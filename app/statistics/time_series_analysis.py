from __future__ import annotations

import csv
import math
import warnings
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd
from arch.unitroot import PhillipsPerron
from arch.utility.exceptions import InfeasibleTestException
from scipy.stats import jarque_bera, norm
from statsmodels.stats.diagnostic import acorr_ljungbox, het_arch
from statsmodels.tsa.arima.model import ARIMA
from statsmodels.tsa.api import VAR
from statsmodels.tsa.holtwinters import ExponentialSmoothing
from statsmodels.regression.linear_model import OLS
from statsmodels.tools.tools import add_constant
from statsmodels.tsa.statespace.sarimax import SARIMAX
from statsmodels.tsa.seasonal import seasonal_decompose
from statsmodels.tsa.stattools import acf, adfuller, kpss, pacf
from statsmodels.tsa.vector_ar.vecm import VECM, coint_johansen, select_coint_rank


_FREQUENCY_LABELS = {
    "A": "Annual",
    "Y": "Annual",
    "Q": "Quarterly",
    "M": "Monthly",
    "W": "Weekly",
    "D": "Daily",
    "H": "Hourly",
    "T": "Minute",
    "S": "Second",
}


def _finite_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return numeric if np.isfinite(numeric) else None


def stationarity_p_value_display(test: dict[str, Any]) -> str:
    value = test.get("p_value")
    if value is None:
        return "Unavailable"
    if (
        test.get("null", "").startswith("The series is stationary")
        and value == 0.1
        and any("actual p-value is greater" in warning for warning in test.get("warnings", []))
    ):
        return "p >= 0.100"
    if 0 <= value < 0.001:
        return "p < 0.001"
    return f"p = {value:.3f}"


def infer_time_frequency(index: pd.Index) -> str | None:
    dates = pd.DatetimeIndex(index).dropna().sort_values().unique()
    if len(dates) < 2:
        return None
    inferred = pd.infer_freq(dates) if len(dates) >= 3 else None
    if inferred:
        return inferred

    month_ordinals = dates.year * 12 + dates.month
    month_steps = np.diff(month_ordinals)
    if len(month_steps) and np.all(dates.day == dates.day[0]):
        minimum_month_step = int(month_steps.min())
        if minimum_month_step == 1 and np.all(dates.day == 1):
            return "MS"
        month_ends = dates.is_month_end.all()
        if minimum_month_step == 1 and month_ends:
            return "ME"
        quarter_starts = dates.month.isin((1, 4, 7, 10)).all() and np.all(month_steps % 3 == 0)
        if quarter_starts and minimum_month_step == 3 and np.all(dates.day == 1):
            return "QS-JAN"
        quarter_ends = dates.month.isin((3, 6, 9, 12)).all() and np.all(month_steps % 3 == 0)
        if quarter_ends and minimum_month_step == 3 and month_ends:
            return "QE-DEC"
        same_month_day = (dates.month == dates.month[0]).all()
        if same_month_day and minimum_month_step == 12 and np.all(month_steps % 12 == 0):
            return f"YS-{dates[0].strftime('%b').upper()}"

    day_steps = np.diff(dates.normalize().asi8) / (24 * 60 * 60 * 1_000_000_000)
    if len(day_steps) and np.all(day_steps % 7 == 0):
        return "W"
    if len(day_steps) and np.all(day_steps % 1 == 0):
        return "D"
    return None


def parse_time_values(values: pd.Series) -> pd.Series:
    """Parse dates, annual values, and common YYYYQn / YYYY-Qn quarter labels."""
    text = values.astype("string").str.strip()
    quarters = text.str.extract(r"^(?P<year>\d{4})[- ]?Q(?P<quarter>[1-4])$", expand=True)
    quarter_mask = quarters["year"].notna()
    parsed = pd.to_datetime(text, errors="coerce", format="mixed")
    parsed.loc[quarter_mask] = pd.NaT
    if quarter_mask.any():
        quarter_periods = pd.PeriodIndex(
            quarters.loc[quarter_mask, "year"] + "Q" + quarters.loc[quarter_mask, "quarter"],
            freq="Q",
        )
        parsed.loc[quarter_mask] = quarter_periods.to_timestamp()

    numeric = pd.to_numeric(values, errors="coerce")
    year_mask = numeric.between(1000, 2200) & numeric.mod(1).eq(0)
    if year_mask.any():
        parsed.loc[year_mask] = pd.to_datetime(
            numeric.loc[year_mask].astype("Int64").astype("string"),
            format="%Y",
            errors="coerce",
        )
    return parsed


def read_time_series_file(path: str | Path) -> pd.DataFrame:
    """Read CSV/XLSX/XLS or text-based PDF tables without fabricating data."""
    file_path = Path(path)
    suffix = file_path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(file_path)
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(file_path)
    if suffix == ".pdf":
        from pypdf import PdfReader

        pages = [page.extract_text() or "" for page in PdfReader(file_path).pages]
        text = "\n".join(pages).strip()
        if not text:
            raise ValueError(
                "No selectable text was found in the PDF. Scanned-PDF OCR is not "
                "available in this import path; export the table to CSV/Excel first."
            )
        return parse_pasted_data(text)
    raise ValueError("Choose a CSV, XLSX, XLS, or text-based PDF file.")


def parse_pasted_data(text: str) -> pd.DataFrame:
    """Parse common spreadsheet clipboard formats, including tab-delimited text."""
    content = str(text or "").strip()
    if not content:
        raise ValueError("Paste a non-empty table before importing.")
    try:
        frame = pd.read_csv(StringIO(content), sep=None, engine="python")
        if len(frame.columns) > 1:
            return frame
    except (csv.Error, pd.errors.ParserError, ValueError):
        pass
    try:
        return pd.read_csv(StringIO(content), sep=r"\s{2,}|\t|,", engine="python")
    except (csv.Error, pd.errors.ParserError, ValueError) as error:
        raise ValueError("The pasted text could not be parsed as a table.") from error


def detect_time_series(dataframe: pd.DataFrame) -> dict[str, Any]:
    """Suggest time and numeric columns and report data-quality issues."""
    date_scores: dict[str, float] = {}
    numeric_columns = [
        str(column)
        for column in dataframe.columns
        if pd.api.types.is_numeric_dtype(dataframe[column])
    ]
    for column in dataframe.columns:
        parsed = parse_time_values(dataframe[column])
        ratio = float(parsed.notna().mean()) if len(parsed) else 0.0
        name_hint = any(word in str(column).lower() for word in ("date", "time", "year", "month", "quarter"))
        score = ratio + (0.25 if name_hint else 0)
        if ratio >= 0.7 or name_hint:
            date_scores[str(column)] = score

    date_column = max(date_scores, key=date_scores.get) if date_scores else None
    values = dataframe[date_column] if date_column is not None else pd.Series(dtype=object)
    parsed_dates = parse_time_values(values).dropna().sort_values()
    frequency = infer_time_frequency(pd.DatetimeIndex(parsed_dates))
    frequency_code = frequency[:1].upper() if frequency else None
    label = _FREQUENCY_LABELS.get(frequency_code, "Other/irregular")

    parsed_all = parse_time_values(values)
    duplicate_count = int(parsed_all.dropna().duplicated().sum())
    valid_dates = parsed_all.dropna()
    descending = bool(len(valid_dates) > 1 and valid_dates.iloc[0] > valid_dates.iloc[-1])
    missing_date_count = int(parsed_all.isna().sum())
    return {
        "date_column": date_column,
        "numeric_columns": numeric_columns,
        "frequency": frequency,
        "frequency_label": label,
        "missing_date_count": missing_date_count,
        "duplicate_date_count": duplicate_count,
        "descending": descending,
        "date_confidence": date_scores.get(date_column, 0.0) if date_column else 0.0,
    }


def validate_time_series(
    dataframe: pd.DataFrame,
    date_column: str,
    value_column: str,
) -> dict[str, Any]:
    """Validate a selected pair and describe issues without imputing values."""
    if date_column not in dataframe.columns or value_column not in dataframe.columns:
        raise ValueError("Select existing date and observation columns.")
    if date_column == value_column:
        raise ValueError("The time and observation columns must be different.")

    dates = parse_time_values(dataframe[date_column])
    values = pd.to_numeric(dataframe[value_column], errors="coerce")
    values = values.where(np.isfinite(values), np.nan)
    valid_dates = dates.dropna()
    valid_rows = dates.notna() & values.notna()
    duplicate_count = int(valid_dates.duplicated().sum())
    chronological = valid_dates.is_monotonic_increasing
    descending = valid_dates.is_monotonic_decreasing and len(valid_dates) > 1
    frequency = None
    missing_periods = 0
    if len(valid_dates) >= 3 and duplicate_count == 0:
        frequency = infer_time_frequency(pd.DatetimeIndex(valid_dates.sort_values()))
        if frequency:
            expected = pd.date_range(valid_dates.min(), valid_dates.max(), freq=frequency)
            present = pd.DatetimeIndex(valid_dates.unique())
            missing_periods = max(0, len(expected.difference(present)))

    issues = []
    if dates.isna().any():
        issues.append(f"{int(dates.isna().sum())} invalid or missing date value(s).")
    if values.isna().any():
        issues.append(f"{int(values.isna().sum())} missing or non-numeric observation(s).")
    if duplicate_count:
        issues.append(f"{duplicate_count} duplicate time period(s); resolve duplicates before analysis.")
    if descending:
        issues.append("Rows are in descending chronological order; analysis will sort them chronologically.")
    elif not chronological:
        issues.append("Rows are not in chronological order; analysis will sort them chronologically.")
    if missing_periods:
        issues.append(f"{missing_periods} expected period(s) are absent; no values were imputed.")
    if not frequency and len(valid_dates) >= 3:
        issues.append("The interval appears irregular or could not be inferred automatically.")

    return {
        "valid_rows": int(valid_rows.sum()),
        "invalid_dates": int(dates.isna().sum()),
        "invalid_values": int(values.isna().sum()),
        "duplicate_periods": duplicate_count,
        "frequency": frequency,
        "frequency_label": _FREQUENCY_LABELS.get(frequency[:1].upper(), "Other/irregular")
        if frequency
        else "Other/irregular",
        "missing_periods": missing_periods,
        "descending": descending,
        "issues": issues,
    }


def prepare_time_series_frame(
    dataframe: pd.DataFrame,
    date_column: str,
    value_column: str,
) -> pd.DataFrame:
    """Prepare a sorted series; reject duplicate periods and preserve missing-period gaps."""
    if not isinstance(dataframe, pd.DataFrame):
        raise TypeError("A pandas DataFrame is required for time-series analysis.")
    if date_column not in dataframe.columns:
        raise ValueError(f"Date column '{date_column}' is not present in the dataset.")
    if value_column not in dataframe.columns:
        raise ValueError(f"Value column '{value_column}' is not present in the dataset.")
    report = validate_time_series(dataframe, date_column, value_column)
    if report["duplicate_periods"]:
        raise ValueError("Duplicate time periods must be resolved before analysis.")
    if report["invalid_dates"] or report["invalid_values"]:
        raise ValueError(
            "Selected observations contain invalid/missing dates or non-numeric/missing values. "
            "Review and explicitly approve preprocessing before analysis."
        )

    frame = dataframe[[date_column, value_column]].copy()
    frame[date_column] = parse_time_values(frame[date_column])
    frame[value_column] = pd.to_numeric(frame[value_column], errors="coerce")
    frame[value_column] = frame[value_column].where(
        np.isfinite(frame[value_column]), np.nan
    )
    frame = frame.dropna(subset=[date_column, value_column]).sort_values(date_column)
    if len(frame) < 3:
        raise ValueError("At least three valid time points are required for time-series analysis.")
    frame = frame.set_index(date_column)
    frequency = pd.infer_freq(frame.index) if len(frame) >= 3 else None
    if frequency:
        frame.index = pd.DatetimeIndex(frame.index, freq=frequency)
    frame.columns = ["value"]
    return frame


def _forecast_model(
    series: pd.Series,
    horizon: int,
    model_name: str,
    seasonal_period: int | None,
    arima_order: tuple[int, int, int] = (1, 1, 1),
    seasonal_order: tuple[int, int, int] = (1, 1, 1),
    alpha: float = 0.05,
):
    if horizon < 1:
        raise ValueError("Forecast horizon must be at least one period.")
    frequency = series.index.freq or series.index.inferred_freq
    if frequency is None:
        raise ValueError("Forecast models require a regular time index.")
    future_index = pd.date_range(
        series.index[-1], periods=horizon + 1, freq=frequency
    )[1:]
    values = None
    fitted = None

    if model_name in {"ARIMA", "SARIMA", "AR(1)", "MA(1)", "ARMA(1,1)"}:
        if model_name == "SARIMA":
            if seasonal_period is None or seasonal_period <= 1:
                raise ValueError("SARIMA requires a regular seasonal frequency.")
            if len(series) < seasonal_period * 2:
                raise ValueError(
                    f"SARIMA requires at least {seasonal_period * 2} observations for the selected seasonal period."
                )
            fitted = ARIMA(
                series,
                order=arima_order,
                seasonal_order=(*seasonal_order, seasonal_period),
            ).fit()
        else:
            order = {
                "AR(1)": (1, 0, 0),
                "MA(1)": (0, 0, 1),
                "ARMA(1,1)": (1, 0, 1),
            }.get(model_name, arima_order)
            fitted = ARIMA(series, order=order).fit()
        forecast = fitted.get_forecast(horizon)
        values = forecast.predicted_mean
        interval = forecast.conf_int(alpha=alpha)
        lower = interval.iloc[:, 0]
        upper = interval.iloc[:, 1]
        if not (
            np.isfinite(np.asarray(values, dtype=float)).all()
            and np.isfinite(interval.to_numpy(dtype=float)).all()
        ):
            raise ValueError("The fitted model returned non-finite forecasts or intervals.")
    elif model_name == "Naive":
        values = pd.Series(
            np.repeat(float(series.iloc[-1]), horizon), index=future_index
        )
        fitted_values = series.shift(1)
        fitted = SimpleNamespace(
            resid=(series - fitted_values).dropna(),
            fittedvalues=fitted_values.dropna(),
            aic=None,
            bic=None,
            mle_retvals=None,
        )
    elif model_name == "Seasonal naive":
        if seasonal_period is None or seasonal_period <= 1:
            raise ValueError("Seasonal naive forecasting requires a seasonal frequency.")
        if len(series) < seasonal_period:
            raise ValueError(
                f"Seasonal naive forecasting requires at least {seasonal_period} observations."
            )
        seasonal_values = series.iloc[-seasonal_period:].to_numpy(dtype=float)
        values = pd.Series(np.resize(seasonal_values, horizon), index=future_index)
        fitted_values = series.shift(seasonal_period)
        fitted = SimpleNamespace(
            resid=(series - fitted_values).dropna(),
            fittedvalues=fitted_values.dropna(),
            aic=None,
            bic=None,
            mle_retvals=None,
        )
    elif model_name in {"Historical mean", "Mean", "Linear trend"}:
        x = np.arange(len(series), dtype=float)
        if model_name == "Linear trend":
            design = np.column_stack((np.ones(len(series)), x))
            future_design = np.column_stack(
                (np.ones(horizon), np.arange(len(series), len(series) + horizon))
            )
        else:
            design = np.ones((len(series), 1))
            future_design = np.ones((horizon, 1))
        ols_fit = OLS(series.to_numpy(dtype=float), design).fit()
        values = pd.Series(ols_fit.predict(future_design), index=future_index)
        fitted = SimpleNamespace(
            fittedvalues=pd.Series(ols_fit.fittedvalues, index=series.index),
            resid=pd.Series(ols_fit.resid, index=series.index),
            aic=float(ols_fit.aic),
            bic=float(ols_fit.bic),
            mle_retvals=None,
        )
    elif model_name in {"Simple exponential smoothing", "SES"}:
        fitted = ExponentialSmoothing(
            series, initialization_method="estimated"
        ).fit(optimized=True)
        values = fitted.forecast(horizon)
    elif model_name == "Holt":
        fitted = ExponentialSmoothing(
            series, trend="add", initialization_method="estimated"
        ).fit(optimized=True)
        values = fitted.forecast(horizon)
    elif model_name in {"Holt-Winters", "Exponential smoothing"}:
        period = (
            seasonal_period
            if seasonal_period and seasonal_period > 1
            and len(series) >= seasonal_period * 2
            else None
        )
        fitted = ExponentialSmoothing(
            series,
            trend="add",
            seasonal="add" if period else None,
            seasonal_periods=period,
            initialization_method="estimated",
        ).fit(optimized=True)
        values = fitted.forecast(horizon)
    else:
        raise ValueError(f"Unsupported forecasting model: {model_name}")

    values = pd.Series(np.asarray(values, dtype=float), index=future_index)
    if not np.isfinite(values.to_numpy(dtype=float)).all():
        raise ValueError("The fitted model returned non-finite forecasts.")
    if model_name not in {"ARIMA", "SARIMA"}:
        residuals = np.asarray(getattr(fitted, "resid", []), dtype=float)
        residuals = residuals[np.isfinite(residuals)]
        residual_scale = (
            float(np.std(residuals, ddof=1)) if len(residuals) > 1 else 0.0
        )
        z_value = float(abs(norm.ppf(alpha / 2)))
        steps = np.sqrt(np.arange(1, horizon + 1))
        lower = pd.Series(
            values.to_numpy() - z_value * residual_scale * steps,
            index=future_index,
        )
        upper = pd.Series(
            values.to_numpy() + z_value * residual_scale * steps,
            index=future_index,
        )
    return fitted, values, lower, upper


def stationarity_test_conclusion(
    test_name: str,
    p_value: float | None,
    significance_level: float,
) -> dict[str, Any]:
    """Translate a p-value using the test's own null hypothesis."""
    normalized_name = test_name.strip().lower()
    if normalized_name not in {"adf", "pp", "phillips-perron", "kpss"}:
        raise ValueError(f"Unsupported stationarity test: {test_name}")
    if p_value is None or not np.isfinite(p_value):
        return {
            "reject_null": None,
            "conclusion": "The test did not return a usable p-value.",
        }
    reject_null = bool(float(p_value) < significance_level)
    if normalized_name == "kpss":
        conclusion = (
            "Reject the stationarity null; evidence against stationarity under the specified deterministic terms."
            if reject_null
            else "Fail to reject the stationarity null; this is not proof of stationarity."
        )
    else:
        conclusion = (
            "Reject the unit-root null; evidence supports stationarity under the specified deterministic terms."
            if reject_null
            else "Fail to reject the unit-root null; this does not establish that a unit root exists."
        )
    return {"reject_null": reject_null, "conclusion": conclusion}


def _stationarity_tests(
    series: pd.Series,
    significance_level: float,
    deterministic: str,
    deterministic_specification: str,
) -> dict[str, Any]:
    tests: dict[str, Any] = {}
    test_specs = (
        ("ADF", lambda: adfuller(series, autolag="AIC", regression=deterministic, result_object=True)),
        ("Phillips-Perron", lambda: PhillipsPerron(series, trend=deterministic)),
    )
    for name, run_test in test_specs:
        try:
            result = run_test()
            test_statistic = _finite_or_none(
                result.statistic if name == "ADF" else result.stat
            )
            test_p_value = _finite_or_none(result.pvalue)
            if test_statistic is None or test_p_value is None:
                tests[name] = {
                    "error": "The test returned a non-finite statistic or p-value.",
                    "reject_null": None,
                }
                continue
            test = {
                "statistic": test_statistic,
                "p_value": test_p_value,
                "critical_values": {
                    key: _finite_or_none(value)
                    for key, value in result.critical_values.items()
                },
                "null": "The series has a unit root.",
                "alternative": "The series is stationary under the specified deterministic terms.",
                "scope": deterministic_specification,
            }
            if name == "ADF":
                # Keep the lag-selection choice and effective sample visible
                # so ADF results can be independently reviewed and reproduced.
                test.update(
                    {
                        "autolag": "AIC",
                        "used_lags": int(result.lags),
                        "observations": int(result.nobs),
                    }
                )
            test.update(
                stationarity_test_conclusion(
                    name, test["p_value"], significance_level
                )
            )
            test["p_value_display"] = stationarity_p_value_display(test)
            tests[name] = test
        except (
            ValueError,
            InfeasibleTestException,
            np.linalg.LinAlgError,
            OverflowError,
        ) as error:
            tests[name] = {"error": str(error), "reject_null": None}

    if deterministic != "n":
        try:
            with warnings.catch_warnings(record=True) as test_warnings:
                warnings.simplefilter("always")
                result = kpss(
                    series,
                    regression="ct" if deterministic == "ct" else "c",
                    nlags="auto",
                    result_object=True,
                )
            test_statistic = _finite_or_none(result.statistic)
            test_p_value = _finite_or_none(result.pvalue)
            if test_statistic is None or test_p_value is None:
                tests["KPSS"] = {
                    "error": "The test returned a non-finite statistic or p-value.",
                    "reject_null": None,
                }
                return tests
            test = {
                "statistic": test_statistic,
                "p_value": test_p_value,
                "critical_values": {
                    key: _finite_or_none(value)
                    for key, value in result.critical_values.items()
                },
                "null": "The series is stationary under the specified deterministic terms.",
                "alternative": "The series is not stationary under the specified deterministic terms.",
                "scope": deterministic_specification,
            }
            test.update(
                stationarity_test_conclusion(
                    "KPSS", test["p_value"], significance_level
                )
            )
            test["warnings"] = [str(item.message) for item in test_warnings]
            test["p_value_display"] = stationarity_p_value_display(test)
            tests["KPSS"] = test
        except (ValueError, np.linalg.LinAlgError, OverflowError) as error:
            tests["KPSS"] = {"error": str(error), "reject_null": None}
    else:
        tests["KPSS"] = {
            "error": "KPSS does not support a no-constant/no-trend regression.",
            "reject_null": None,
        }
    return tests


def _combined_stationarity_interpretation(
    tests: dict[str, Any], scope: str, series_name: str = "level"
) -> str:
    adf = tests.get("ADF", {}).get("reject_null")
    pp = tests.get("Phillips-Perron", {}).get("reject_null")
    kpss = tests.get("KPSS", {}).get("reject_null")
    unit_root_rejected = [decision for decision in (adf, pp) if decision is not None]
    if series_name == "level":
        label = (
            "level stationarity"
            if scope == "level"
            else "trend stationarity in levels"
            if scope == "trend"
            else "zero-mean stationarity in levels"
        )
    else:
        transformed_name = {
            "first_difference": "first-difference",
            "second_difference": "second-difference",
        }.get(series_name, series_name.replace("_", "-"))
        label = (
            f"{transformed_name} stationarity under the "
            f"{scope} deterministic specification"
        )
    if not unit_root_rejected or kpss is None:
        return f"{label.title()} assessment is incomplete; interpret available tests cautiously."
    any_unit_root_rejection = any(unit_root_rejected)
    all_unit_root_rejected = len(unit_root_rejected) == 2 and all(unit_root_rejected)
    unit_root_tests_disagree = (
        len(unit_root_rejected) == 2 and unit_root_rejected[0] != unit_root_rejected[1]
    )
    if (any_unit_root_rejection and kpss) or unit_root_tests_disagree:
        return (
            f"The tests provide conflicting evidence about {label}; the ADF/PP tests and/or KPSS "
            "do not agree. Do not force a definitive stationary/non-stationary classification."
        )
    if all_unit_root_rejected and not kpss:
        return (
            f"The tests provide evidence consistent with {label} at the selected significance level; "
            "this is evidence, not proof."
        )
    if not any_unit_root_rejection and kpss:
        return (
            f"The tests provide evidence against {label}, but failure to reject the ADF/PP unit-root "
            "null does not establish that a unit root exists."
        )
    return (
        f"The tests do not provide a decisive result for {label}: ADF/PP fail to reject the unit-root "
        "null and KPSS fails to reject its stationarity null. Consider sample size, deterministic "
        "terms, and structural breaks."
    )


def _forecast_metrics(actual: np.ndarray, predicted: np.ndarray) -> dict[str, float | None]:
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    if actual.shape != predicted.shape or actual.size == 0:
        raise ValueError("Forecast metrics require non-empty, equally sized actual and predicted values.")
    if not np.isfinite(actual).all() or not np.isfinite(predicted).all():
        raise ValueError("Forecast predictions and actual values must be finite.")
    residual = actual - predicted
    nonzero = np.abs(actual) > np.finfo(float).eps
    return {
        "MSE": float(np.mean(np.square(residual))),
        "RMSE": float(np.sqrt(np.mean(np.square(residual)))),
        "MAE": float(np.mean(np.abs(residual))),
        "MAPE": float(np.mean(np.abs(residual[nonzero] / actual[nonzero])) * 100)
        if nonzero.any()
        else None,
    }


def residual_diagnostic_warnings(
    diagnostics: dict[str, Any],
    convergence_status: str,
    significance_level: float,
) -> list[str]:
    warning_text = {
        "Ljung-Box p-value": "Ljung-Box rejects no residual autocorrelation.",
        "Jarque-Bera p-value": "Jarque-Bera rejects residual normality.",
        "ARCH LM p-value": "ARCH LM detects conditional heteroskedasticity.",
    }
    warnings = [
        f"{message} Review model adequacy at the selected significance level."
        for key, message in warning_text.items()
        if diagnostics.get(key) is not None
        and diagnostics[key] < significance_level
    ]
    if convergence_status == "Did not converge.":
        warnings.append(
            "The model optimizer did not converge; inspect the fit before interpreting results."
        )
    return warnings


def _compare_forecasts(
    train: pd.Series,
    test: pd.Series,
    selected_model: str,
    arima_order: tuple[int, int, int],
    seasonal_order: tuple[int, int, int],
    seasonal_period: int | None,
) -> tuple[dict[str, Any], list[str]]:
    actual = test.to_numpy(dtype=float)
    horizon = len(test)
    candidates: dict[str, Any] = {}
    warnings = []
    model_specs = [
        ("Naive", (1, 1, 1), seasonal_order, seasonal_period, "Naive"),
        ("Historical mean", (1, 1, 1), seasonal_order, None, "Mean"),
        ("Linear trend", (1, 1, 1), seasonal_order, None, "Linear trend"),
        ("Simple exponential smoothing", (1, 1, 1), seasonal_order, None, "SES"),
        ("Holt", (1, 1, 1), seasonal_order, None, "Holt"),
        ("AR(1)", (1, 1, 1), seasonal_order, None, "AR(1)"),
        ("MA(1)", (1, 1, 1), seasonal_order, None, "MA(1)"),
        ("ARMA(1,1)", (1, 1, 1), seasonal_order, None, "ARMA(1,1)"),
        ("ARIMA", (1, 1, 1), seasonal_order, None, "ARIMA(1,1,1)"),
    ]
    if seasonal_period and seasonal_period > 1:
        model_specs.extend(
            [
                ("Seasonal naive", (1, 1, 1), seasonal_order, seasonal_period, "Seasonal naive"),
                ("Holt-Winters", (1, 1, 1), seasonal_order, seasonal_period, "Holt-Winters"),
                ("Exponential smoothing", (1, 1, 1), seasonal_order, seasonal_period,
                 "Exponential smoothing"),
                ("SARIMA", (1, 1, 1), seasonal_order, seasonal_period,
                 _forecast_model_label("SARIMA", (1, 1, 1), seasonal_order, seasonal_period)),
            ]
        )
    selected_label = _forecast_model_label(
        selected_model, arima_order, seasonal_order, seasonal_period
    )
    selected_display = "Holt" if selected_model == "Exponential smoothing" and seasonal_period is None else selected_label
    if not any(spec[4] == selected_display for spec in model_specs):
        model_specs.append(
            (
                selected_model,
                arima_order,
                seasonal_order,
                seasonal_period,
                selected_display,
            )
        )
    for name, order, seasonal, candidate_period, display_name in model_specs:
        try:
            fitted, prediction, _, _ = _forecast_model(
                train,
                horizon,
                name,
                candidate_period,
                order,
                seasonal,
            )
            candidates[display_name] = (
                np.asarray(prediction, dtype=float),
                _finite_or_none(getattr(fitted, "aic", np.nan)),
                _finite_or_none(getattr(fitted, "bic", np.nan)),
            )
        except (ValueError, np.linalg.LinAlgError) as error:
            warnings.append(f"{display_name} comparison could not be completed: {error}")
    comparisons = {
        name: {
            **_forecast_metrics(actual, prediction),
            "AIC": aic,
            "BIC": bic,
            "actual": [float(value) for value in actual],
            "predicted": [float(value) for value in prediction],
        }
        for name, (prediction, aic, bic) in candidates.items()
    }
    return comparisons, warnings


def _forecast_model_label(
    model_name: str,
    arima_order: tuple[int, int, int],
    seasonal_order: tuple[int, int, int],
    seasonal_period: int | None,
) -> str:
    if model_name in {"Historical mean", "Mean"}:
        return "Mean"
    if model_name in {"Simple exponential smoothing", "SES"}:
        return "SES"
    if model_name == "Holt-Winters":
        return "Holt-Winters"
    if model_name == "Exponential smoothing":
        return "Holt-Winters" if seasonal_period and seasonal_period > 1 else "Holt"
    if model_name == "ARIMA":
        return f"ARIMA({','.join(map(str, arima_order))})"
    if model_name == "SARIMA":
        return (
            f"SARIMA({','.join(map(str, arima_order))})"
            f"({','.join(map(str, seasonal_order))},{seasonal_period})"
        )
    return model_name


def analyze_time_series(
    dataframe: pd.DataFrame,
    date_column: str,
    value_column: str,
    forecast_horizon: int = 6,
    seasonal_period: int | None = None,
    significance_level: float = 0.05,
    model_name: str = "Exponential smoothing",
    test_size: int | None = None,
    deterministic_specification: str = "Constant",
    arima_order: tuple[int, int, int] = (1, 1, 1),
    seasonal_order: tuple[int, int, int] = (1, 1, 1),
    include_second_difference: bool = False,
    train_fraction: float = 0.8,
    validation_strategy: str = "holdout",
    difference_deterministic_specification: str | None = None,
) -> dict[str, Any]:
    frame = prepare_time_series_frame(dataframe, date_column, value_column)
    series = frame["value"].astype(float)
    horizon = int(forecast_horizon)
    if horizon < 1:
        raise ValueError("Forecast horizon must be at least one period.")
    if not 0 < significance_level < 1:
        raise ValueError("Significance level must be between zero and one.")
    if not 0 < train_fraction < 1:
        raise ValueError("Training percentage must be between zero and one.")
    if validation_strategy not in {"holdout", "rolling-window", "expanding-window"}:
        raise ValueError(
            "Choose holdout, rolling-window, or expanding-window validation."
        )
    supported_models = {
        "Naive",
        "Seasonal naive",
        "Historical mean",
        "Linear trend",
        "AR(1)",
        "MA(1)",
        "ARMA(1,1)",
        "ARIMA",
        "SARIMA",
        "Simple exponential smoothing",
        "Holt",
        "Holt-Winters",
        "Exponential smoothing",
    }
    if model_name not in supported_models:
        raise ValueError("Select a supported forecasting model.")
    if len(arima_order) != 3 or len(seasonal_order) != 3 or any(
        int(value) < 0 for value in (*arima_order, *seasonal_order)
    ):
        raise ValueError("ARIMA order parameters must contain three non-negative integers.")
    deterministic_terms = {
        "No constant or trend": "n",
        "Constant": "c",
        "Constant and trend": "ct",
    }
    if deterministic_specification not in deterministic_terms:
        raise ValueError("Select a supported deterministic specification.")
    deterministic = deterministic_terms[deterministic_specification]
    difference_deterministic_specification = (
        difference_deterministic_specification or deterministic_specification
    )
    if difference_deterministic_specification not in deterministic_terms:
        raise ValueError("Select a supported differenced-series deterministic specification.")
    difference_deterministic = deterministic_terms[
        difference_deterministic_specification
    ]

    validation = validate_time_series(dataframe, date_column, value_column)
    freq = validation["frequency"]
    period = seasonal_period if seasonal_period and seasonal_period > 1 else (
        12 if freq and freq.startswith(("M", "ME")) else 4 if freq and freq.startswith("Q") else 1
    )
    if len(series) < 20:
        validation["issues"].append("Small sample: estimates and forecasts may be unstable.")
    regular_frequency = pd.infer_freq(series.index) if len(series) >= 3 else None
    if regular_frequency is None:
        validation["issues"].append(
            "Forecasting and holdout evaluation were skipped because the time intervals are irregular or incomplete."
        )
    scope = (
        "trend"
        if deterministic == "ct"
        else "level"
        if deterministic == "c"
        else "zero-mean"
    )
    first_difference = series.diff().dropna()
    second_difference = first_difference.diff().dropna()
    stationarity_assessment = {
        "level": _stationarity_tests(
            series, significance_level, deterministic, deterministic_specification
        ),
        "first_difference": _stationarity_tests(
            first_difference,
            significance_level,
            difference_deterministic,
            difference_deterministic_specification,
        ),
    }
    if include_second_difference:
        stationarity_assessment["second_difference"] = _stationarity_tests(
            second_difference,
            significance_level,
            difference_deterministic,
            difference_deterministic_specification,
        )
    for level, tests in stationarity_assessment.items():
        for test_name, test in tests.items():
            if test.get("error"):
                validation["issues"].append(
                    f"{level.replace('_', ' ').title()} {test_name} test unavailable: {test['error']}"
                )
            validation["issues"].extend(
                f"{level.replace('_', ' ').title()} {test_name}: {warning}"
                for warning in test.get("warnings", [])
            )
    stationarity = stationarity_assessment["level"]
    stationarity_interpretations = {
        name: _combined_stationarity_interpretation(tests, scope, name)
        for name, tests in stationarity_assessment.items()
    }

    x = np.arange(len(series), dtype=float)
    slope, intercept = np.polyfit(x, series.to_numpy(), 1)
    trend = pd.Series(intercept + slope * x, index=series.index, name="linear_trend")
    rolling_window = min(max(3, period), max(3, len(series) // 3))
    rolling_mean = series.rolling(rolling_window, min_periods=rolling_window).mean()
    rolling_standard_deviation = series.rolling(
        rolling_window, min_periods=rolling_window
    ).std()

    decomposition = None
    if period > 1 and len(series) >= period * 2:
        try:
            decomposition = seasonal_decompose(
                series,
                model="multiplicative" if (series > 0).all() else "additive",
                period=period,
                extrapolate_trend="period",
            )
        except ValueError as error:
            validation["issues"].append(f"Seasonal decomposition unavailable: {error}")
    elif period > 1:
        validation["issues"].append(
            f"Seasonal analysis needs at least {period * 2} observations; it was skipped."
        )

    requested_test_size = (
        math.ceil(len(series) * (1 - train_fraction))
        if test_size is None
        else max(0, int(test_size))
    )
    test_size = min(requested_test_size, max(0, len(series) - 5))
    if test_size == 0 and requested_test_size > 0:
        validation["issues"].append(
            "Out-of-sample evaluation was skipped because the dataset does not leave "
            "at least five training observations."
        )
    elif test_size == 0:
        validation["issues"].append(
            "Out-of-sample evaluation was disabled; no holdout forecast accuracy is reported."
        )
    elif len(series) < 8:
        test_size = 0
        validation["issues"].append(
            "Out-of-sample evaluation was skipped because fewer than eight observations "
            "are available for a minimally useful training/holdout split."
        )
    evaluation: dict[str, float | None] = {}
    holdout = {"periods": [], "actual": [], "predicted": []}
    model_comparison = {}
    if test_size and regular_frequency:
        train, test = series.iloc[:-test_size], series.iloc[-test_size:]
        try:
            if validation_strategy == "holdout":
                model_comparison, comparison_warnings = _compare_forecasts(
                    train,
                    test,
                    model_name,
                    arima_order,
                    seasonal_order,
                    period if period > 1 else None,
                )
                holdout = {
                    "periods": [str(value) for value in test.index],
                    "actual": [float(value) for value in test.to_numpy()],
                    "predicted": [],
                }
                validation_actual = test.to_numpy(dtype=float)
            else:
                fold_predictions: dict[str, list[float]] = {}
                validation_actual_values = []
                comparison_warnings = []
                initial_train_size = len(train)
                for position in range(initial_train_size, len(series)):
                    start = (
                        position - initial_train_size
                        if validation_strategy == "rolling-window"
                        else 0
                    )
                    fold_train = series.iloc[start:position]
                    fold_test = series.iloc[position : position + 1]
                    fold_comparison, fold_warnings = _compare_forecasts(
                        fold_train,
                        fold_test,
                        model_name,
                        arima_order,
                        seasonal_order,
                        period if period > 1 else None,
                    )
                    comparison_warnings.extend(fold_warnings)
                    validation_actual_values.append(float(fold_test.iloc[0]))
                    for candidate_name, candidate_result in fold_comparison.items():
                        fold_predictions.setdefault(candidate_name, []).extend(
                            candidate_result["predicted"]
                        )
                validation_actual = np.asarray(validation_actual_values, dtype=float)
                model_comparison = {
                    name: {
                        **_forecast_metrics(validation_actual, np.asarray(predictions, dtype=float)),
                        "AIC": None,
                        "BIC": None,
                        "actual": [float(value) for value in validation_actual],
                        "predicted": [float(value) for value in predictions],
                    }
                    for name, predictions in fold_predictions.items()
                    if len(predictions) == len(validation_actual)
                }
                holdout = {
                    "periods": [str(value) for value in test.index],
                    "actual": [float(value) for value in test.to_numpy()],
                    "predicted": [],
                }
            validation["issues"].extend(comparison_warnings)
            selected_label = _forecast_model_label(
                model_name,
                arima_order,
                seasonal_order,
                period if period > 1 else None,
            )
            selected_metrics = model_comparison.get(selected_label)
            if selected_metrics is None:
                validation["issues"].append(
                    f"Selected model {selected_label} could not be evaluated; other model comparisons are retained."
                )
            else:
                evaluation = {
                    key: selected_metrics[key]
                    for key in ("MSE", "RMSE", "MAE", "MAPE")
                }
                holdout = {
                    **holdout,
                    "predicted": selected_metrics["predicted"],
                }
        except (ValueError, np.linalg.LinAlgError) as error:
            validation["issues"].append(f"Out-of-sample evaluation failed: {error}")
    elif test_size:
        validation["issues"].append(
            "Holdout evaluation was skipped because chronological periods are not regular."
        )

    if regular_frequency:
        fitted, future, lower, upper = _forecast_model(
            series,
            horizon,
            model_name,
            period if period > 1 else None,
            arima_order,
            seasonal_order,
            significance_level,
        )
    else:
        fitted = None
        future = pd.Series(dtype=float)
        lower = pd.Series(dtype=float)
        upper = pd.Series(dtype=float)
    forecast_intervals = {}
    if fitted is not None and len(future):
        for confidence in (0.80, 0.95):
            try:
                if hasattr(fitted, "get_forecast"):
                    interval = fitted.get_forecast(len(future)).conf_int(
                        alpha=1 - confidence
                    )
                    band_lower = np.asarray(interval.iloc[:, 0], dtype=float)
                    band_upper = np.asarray(interval.iloc[:, 1], dtype=float)
                    method = "model-based"
                else:
                    model_residuals = np.asarray(
                        getattr(fitted, "resid", []), dtype=float
                    )
                    model_residuals = model_residuals[np.isfinite(model_residuals)]
                    scale = float(np.std(model_residuals, ddof=1)) if len(model_residuals) > 1 else 0.0
                    steps = np.sqrt(np.arange(1, len(future) + 1, dtype=float))
                    z_value = float(norm.ppf((1 + confidence) / 2))
                    band_lower = np.asarray(future, dtype=float) - z_value * scale * steps
                    band_upper = np.asarray(future, dtype=float) + z_value * scale * steps
                    method = "approximate residual-based"
                forecast_intervals[f"{int(confidence * 100)}%"] = {
                    "lower": [float(value) for value in band_lower],
                    "upper": [float(value) for value in band_upper],
                    "method": method,
                }
            except (ValueError, TypeError, IndexError, np.linalg.LinAlgError):
                continue
    diagnostics = {}
    diagnostic_warnings = []
    residuals = np.asarray(getattr(fitted, "resid", []), dtype=float)
    residuals = residuals[np.isfinite(residuals)]
    if len(residuals) > 3:
        lag = min(10, max(1, len(residuals) // 5))
        ljung_box_p = _finite_or_none(
            acorr_ljungbox(
                residuals, lags=[lag], return_df=True
            )["lb_pvalue"].iloc[0]
        )
        diagnostics["Ljung-Box p-value"] = ljung_box_p
        normality = jarque_bera(residuals)
        diagnostics["Jarque-Bera statistic"] = _finite_or_none(normality.statistic)
        diagnostics["Jarque-Bera p-value"] = _finite_or_none(normality.pvalue)
        arch_lm, arch_pvalue, _, _ = het_arch(residuals, nlags=lag)
        diagnostics["ARCH LM statistic"] = _finite_or_none(arch_lm)
        diagnostics["ARCH LM p-value"] = _finite_or_none(arch_pvalue)
    fitted_residuals = np.asarray(getattr(fitted, "resid", []), dtype=float)
    residual_index = (
        getattr(getattr(fitted, "resid", None), "index", pd.Index([]))
        if fitted is not None
        else pd.Index([])
    )
    finite_residuals = np.isfinite(fitted_residuals)
    residual_plot = {
        "periods": [str(value) for value in residual_index[finite_residuals]],
        "values": [float(value) for value in fitted_residuals[finite_residuals]],
    }
    residual_acf = []
    if len(residuals) >= 5:
        residual_acf = [
            _finite_or_none(value)
            for value in acf(residuals, nlags=min(20, len(residuals) // 2 - 1), fft=False)
        ]
    mle_retvals = getattr(fitted, "mle_retvals", None)
    if fitted is None:
        convergence_status = "Not fitted because the time intervals are irregular or incomplete."
    elif mle_retvals is None:
        convergence_status = "Not exposed by this model implementation."
    elif (
        mle_retvals.get("converged", mle_retvals.get("success")) is not None
        and bool(mle_retvals.get("converged", mle_retvals.get("success")))
    ):
        convergence_status = "Converged."
    elif mle_retvals.get("converged", mle_retvals.get("success")) is None:
        convergence_status = "Not exposed by this model implementation."
    else:
        convergence_status = "Did not converge."
    diagnostic_warnings = residual_diagnostic_warnings(
        diagnostics, convergence_status, significance_level
    )
    validation["issues"].extend(diagnostic_warnings)

    changes = series.diff()
    percent_change = series.pct_change(fill_method=None) * 100
    percent_change = percent_change.replace([np.inf, -np.inf], np.nan)
    elapsed_years = (
        (series.index[-1] - series.index[0]).days / 365.2425
        if len(series) > 1
        else 0
    )
    cagr = (
        float(((series.iloc[-1] / series.iloc[0]) ** (1 / elapsed_years) - 1) * 100)
        if elapsed_years > 0 and series.iloc[0] > 0 and series.iloc[-1] > 0
        else None
    )
    description = {
        "count": int(series.count()),
        "missing_values": validation["invalid_values"],
        "mean": _finite_or_none(series.mean()),
        "median": _finite_or_none(series.median()),
        "minimum": _finite_or_none(series.min()),
        "maximum": _finite_or_none(series.max()),
        "range": _finite_or_none(series.max() - series.min()),
        "variance": _finite_or_none(series.var(ddof=1)),
        "standard_deviation": _finite_or_none(series.std(ddof=1)),
        "skewness": _finite_or_none(series.skew()),
        "kurtosis": _finite_or_none(series.kurtosis()),
        "mean_absolute_change": _finite_or_none(changes.abs().mean()),
        "mean_percentage_change": _finite_or_none(percent_change.mean()),
        "compound_annual_growth_rate_percent": cagr,
    }
    correlogram = {"acf": [], "pacf": []}
    if len(series) >= 5:
        max_lag = min(20, len(series) // 2 - 1)
        correlogram = {
            "acf": [_finite_or_none(value) for value in acf(series, nlags=max_lag, fft=False)],
            "pacf": [_finite_or_none(value) for value in pacf(series, nlags=max_lag, method="ywm")],
        }
    seasonal_components = {}
    decomposition_plot = {}
    if decomposition is not None:
        seasonal_values = decomposition.seasonal
        decomposition_plot = {
            "periods": [str(value) for value in series.index],
            "observed": [float(value) for value in series.to_numpy(dtype=float)],
            "trend": [
                _finite_or_none(value) for value in decomposition.trend.to_numpy(dtype=float)
            ],
            "seasonal": [
                _finite_or_none(value) for value in decomposition.seasonal.to_numpy(dtype=float)
            ],
            "resid": [
                _finite_or_none(value) for value in decomposition.resid.to_numpy(dtype=float)
            ],
            "model": "multiplicative" if (series > 0).all() else "additive",
            "period": int(period),
        }
        seasonal_groups = (
            seasonal_values.index.month if period == 12 else seasonal_values.index.quarter
        )
        seasonal_components = {
            int(key): _finite_or_none(value)
            for key, value in seasonal_values.groupby(seasonal_groups).mean().items()
        }
    summary_lines = [
        f"Time-series analysis: {value_column}",
        f"Observations: {len(series)}; date range: {series.index.min().date()} to {series.index.max().date()}",
        f"Frequency: {validation['frequency_label']}",
        f"Level-series deterministic terms: {deterministic_specification}; "
        f"differenced-series deterministic terms: {difference_deterministic_specification}",
        f"Mean: {series.mean():.3f}; median: {series.median():.3f}",
        f"Linear trend slope per observation: {slope:.3f}",
        f"Model: {model_name}; forecast horizon: {horizon if regular_frequency else 'not available'}",
    ]
    for name, result in stationarity.items():
        if "error" in result:
            summary_lines.append(f"{name}: unavailable ({result['error']})")
        else:
            summary_lines.append(
                f"{name}: statistic {result['statistic']:.3f}, "
                f"{stationarity_p_value_display(result)}; "
                f"{result['conclusion']}"
            )
    summary_lines.extend(
        f"{name.replace('_', ' ').title()}: {interpretation}"
        for name, interpretation in stationarity_interpretations.items()
    )
    summary_lines.extend(
        [
            f"Chronological evaluation: {len(series) - len(holdout['periods']) if holdout['periods'] else 0} "
            f"training observations; {len(holdout['periods'])} holdout observations. "
            "Candidates are fit on training observations only and scored on the holdout.",
            f"Final estimation refits {model_name} on all {len(series)} observations "
            "before producing future forecasts."
            if regular_frequency
            else "Final estimation and future forecasts were unavailable because the time intervals are irregular or incomplete.",
        ]
    )
    summary_lines.extend(f"Warning: {issue}" for issue in validation["issues"])

    if model_name == "SARIMA":
        model_specification = (
            f"SARIMA({','.join(map(str, arima_order))})"
            f"({','.join(map(str, seasonal_order))},{period})"
        )
    elif model_name == "ARIMA":
        model_specification = f"ARIMA({','.join(map(str, arima_order))})"
    elif model_name == "Exponential smoothing":
        model_specification = "Additive Holt-Winters" if period > 1 else "Holt linear trend"
    else:
        model_specification = model_name

    interval_method = (
        "Formal model-based prediction interval"
        if model_name in {"ARIMA", "SARIMA"}
        else "Approximate residual-based interval"
    )
    interval_assumptions = (
        "ARIMA/SARIMA intervals use the fitted state-space model's forecast covariance and assume the specified model is correctly specified."
        if model_name in {"ARIMA", "SARIMA"}
        else         f"Approximate {100 * (1 - significance_level):.1f}% intervals use sample residual standard deviation multiplied by sqrt(horizon); they assume independent, homoskedastic, approximately Gaussian forecast errors and are not formal model-based intervals."
    )
    test_evidence = "; ".join(
        f"{name} {stationarity_p_value_display(test)} ({test['conclusion']})"
        for name, test in stationarity.items()
        if "p_value" in test
    ) or "No level stationarity tests returned usable p-values."
    direction = "increasing" if slope > 0 else "decreasing" if slope < 0 else "flat"
    first_difference_tests = stationarity_assessment["first_difference"]
    first_difference_evidence = "; ".join(
        f"{name} {stationarity_p_value_display(test)} ({test['conclusion']})"
        for name, test in first_difference_tests.items()
        if "p_value" in test
    ) or "No first-difference stationarity tests returned usable p-values."
    forecast_accuracy_interpretation = (
        f"Chronological holdout performance over {len(holdout['periods'])} observations: "
        + "; ".join(
            f"{name} RMSE={metrics['RMSE']:.3f}, MAE={metrics['MAE']:.3f}, "
            f"MAPE={metrics['MAPE']:.3f}%"
            if metrics["MAPE"] is not None
            else f"{name} RMSE={metrics['RMSE']:.3f}, MAE={metrics['MAE']:.3f}, MAPE unavailable"
            for name, metrics in model_comparison.items()
        )
        + ". All candidates were fit on training observations only; the user-selected model is not automatically replaced based on AIC/BIC."
        if model_comparison
        else "No chronological holdout comparison was available; model accuracy cannot be inferred from in-sample fit."
    )
    academic_interpretations = {
        "level": (
            f"Original-level assessment using the {deterministic_specification} deterministic specification: "
            f"{test_evidence} {stationarity_interpretations['level']}"
        ),
        "first_difference": (
            f"First-differenced series assessment using the {difference_deterministic_specification} deterministic specification: "
            f"{first_difference_evidence} {stationarity_interpretations['first_difference']}"
        ),
        "forecast_model": (
            f"The final {model_specification} model was estimated using all {len(series)} available observations "
            f"after holdout evaluation. {interval_method}: {interval_assumptions}"
        ),
        "residual_diagnostics": (
            f"Final-model convergence status: {convergence_status}. "
            + (
                "Warnings: " + " ".join(diagnostic_warnings)
                if diagnostic_warnings
                else "No configured Ljung-Box, Jarque-Bera, ARCH LM, or convergence warning was triggered."
            )
        ),
        "forecast_accuracy": forecast_accuracy_interpretation,
    }
    academic_interpretation = (
        f"For {value_column}, the analysis covers {len(series)} {validation['frequency_label'].lower()} "
        f"observations from {series.index.min().date()} to {series.index.max().date()}. "
        f"The selected deterministic specification assesses {scope} stationarity. "
        f"{academic_interpretations['level']} "
        f"The fitted linear trend is {direction} at {slope:.3f} observation units per period. "
        f"{academic_interpretations['first_difference']} "
        f"{academic_interpretations['forecast_model']} "
        f"{academic_interpretations['residual_diagnostics']} "
        f"{academic_interpretations['forecast_accuracy']}"
    )

    return {
        "date_column": date_column,
        "value_column": value_column,
        "rows": int(len(series)),
        "start_date": str(series.index.min().date()),
        "end_date": str(series.index.max().date()),
        "frequency": validation["frequency"],
        "frequency_label": validation["frequency_label"],
        "validation": validation,
        "descriptive_statistics": description,
        "trend_slope": float(slope),
        "trend_intercept": float(intercept),
        "trend": trend,
        "trend_values": [float(value) for value in trend.to_numpy()],
        "stationarity_tests": stationarity,
        "stationarity_assessment": stationarity_assessment,
        "stationarity_interpretations": stationarity_interpretations,
        "stationarity_scope": scope,
        "deterministic_specification": deterministic_specification,
        "difference_deterministic_specification": difference_deterministic_specification,
        "significance_level": float(significance_level),
        "rolling_window": int(rolling_window),
        "include_second_difference": bool(include_second_difference),
        "time_series_plot": {
            "periods": [str(value) for value in series.index],
            "values": [float(value) for value in series.to_numpy()],
            "rolling_mean": [_finite_or_none(value) for value in rolling_mean],
            "rolling_standard_deviation": [
                _finite_or_none(value) for value in rolling_standard_deviation
            ],
            "first_difference": [
                _finite_or_none(value) for value in series.diff()
            ],
            "second_difference": [
                _finite_or_none(value) for value in series.diff().diff()
            ]
            if include_second_difference
            else [],
        },
        "seasonal_period": int(period),
        "decomposition": decomposition,
        "decomposition_plot": decomposition_plot,
        "forecast_horizon": horizon,
        "model_name": model_name,
        "model_specification": model_specification,
        "deterministic_specification": deterministic_specification,
        "aic": _finite_or_none(fitted.aic) if hasattr(fitted, "aic") else None,
        "bic": _finite_or_none(fitted.bic) if hasattr(fitted, "bic") else None,
        "forecast_values": [float(value) for value in future],
        "forecast_lower": [float(value) for value in lower],
        "forecast_upper": [float(value) for value in upper],
        "forecast_intervals": forecast_intervals,
        "forecast_index": [str(value) for value in future.index],
        "fitted_values": [
            float(value) if np.isfinite(value) else None
            for value in np.asarray(getattr(fitted, "fittedvalues", []), dtype=float)
        ],
        "fitted_index": [
            str(value)
            for value in getattr(
                getattr(fitted, "fittedvalues", None), "index", pd.Index([])
            )
        ],
        "prediction_interval": {
            "method": interval_method,
            "confidence_level": 1 - significance_level,
            "assumptions": interval_assumptions,
        },
        "evaluation": evaluation,
        "model_comparison": model_comparison,
        "holdout": holdout,
        "model_evaluation_design": {
            "training_observations": (
                len(series) - len(holdout["periods"])
                if holdout["periods"]
                else 0
            ),
            "holdout_observations": len(holdout["periods"]),
            "training_end": (
                str(series.index[-len(holdout["periods"]) - 1].date())
                if holdout["periods"]
                else None
            ),
            "holdout_start": holdout["periods"][0] if holdout["periods"] else None,
            "final_estimation_observations": len(series) if fitted is not None else 0,
            "final_model_refit_on_full_series": fitted is not None,
            "evaluation_enabled": bool(model_comparison),
            "validation_strategy": validation_strategy,
            "training_fraction": (
                float(1 - len(holdout["periods"]) / len(series))
                if holdout["periods"]
                else None
            ),
        },
        "diagnostics": diagnostics,
        "diagnostic_warnings": diagnostic_warnings,
        "convergence_status": convergence_status,
        "residual_plot": residual_plot,
        "residual_acf": residual_acf,
        "correlogram": correlogram,
        "seasonal_components": seasonal_components,
        "academic_interpretation": academic_interpretation,
        "academic_interpretations": academic_interpretations,
        "summary": "\n".join(summary_lines),
    }


def inspect_time_series_dataset(
    dataframe: pd.DataFrame,
    date_column: str | None = None,
) -> dict[str, Any]:
    """Describe candidate temporal and variable columns without changing the data."""
    if not isinstance(dataframe, pd.DataFrame):
        raise TypeError("A pandas DataFrame is required for time-series inspection.")
    if dataframe.empty or len(dataframe.columns) < 2:
        raise ValueError("Import a non-empty table with a time column and at least one variable.")

    detection = detect_time_series(dataframe)
    selected_date = date_column or detection["date_column"]
    if selected_date not in dataframe.columns:
        raise ValueError("Select an existing date/time column before inspecting variable roles.")

    dates = parse_time_values(dataframe[selected_date])
    column_details = {}
    for column in dataframe.columns:
        values = dataframe[column]
        numeric = pd.to_numeric(values, errors="coerce")
        numeric_ratio = float(numeric.notna().mean()) if len(values) else 0.0
        parsed_dates = parse_time_values(values)
        date_ratio = float(parsed_dates.notna().mean()) if len(values) else 0.0
        if column == selected_date or date_ratio >= 0.7:
            variable_type = "date/time"
        elif pd.api.types.is_numeric_dtype(values) or numeric_ratio >= 0.8:
            variable_type = "numeric"
        else:
            variable_type = "categorical"
        finite_numeric = numeric.where(np.isfinite(numeric), np.nan)
        variable_dates = pd.DatetimeIndex(
            dates.loc[finite_numeric.notna()].dropna().sort_values().unique()
        ) if column != selected_date else pd.DatetimeIndex([])
        observed_frequency = (
            infer_time_frequency(variable_dates) if len(variable_dates) >= 3 else None
        )
        column_details[str(column)] = {
            "type": variable_type,
            "missing_count": int(values.isna().sum()),
            "numeric_parse_ratio": numeric_ratio,
            "date_parse_ratio": date_ratio,
            "unique_count": int(values.nunique(dropna=True)),
            "constant": bool(values.nunique(dropna=True) <= 1),
            "finite_numeric_count": int(finite_numeric.notna().sum()),
            "observed_frequency": observed_frequency,
        }

    valid_dates = dates.dropna()
    duplicate_count = int(valid_dates.duplicated().sum())
    frequency = (
        infer_time_frequency(pd.DatetimeIndex(valid_dates.sort_values().unique()))
        if len(valid_dates) >= 2
        else None
    )
    expected_periods = (
        pd.date_range(valid_dates.min(), valid_dates.max(), freq=frequency)
        if frequency and len(valid_dates)
        else pd.DatetimeIndex([])
    )
    missing_periods = (
        int(len(expected_periods.difference(pd.DatetimeIndex(valid_dates.unique()))))
        if len(expected_periods)
        else None
    )
    issues = []
    if dates.isna().any():
        issues.append(f"{int(dates.isna().sum())} date/time value(s) are invalid or missing.")
    if duplicate_count:
        issues.append(f"{duplicate_count} duplicate timestamps require an explicit resolution.")
    if len(valid_dates) >= 3 and frequency is None:
        issues.append("Time intervals are irregular or could not be inferred.")
    if missing_periods:
        issues.append(f"{missing_periods} expected timestamps are absent; no values were filled.")
    for column, details in column_details.items():
        if column != str(selected_date):
            if details["missing_count"]:
                issues.append(
                    f"{column} has {details['missing_count']} missing value(s); choose an explicit treatment."
                )
        if column != str(selected_date) and details["type"] == "numeric":
            if details["constant"]:
                issues.append(f"{column} is constant or has no observed values.")
            if (
                frequency
                and details["observed_frequency"]
                and details["observed_frequency"] != frequency
            ):
                issues.append(
                    f"{column} is observed at a different apparent frequency "
                    f"({details['observed_frequency']}) than the date column ({frequency}); "
                    "review explicit alignment or aggregation."
                )

    return {
        "date_column": str(selected_date),
        "columns": column_details,
        "numeric_columns": [
            column for column, details in column_details.items()
            if details["type"] == "numeric"
        ],
        "categorical_columns": [
            column for column, details in column_details.items()
            if details["type"] == "categorical"
        ],
        "frequency": frequency,
        "frequency_label": _FREQUENCY_LABELS.get(frequency[:1].upper(), "Other/irregular")
        if frequency
        else "Other/irregular",
        "valid_dates": int(valid_dates.size),
        "duplicate_timestamps": duplicate_count,
        "missing_periods": missing_periods,
        "issues": issues,
        "source_row_count": int(len(dataframe)),
    }


def preprocess_time_series_dataframe(
    dataframe: pd.DataFrame,
    date_column: str,
    operations: list[dict[str, Any]] | tuple[dict[str, Any], ...],
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """Apply only explicitly requested operations to a copy and record their effects."""
    if date_column not in dataframe.columns:
        raise ValueError(f"Date column '{date_column}' is not present in the dataset.")
    working = dataframe.copy(deep=True)
    original_date_values = working[date_column].copy()
    working[date_column] = parse_time_values(working[date_column])
    log: list[dict[str, Any]] = []
    if not pd.api.types.is_datetime64_any_dtype(original_date_values):
        log.append(
            {
                "action": "parse_dates",
                "column": date_column,
                "rows_before": int(len(working)),
                "rows_after": int(len(working)),
                "rows_changed": 0,
                "implication": "Parsed dates into a working-copy datetime index; source values remain unchanged.",
            }
        )
    for operation in operations:
        action = operation.get("action")
        column = operation.get("column")
        before = len(working)
        if action in {"drop_missing_rows", "interpolate", "forward_fill"}:
            if not column or column not in working.columns or column == date_column:
                raise ValueError(f"The {action} operation requires a selected non-date column.")
            values = pd.to_numeric(working[column], errors="coerce")
            values = values.where(np.isfinite(values), np.nan)
            if action == "drop_missing_rows":
                working = working.loc[values.notna()].copy()
                implication = "Rows missing this selected variable are excluded from the working copy."
            elif action == "forward_fill":
                working[column] = values.ffill()
                implication = "Uses the last observed value for later missing entries; may understate uncertainty."
            else:
                working[column] = pd.Series(
                    values.to_numpy(dtype=float), index=working.index
                )
                working = working.sort_values(date_column, kind="stable")
                working[column] = working.set_index(date_column)[column].interpolate(
                    method="time", limit_area="inside"
                ).to_numpy()
                implication = "Interpolates only between observed time points; end gaps remain unresolved."
        elif action in {"aggregate_mean", "keep_first", "keep_last", "remove_duplicates"}:
            if working[date_column].duplicated().sum() == 0:
                raise ValueError(f"No duplicate timestamps are present for {action}.")
            if action == "aggregate_mean":
                numeric_columns = [
                    name for name in working.columns
                    if name != date_column and pd.api.types.is_numeric_dtype(
                        pd.to_numeric(working[name], errors="coerce")
                    )
                ]
                non_numeric = [
                    name for name in working.columns
                    if name != date_column and name not in numeric_columns
                ]
                if non_numeric:
                    raise ValueError(
                        "Mean aggregation is not defined for categorical columns: "
                        + ", ".join(map(str, non_numeric))
                    )
                if not numeric_columns:
                    raise ValueError("Mean aggregation requires at least one numeric variable.")
                working = working.groupby(date_column, as_index=False, sort=True)[
                    numeric_columns
                ].mean()
                implication = "Aggregates duplicate observations by arithmetic mean; within-period variation is lost."
            else:
                keep = "first" if action in {"keep_first", "remove_duplicates"} else "last"
                working = working.drop_duplicates(subset=[date_column], keep=keep).copy()
                implication = f"Retains the {keep} row per timestamp and excludes other duplicate observations."
        elif action == "resample":
            frequency = str(operation.get("frequency", "")).strip()
            aggregation = str(operation.get("aggregation", "mean")).strip().lower()
            if not frequency or aggregation not in {"mean", "sum", "first", "last"}:
                raise ValueError("Resampling requires a frequency and mean, sum, first, or last aggregation.")
            numeric_columns = [
                name for name in working.columns
                if name != date_column and pd.api.types.is_numeric_dtype(
                    pd.to_numeric(working[name], errors="coerce")
                )
            ]
            if len(numeric_columns) != len(working.columns) - 1:
                raise ValueError("Resampling categorical columns requires an explicit conversion first.")
            working[numeric_columns] = working[numeric_columns].apply(
                pd.to_numeric, errors="coerce"
            )
            working = (
                working.set_index(date_column)[numeric_columns]
                .resample(frequency)
                .agg(aggregation)
                .reset_index()
            )
            implication = (
                f"Resamples to {frequency} using {aggregation}; aggregation can hide within-period dynamics "
                "and newly empty periods remain missing."
            )
        else:
            raise ValueError(f"Unsupported explicit preprocessing operation: {action}")
        log.append(
            {
                **operation,
                "rows_before": int(before),
                "rows_after": int(len(working)),
                "rows_changed": int(before - len(working)),
                "implication": implication,
            }
        )
    return working, log


def recommend_time_series_methods(
    dataframe: pd.DataFrame,
    date_column: str,
    dependent_variables: list[str] | tuple[str, ...] | None = None,
    exogenous_variables: list[str] | tuple[str, ...] | None = None,
    endogenous_variables: list[str] | tuple[str, ...] | None = None,
    significance_level: float = 0.05,
) -> dict[str, Any]:
    """Return methods grouped by data-based eligibility and explanatory reasons."""
    if not 0 < significance_level < 1:
        raise ValueError("Significance level must be between zero and one.")
    inspection = inspect_time_series_dataset(dataframe, date_column)
    numeric = inspection["numeric_columns"]
    dependent = list(dependent_variables or [])
    exogenous = list(exogenous_variables or [])
    endogenous = list(endogenous_variables or [])
    if not dependent and not endogenous and numeric:
        dependent = [numeric[0]]
    selected = dependent + endogenous + exogenous
    if len(selected) != len(set(selected)):
        raise ValueError("A variable cannot be assigned to multiple analysis roles.")
    unknown = [column for column in selected if column not in dataframe.columns]
    if unknown:
        raise ValueError(f"Selected variable(s) are not present: {', '.join(unknown)}.")
    unsuitable_types = [
        column for column in selected
        if inspection["columns"][column]["type"] != "numeric"
    ]
    if unsuitable_types:
        raise ValueError(
            "Selected model variables must be numeric: " + ", ".join(unsuitable_types)
        )

    stationarity_profiles = {}
    dates = parse_time_values(dataframe[date_column])
    for column in dict.fromkeys(dependent + endogenous + exogenous):
        complete = pd.DataFrame(
            {
                "date": dates,
                "value": pd.to_numeric(dataframe[column], errors="coerce"),
            }
        ).dropna()
        complete = complete.sort_values("date").drop_duplicates("date")
        series = complete["value"].astype(float)
        profile: dict[str, Any] = {"observations": int(len(series))}
        if len(series) >= 12 and series.nunique() > 1:
            for label, candidate in (
                ("level", series),
                ("first_difference", series.diff().dropna()),
            ):
                if len(candidate) < 8 or candidate.nunique() < 2:
                    profile[label] = {"ADF_p_value": None, "KPSS_p_value": None}
                    continue
                try:
                    adf_p = float(adfuller(candidate, regression="c", autolag="AIC")[1])
                    kpss_p = float(kpss(candidate, regression="c", nlags="auto")[1])
                    profile[label] = {
                        "ADF_p_value": adf_p,
                        "KPSS_p_value": kpss_p,
                        "stationary_evidence": bool(
                            adf_p < significance_level and kpss_p >= significance_level
                        ),
                        "unit_root_evidence": bool(
                            adf_p >= significance_level and kpss_p < significance_level
                        ),
                    }
                except (ValueError, np.linalg.LinAlgError):
                    profile[label] = {"ADF_p_value": None, "KPSS_p_value": None}
        else:
            profile["limitation"] = (
                "Fewer than 12 usable varying observations; integration order cannot be "
                "screened reliably by the recommendation engine."
            )
        stationarity_profiles[column] = profile

    recommended: list[dict[str, str]] = []
    conditional: list[dict[str, str]] = []
    unsuitable: list[dict[str, str]] = []
    regular = bool(inspection["frequency"]) and not inspection["duplicate_timestamps"]
    has_temporal_gaps = bool(inspection["missing_periods"])
    has_selected_missing = any(
        inspection["columns"][column]["missing_count"] > 0
        for column in selected
    )
    row_count = inspection["valid_dates"]
    one_series = len(dependent) == 1 and not exogenous and not endogenous
    has_exog = len(dependent) == 1 and bool(exogenous)
    multiple_endogenous = len(endogenous) >= 2
    selected_constants = [
        column
        for column in set(dependent + endogenous + exogenous)
        if inspection["columns"][column]["constant"]
    ]

    def add(target: list[dict[str, str]], method: str, reason: str) -> None:
        target.append({"method": method, "reason": reason})

    if selected_constants:
        add(
            unsuitable,
            "Models requiring varying selected variables",
            "The following selected variables are constant or empty: "
            + ", ".join(sorted(selected_constants))
            + ". Remove them or verify the source data.",
        )
    elif one_series:
        if regular and not has_temporal_gaps and not has_selected_missing and row_count >= 8:
            add(recommended, "ARIMA", "One numeric dependent series has a regular, ordered time index.")
            if inspection["frequency"].startswith(("M", "ME", "Q", "W")) and row_count >= 24:
                add(recommended, "SARIMA", "The observed frequency supports a seasonal model; verify at least two cycles and seasonal structure.")
            else:
                add(conditional, "SARIMA", "A regular seasonal period and sufficient repeated cycles have not been established.")
            for method in ("ADF", "KPSS", "Phillips-Perron", "ACF/PACF", "Trend analysis", "Forecasting"):
                add(recommended, method, "These univariate diagnostics/analyses apply to the selected numeric series.")
            for method in ("Naive", "Historical mean", "Linear trend", "Exponential smoothing"):
                add(
                    recommended,
                    method,
                    "This benchmark/trend smoother can be evaluated on the same chronological holdout without requiring an extra predictor.",
                )
            if inspection["frequency"].startswith(("M", "ME", "Q", "W")) and row_count >= 24:
                add(recommended, "Seasonal decomposition", "The date frequency and row count permit checking multiple seasonal cycles.")
            else:
                add(conditional, "Seasonal decomposition", "A known seasonal period and at least two complete cycles are needed.")
        else:
            add(conditional, "Univariate ARIMA and diagnostics", "Resolve irregularity, duplicates, gaps, or small-sample limitations before fitting.")
    elif has_exog:
        if regular and not has_temporal_gaps and not has_selected_missing and row_count >= 12:
            predictors_stationary = all(
                stationarity_profiles.get(column, {})
                .get("level", {})
                .get("stationary_evidence")
                is True
                for column in exogenous
            )
            all_variables_stationary = predictors_stationary and (
                stationarity_profiles.get(dependent[0], {})
                .get("level", {})
                .get("stationary_evidence")
                is True
            )
            if predictors_stationary:
                add(
                    recommended,
                    "ARIMAX",
                    "The explicitly selected exogenous predictors have level-stationarity evidence; the dependent series can be modeled with an appropriate ARIMA integration order.",
                )
                if inspection["frequency"].startswith(("M", "ME", "Q", "W")) and row_count >= 24:
                    add(recommended, "SARIMAX", "The predictors are level-stationary and the regular frequency and sample permit evaluating a seasonal exogenous model.")
                else:
                    add(conditional, "SARIMAX", "Seasonal evidence and adequate repeated cycles are not established.")
            else:
                add(
                    conditional,
                    "ARIMAX/SARIMAX",
                    "At least one external predictor lacks level-stationarity evidence. Transform the predictor explicitly or establish a defensible cointegrating design before using it; exogenous inputs are not automatically differenced.",
                )
            if all_variables_stationary:
                add(recommended, "Regression-based forecasting", "The dependent series and explicitly selected predictors have level-stationarity evidence for chronological regression forecasting.")
            else:
                add(conditional, "Regression-based forecasting", "Regression in levels requires level-stationary dependent and predictor series; transform variables explicitly or use a justified cointegrating design.")
        else:
            add(conditional, "ARIMAX/SARIMAX and regression", "Resolve temporal gaps, irregular intervals, duplicate dates, or limited sample size.")
    elif multiple_endogenous:
        enough_rows = row_count >= max(30, 5 * len(endogenous))
        if regular and not has_temporal_gaps and not has_selected_missing and enough_rows:
            profiles = [stationarity_profiles.get(column, {}) for column in endogenous]
            all_stationary = all(
                item.get("level", {}).get("stationary_evidence") is True
                for item in profiles
            )
            all_i1 = all(
                item.get("level", {}).get("unit_root_evidence") is True
                and item.get("first_difference", {}).get("stationary_evidence") is True
                for item in profiles
            )
            if all_stationary:
                add(recommended, "VAR", "Every selected endogenous series has ADF/KPSS evidence consistent with level stationarity; still verify lag adequacy and stability.")
                add(recommended, "Granger causality", "A level-stationary multivariate system is available; interpret tests conditional on lag and residual adequacy.")
            else:
                add(conditional, "VAR", "At least one endogenous series is not clearly stationary in levels. Use a statistically justified stationary transformation or assess a cointegrated system before fitting levels VAR.")
                add(conditional, "Granger causality", "Establish integration orders and the correct levels-versus-differences specification before inference.")
            add(conditional, "Johansen cointegration", "Use when the selected variables have compatible integration orders (typically I(1)); choose deterministic terms and lag order deliberately.")
            add(
                conditional,
                "VECM",
                "Consider only when selected series are consistently I(1) and Johansen rank selection supports a non-zero, non-saturated rank."
                if not all_i1
                else "Selected series have level unit-root and first-difference stationarity evidence; run Johansen rank selection before estimating VECM.",
            )
            add(conditional, "Impulse responses and FEVD", "Available after a stable, adequately specified model; orthogonal responses depend on variable ordering.")
        else:
            add(conditional, "VAR/VECM and multivariate diagnostics", "Resolve temporal alignment, gaps, duplicates, or insufficient observations.")
    elif len(numeric) > 1:
        add(conditional, "Multivariate or exogenous models", "Assign numeric columns explicitly as endogenous outcomes or external predictors.")

    if len(dependent) == 1 and len(endogenous) > 1:
        add(unsuitable, "VAR/VECM on all selected columns", "The same variable cannot simultaneously be treated as a single dependent series and part of a separate endogenous system.")
    if not regular:
        add(unsuitable, "Regular-grid forecasting", "A unique regular frequency is required; approve a documented alignment before using these models.")
    if row_count < 8:
        add(unsuitable, "Information-intensive time-series models", "The available sample is too small for stable estimation and chronological validation.")

    return {
        "inspection": inspection,
        "roles": {
            "dependent_variables": dependent,
            "endogenous_variables": endogenous,
            "exogenous_variables": exogenous,
        },
        "stationarity_profiles": stationarity_profiles,
        "recommended": recommended,
        "conditional": conditional,
        "unsuitable": unsuitable,
    }


def analyze_exogenous_time_series(
    dataframe: pd.DataFrame,
    date_column: str,
    dependent_variable: str,
    exogenous_variables: list[str] | tuple[str, ...],
    forecast_horizon: int = 6,
    model_name: str = "ARIMAX",
    order: tuple[int, int, int] = (1, 1, 1),
    seasonal_order: tuple[int, int, int] = (1, 0, 0),
    seasonal_period: int | None = None,
    future_exog: pd.DataFrame | None = None,
    scenarios: dict[str, pd.DataFrame] | None = None,
    auto_forecast_exog: bool = False,
    test_size: int | None = None,
    significance_level: float = 0.05,
) -> dict[str, Any]:
    """Fit an exogenous forecasting model without imputing or fabricating inputs."""
    from statsmodels.tsa.statespace.sarimax import SARIMAX

    exogenous = list(exogenous_variables)
    if model_name not in {"ARIMAX", "SARIMAX", "Regression"}:
        raise ValueError("Choose ARIMAX, SARIMAX, or Regression for exogenous analysis.")
    if not exogenous or dependent_variable in exogenous:
        raise ValueError("Select one dependent variable and at least one distinct predictor.")
    if len(exogenous) != len(set(exogenous)):
        raise ValueError("Select each exogenous variable only once.")
    if any(column not in dataframe.columns for column in [date_column, dependent_variable, *exogenous]):
        raise ValueError("The selected time, dependent, or predictor column is not present.")
    if forecast_horizon < 1 or not 0 < significance_level < 1:
        raise ValueError("Forecast horizon and significance level are outside their valid ranges.")
    if len(order) != 3 or len(seasonal_order) != 3 or any(
        int(value) < 0 for value in (*order, *seasonal_order)
    ):
        raise ValueError("ARIMA order parameters must contain three non-negative integers.")

    dates = parse_time_values(dataframe[date_column])
    numeric = dataframe[[dependent_variable, *exogenous]].apply(
        pd.to_numeric, errors="coerce"
    )
    numeric = numeric.where(np.isfinite(numeric), np.nan)
    invalid_rows = dates.isna() | numeric.isna().any(axis=1)
    if invalid_rows.any():
        raise ValueError(
            f"{int(invalid_rows.sum())} row(s) have invalid dates or missing/non-numeric selected values. "
            "Review and approve a preprocessing operation before fitting."
        )
    frame = numeric.copy()
    frame.index = pd.DatetimeIndex(dates)
    if frame.index.has_duplicates:
        raise ValueError("Duplicate timestamps must be explicitly resolved before exogenous analysis.")
    frame = frame.sort_index()
    frequency = infer_time_frequency(frame.index)
    regular_frequency = pd.infer_freq(frame.index) if len(frame) >= 3 else None
    if not frequency or not regular_frequency:
        raise ValueError(
            "Exogenous forecasting requires a complete regular time index. "
            "Review an explicit alignment or resampling operation first."
        )
    series = frame[dependent_variable].astype(float)
    predictors = frame[exogenous].astype(float)
    horizon = int(forecast_horizon)
    period = int(seasonal_period or (
        12 if frequency.startswith(("M", "ME"))
        else 4 if frequency.startswith("Q")
        else 1
    ))
    if model_name == "SARIMAX" and (
        period <= 1 or len(frame) < period * 2
    ):
        raise ValueError(
            "SARIMAX requires a regular seasonal frequency and at least two observed seasonal cycles."
        )
    if len(frame) < max(12, 3 * len(exogenous) + 5):
        raise ValueError(
            "The sample is too small for the selected number of predictors and chronological validation."
        )
    stationarity_profiles = {}
    for column in [dependent_variable, *exogenous]:
        level = frame[column].astype(float)
        first_difference = level.diff().dropna()
        try:
            level_adf = float(adfuller(level, regression="c", autolag="AIC")[1])
            level_kpss = float(kpss(level, regression="c", nlags="auto")[1])
            difference_adf = float(
                adfuller(first_difference, regression="c", autolag="AIC")[1]
            )
            difference_kpss = float(
                kpss(first_difference, regression="c", nlags="auto")[1]
            )
            stationary = (
                level_adf < significance_level and level_kpss >= significance_level
            )
            difference_stationary = (
                difference_adf < significance_level
                and difference_kpss >= significance_level
            )
        except (ValueError, np.linalg.LinAlgError):
            level_adf = None
            level_kpss = None
            difference_adf = None
            difference_kpss = None
            stationary = False
            difference_stationary = False
        stationarity_profiles[column] = {
            "ADF_p_value": level_adf,
            "KPSS_p_value": level_kpss,
            "level_stationary_evidence": stationary,
            "first_difference_ADF_p_value": difference_adf,
            "first_difference_KPSS_p_value": difference_kpss,
            "first_difference_stationary_evidence": difference_stationary,
        }
    if model_name == "Regression" and not all(
        values["level_stationary_evidence"]
        for values in stationarity_profiles.values()
    ):
        raise ValueError(
            "Regression-based time-series forecasting requires level-stationary selected variables "
            "or a separately justified cointegrating design. Difference variables or select ARIMAX/SARIMAX."
        )
    if series.nunique() < 2:
        raise ValueError("The dependent series is constant and cannot support this exogenous model.")
    constant_predictors = [
        column for column in exogenous if predictors[column].nunique() < 2
    ]
    if constant_predictors:
        raise ValueError(
            "Constant predictor(s) cannot identify an exogenous effect: "
            + ", ".join(constant_predictors)
            + "."
        )
    nonstationary_predictors = [
        column
        for column in exogenous
        if not stationarity_profiles[column]["level_stationary_evidence"]
    ]
    if model_name in {"ARIMAX", "SARIMAX"} and nonstationary_predictors:
        raise ValueError(
            "ARIMAX/SARIMAX require level-stationary exogenous predictors in this workflow. "
            "Explicitly transform nonstationary predictors or establish a defensible "
            "cointegrating design before fitting: "
            + ", ".join(nonstationary_predictors)
            + "."
        )

    evaluation_enabled = test_size != 0
    requested_test_size = (
        max(1, int(test_size))
        if test_size is not None and evaluation_enabled
        else max(1, int(math.ceil(len(frame) * 0.2)))
        if evaluation_enabled
        else 0
    )
    actual_test_size = (
        min(requested_test_size, len(frame) - 8) if evaluation_enabled else 0
    )
    if evaluation_enabled and actual_test_size < 1:
        raise ValueError("At least eight training observations are required for exogenous validation.")
    if actual_test_size:
        train_y, test_y = series.iloc[:-actual_test_size], series.iloc[-actual_test_size:]
        train_x, test_x = predictors.iloc[:-actual_test_size], predictors.iloc[-actual_test_size:]
    else:
        train_y, test_y = series, series.iloc[:0]
        train_x, test_x = predictors, predictors.iloc[:0]

    def fit_and_predict(y, x, future_x, future_dates):
        if model_name == "Regression":
            positions = np.arange(len(y), dtype=float)
            future_positions = np.arange(len(y), len(y) + len(future_x), dtype=float)
            design = pd.DataFrame(x.to_numpy(), index=y.index, columns=exogenous)
            design.insert(0, "time_trend", positions)
            design = add_constant(design, has_constant="add")
            future_design = pd.DataFrame(
                future_x.to_numpy(), index=future_dates, columns=exogenous
            )
            future_design.insert(0, "time_trend", future_positions)
            future_design = add_constant(future_design, has_constant="add")
            if np.linalg.matrix_rank(design.to_numpy(dtype=float)) < design.shape[1]:
                raise ValueError("Regression predictors are constant or collinear; revise the predictor set.")
            fitted_model = OLS(y.to_numpy(dtype=float), design).fit()
            if future_x.empty:
                empty = pd.Series(dtype=float, index=future_dates)
                return fitted_model, empty, empty, empty
            interval = fitted_model.get_prediction(future_design).summary_frame(
                alpha=significance_level
            )
            return (
                fitted_model,
                pd.Series(interval["mean"].to_numpy(dtype=float), index=future_dates),
                pd.Series(interval["obs_ci_lower"].to_numpy(dtype=float), index=future_dates),
                pd.Series(interval["obs_ci_upper"].to_numpy(dtype=float), index=future_dates),
            )
        seasonal = (
            (*seasonal_order, period)
            if model_name == "SARIMAX"
            else (0, 0, 0, 0)
        )
        fitted_model = SARIMAX(
            y,
            exog=x,
            order=order,
            seasonal_order=seasonal,
            enforce_stationarity=False,
            enforce_invertibility=False,
        ).fit(disp=False)
        if future_x.empty:
            empty = pd.Series(dtype=float, index=future_dates)
            return fitted_model, empty, empty, empty
        forecast = fitted_model.get_forecast(steps=len(future_x), exog=future_x)
        interval = forecast.conf_int(alpha=significance_level)
        return (
            fitted_model,
            pd.Series(np.asarray(forecast.predicted_mean, dtype=float), index=future_dates),
            pd.Series(interval.iloc[:, 0].to_numpy(dtype=float), index=future_dates),
            pd.Series(interval.iloc[:, 1].to_numpy(dtype=float), index=future_dates),
        )

    if evaluation_enabled:
        holdout_fit, holdout_predictions, _, _ = fit_and_predict(
            train_y, train_x, test_x, test_y.index
        )
        holdout_metrics = _forecast_metrics(
            test_y.to_numpy(dtype=float), holdout_predictions.to_numpy(dtype=float)
        )
    else:
        holdout_predictions = pd.Series(dtype=float, index=test_y.index)
        holdout_metrics = {}
    fitted, _, _, _ = fit_and_predict(
        series, predictors, predictors.iloc[:0], pd.DatetimeIndex([])
    )
    future_index = pd.date_range(
        frame.index[-1], periods=horizon + 1, freq=regular_frequency
    )[1:]

    def normalize_future_inputs(
        values: pd.DataFrame,
        label: str,
    ) -> pd.DataFrame:
        prepared = values.copy()
        if date_column in prepared.columns:
            parsed_dates = parse_time_values(prepared.pop(date_column))
            if parsed_dates.isna().any():
                raise ValueError(f"{label} contains invalid future dates.")
            prepared.index = pd.DatetimeIndex(parsed_dates)
        elif isinstance(prepared.index, pd.DatetimeIndex):
            prepared.index = pd.DatetimeIndex(parse_time_values(pd.Series(prepared.index)))
        else:
            raise ValueError(f"{label} must include a date column or a DatetimeIndex.")
        if prepared.index.has_duplicates or not prepared.index.equals(future_index):
            raise ValueError(
                f"{label} must contain exactly the {horizon} forecast dates in chronological order."
            )
        if set(prepared.columns) != set(exogenous):
            raise ValueError(f"{label} must contain exactly these predictors: {', '.join(exogenous)}.")
        prepared = prepared[exogenous].apply(pd.to_numeric, errors="coerce")
        prepared = prepared.where(np.isfinite(prepared), np.nan)
        if prepared.isna().any().any():
            raise ValueError(f"{label} contains missing or non-numeric predictor values.")
        return prepared.astype(float)

    normalized_scenarios: dict[str, pd.DataFrame] = {}
    if scenarios:
        for scenario_name, values in scenarios.items():
            if not scenario_name.strip():
                raise ValueError("Scenario names cannot be empty.")
            normalized_scenarios[scenario_name.strip()] = normalize_future_inputs(
                values, f"Scenario '{scenario_name}'"
            )
    normalized_future = (
        normalize_future_inputs(future_exog, "Future predictor input")
        if future_exog is not None
        else None
    )
    automatic_predictors_used = False
    if auto_forecast_exog and normalized_future is None:
        if len(frame) < 12:
            raise ValueError(
                "Automatic predictor forecasting requires at least 12 observations per predictor; "
                "supply future predictor values manually instead."
            )
        predicted_columns = {}
        for column in exogenous:
            predictor_period = period if len(frame) >= period * 2 else None
            _, prediction, _, _ = _forecast_model(
                predictors[column],
                horizon,
                "Holt-Winters" if predictor_period else "Holt",
                predictor_period,
            )
            predicted_columns[column] = prediction.to_numpy(dtype=float)
        normalized_future = pd.DataFrame(predicted_columns, index=future_index)
        automatic_predictors_used = True
    if normalized_future is not None:
        normalized_scenarios.setdefault("Baseline", normalized_future)
    if normalized_future is None and not normalized_scenarios:
        forecast_values: list[float] = []
        forecast_lower: list[float] = []
        forecast_upper: list[float] = []
        forecast_dates: list[str] = []
        forecast_limitation = (
            "Future forecasts were not produced because future predictor values were not supplied. "
            "Provide date-aligned predictors or choose suitable automatic predictor forecasting."
        )
    else:
        scenario_results = {}
        for scenario_name, scenario_x in normalized_scenarios.items():
            _, scenario_mean, scenario_lower, scenario_upper = fit_and_predict(
                series, predictors, scenario_x, future_index
            )
            scenario_results[scenario_name] = {
                "forecast_values": scenario_mean.tolist(),
                "forecast_lower": scenario_lower.tolist(),
                "forecast_upper": scenario_upper.tolist(),
                "forecast_index": [str(value) for value in future_index],
            }
        selected_scenario = (
            "Baseline"
            if automatic_predictors_used and "Baseline" in scenario_results
            else next(iter(scenario_results))
        )
        selected = scenario_results[selected_scenario]
        forecast_values = selected["forecast_values"]
        forecast_lower = selected["forecast_lower"]
        forecast_upper = selected["forecast_upper"]
        forecast_dates = selected["forecast_index"]
        forecast_limitation = None

    residuals = np.asarray(getattr(fitted, "resid", []), dtype=float)
    residuals = residuals[np.isfinite(residuals)]
    diagnostics = {}
    if len(residuals) > 3:
        lag = min(10, max(1, len(residuals) // 5))
        diagnostics["Ljung-Box p-value"] = _finite_or_none(
            acorr_ljungbox(residuals, lags=[lag], return_df=True)["lb_pvalue"].iloc[0]
        )
        jb = jarque_bera(residuals)
        diagnostics["Jarque-Bera p-value"] = _finite_or_none(jb.pvalue)
        diagnostics["ARCH LM p-value"] = _finite_or_none(het_arch(residuals, nlags=lag)[1])
    parameters = getattr(fitted, "params", pd.Series(dtype=float))
    p_values = getattr(fitted, "pvalues", pd.Series(dtype=float))
    parameter_inference = {
        str(name): {
            "estimate": _finite_or_none(value),
            "p_value": _finite_or_none(p_values.get(name)),
        }
        for name, value in parameters.items()
    }
    return {
        "analysis_type": "exogenous",
        "date_column": date_column,
        "dependent_variable": dependent_variable,
        "exogenous_variables": exogenous,
        "model_name": model_name,
        "model_specification": (
            f"{model_name}({','.join(map(str, order))})"
            + (
                f"({','.join(map(str, seasonal_order))},{period})"
                if model_name == "SARIMAX"
                else ""
            )
        ),
        "rows": int(len(frame)),
        "frequency": frequency,
        "forecast_horizon": horizon,
        "evaluation": holdout_metrics,
        "holdout": {
            "periods": [str(value) for value in test_y.index],
            "actual": test_y.tolist(),
            "predicted": holdout_predictions.tolist(),
        },
        "model_evaluation_design": {
            "training_observations": int(len(train_y)),
            "holdout_observations": int(len(test_y)),
            "training_end": str(train_y.index[-1]) if len(train_y) else None,
            "holdout_start": str(test_y.index[0]) if len(test_y) else None,
            "final_estimation_observations": int(len(series)),
        },
        "forecast_index": forecast_dates,
        "forecast_values": forecast_values,
        "forecast_lower": forecast_lower,
        "forecast_upper": forecast_upper,
        "forecast_limitation": forecast_limitation,
        "forecast_interval_assumption": (
            "Intervals are conditional on the supplied or independently extrapolated future "
            "predictor paths; predictor forecast uncertainty is not propagated."
        ),
        "scenario_forecasts": (
            scenario_results if normalized_future is not None or normalized_scenarios else {}
        ),
        "future_predictor_values": {
            scenario_name: {
                "periods": [str(value) for value in scenario.index],
                "values": scenario.to_dict(orient="list"),
            }
            for scenario_name, scenario in normalized_scenarios.items()
        },
        "future_predictor_source": (
            "estimated by independent time-series forecasts"
            if automatic_predictors_used
            else "researcher-supplied scenario values"
            if future_exog is not None or scenarios
            else None
        ),
        "parameter_inference": parameter_inference,
        "stationarity_profiles": stationarity_profiles,
        "statistical_warnings": [
            f"{column} is not clearly stationary in levels; check integration, differencing, "
            "and possible cointegration before interpreting exogenous effects."
            for column, profile in stationarity_profiles.items()
            if not profile["level_stationary_evidence"]
        ],
        "diagnostics": diagnostics,
        "aic": _finite_or_none(getattr(fitted, "aic", None)),
        "bic": _finite_or_none(getattr(fitted, "bic", None)),
        "convergence_status": (
            "Converged."
            if getattr(fitted, "mle_retvals", {}).get("converged", True)
            else "Did not converge."
        ),
    }


def analyze_multivariate_time_series(
    dataframe: pd.DataFrame,
    date_column: str,
    endogenous_variables: list[str] | tuple[str, ...],
    model_name: str = "VAR",
    forecast_horizon: int = 6,
    maxlags: int | None = None,
    deterministic: str = "c",
    significance_level: float = 0.05,
    test_size: int | None = None,
    cointegration_rank: int | None = None,
) -> dict[str, Any]:
    """Fit an eligibility-checked VAR or cointegrated VECM system."""
    variables = list(endogenous_variables)
    if model_name == "Johansen cointegration":
        return johansen_cointegration_test(
            dataframe,
            date_column,
            endogenous_variables,
            deterministic=deterministic,
            significance_level=significance_level,
            maxlags=maxlags,
        )
    if model_name not in {"VAR", "VECM"}:
        raise ValueError("Choose VAR, VECM, or Johansen cointegration for multivariate analysis.")
    if len(variables) < 2 or len(variables) != len(set(variables)):
        raise ValueError("Select at least two distinct endogenous variables.")
    if any(column not in dataframe.columns for column in [date_column, *variables]):
        raise ValueError("The selected time or endogenous variable is not present.")
    if forecast_horizon < 1 or not 0 < significance_level < 1:
        raise ValueError("Forecast horizon and significance level are outside their valid ranges.")
    if significance_level not in {0.01, 0.05, 0.1}:
        raise ValueError("Johansen rank selection supports 1%, 5%, or 10% significance levels.")
    if deterministic not in {"n", "c", "ct", "co", "ci", "lo", "li"}:
        raise ValueError("Unsupported deterministic specification for vector analysis.")

    dates = parse_time_values(dataframe[date_column])
    values = dataframe[variables].apply(pd.to_numeric, errors="coerce")
    values = values.where(np.isfinite(values), np.nan)
    if dates.isna().any() or values.isna().any().any():
        raise ValueError(
            "Selected variables contain missing or non-numeric observations. "
            "Review and approve preprocessing before vector analysis."
        )
    frame = values.copy()
    frame.index = pd.DatetimeIndex(dates)
    if frame.index.has_duplicates:
        raise ValueError("Duplicate timestamps must be explicitly resolved before vector analysis.")
    frame = frame.sort_index()
    frequency = infer_time_frequency(frame.index)
    inferred = pd.infer_freq(frame.index) if len(frame) >= 3 else None
    if not frequency or not inferred:
        raise ValueError("VAR/VECM requires a regular time index; explicitly align intervals first.")
    expected = pd.date_range(frame.index.min(), frame.index.max(), freq=frequency)
    if not expected.equals(frame.index):
        raise ValueError("VAR/VECM requires complete aligned observations with no missing periods.")
    if any(frame[column].nunique() < 2 for column in variables):
        raise ValueError("Every endogenous variable must vary; constant variables are unsuitable.")
    minimum_rows = max(30, 5 * len(variables) + 10)
    if len(frame) < minimum_rows:
        raise ValueError(
            f"{model_name} requires at least {minimum_rows} aligned observations for "
            f"{len(variables)} endogenous variables; found {len(frame)}."
        )
    stationarity_profiles = {}
    for column in variables:
        level = frame[column].astype(float)
        first_difference = level.diff().dropna()
        try:
            level_adf = float(adfuller(level, regression="c", autolag="AIC")[1])
            level_kpss = float(kpss(level, regression="c", nlags="auto")[1])
            difference_adf = float(
                adfuller(first_difference, regression="c", autolag="AIC")[1]
            )
            difference_kpss = float(
                kpss(first_difference, regression="c", nlags="auto")[1]
            )
        except (ValueError, np.linalg.LinAlgError) as error:
            raise ValueError(
                f"Stationarity/integration screening failed for {column}: {error}"
            ) from error
        stationary = level_adf < significance_level and level_kpss >= significance_level
        integrated_one = (
            level_adf >= significance_level
            and level_kpss < significance_level
            and difference_adf < significance_level
            and difference_kpss >= significance_level
        )
        stationarity_profiles[column] = {
            "level_ADF_p_value": level_adf,
            "level_KPSS_p_value": level_kpss,
            "first_difference_ADF_p_value": difference_adf,
            "first_difference_KPSS_p_value": difference_kpss,
            "level_stationary_evidence": stationary,
            "I1_evidence": integrated_one,
        }
    if model_name == "VAR" and not all(
        profile["level_stationary_evidence"]
        for profile in stationarity_profiles.values()
    ):
        raise ValueError(
            "A VAR in levels is not recommended because ADF/KPSS do not jointly support "
            "stationarity for every variable. Use an explicitly reviewed stationary transformation, "
            "or test for cointegration before considering VECM; no differencing was applied."
        )
    if model_name == "VECM" and not all(
        profile["I1_evidence"] for profile in stationarity_profiles.values()
    ):
        raise ValueError(
            "VECM requires compatible I(1) evidence: level ADF/KPSS unit-root evidence and "
            "stationary first differences for every selected variable. Review an appropriate "
            "stationary VAR alternative."
        )
    if maxlags is not None and (maxlags < 1 or maxlags >= len(frame) // 3):
        raise ValueError("Maximum lag must be positive and less than one third of the usable sample.")

    lag_limit = maxlags or min(12, max(1, len(frame) // 5))
    selected_order = VAR(frame).select_order(maxlags=lag_limit, trend="c")
    selected_lag = selected_order.selected_orders.get("aic")
    if selected_lag is None:
        selected_lag = 1
    selected_lag = max(1, int(selected_lag))
    johansen_det_order = {"n": -1, "c": 0, "ct": 1}.get(deterministic, 0)

    if model_name == "VAR":
        fitted = VAR(frame).fit(maxlags=selected_lag, trend="c")
        stability = bool(fitted.is_stable(verbose=False))
        cointegration = None
        granger = {}
        for caused in variables:
            causes = [column for column in variables if column != caused]
            try:
                test = fitted.test_causality(caused, causing=causes, kind="f")
                granger[caused] = {
                    "causes": causes,
                    "statistic": _finite_or_none(test.test_statistic),
                    "p_value": _finite_or_none(test.pvalue),
                    "conclusion": (
                        f"Reject no joint Granger causality at alpha={significance_level:g}."
                        if test.pvalue < significance_level
                        else "Fail to reject no joint Granger causality at the selected level."
                    ),
                }
            except (ValueError, np.linalg.LinAlgError) as error:
                granger[caused] = {"error": str(error)}
        irf = fitted.irf(min(10, max(1, len(frame) // 5)))
        irf_output = {
            "periods": list(range(len(irf.orth_irfs))),
            "variables": variables,
            "values": np.asarray(irf.orth_irfs, dtype=float).tolist(),
        }
        cointegration = None
        try:
            fevd_object = fitted.fevd(min(10, max(1, len(frame) // 5)))
            fevd_output = {
                "periods": list(range(1, fevd_object.decomp.shape[0] + 1)),
                "variables": variables,
                "values": np.asarray(fevd_object.decomp, dtype=float).tolist(),
            }
        except (ValueError, np.linalg.LinAlgError) as error:
            fevd_output = {"error": str(error)}
    else:
        rank_test = select_coint_rank(
            frame,
            det_order=johansen_det_order,
            k_ar_diff=max(1, selected_lag - 1),
            method="trace",
            signif=significance_level,
        )
        supported_rank = int(rank_test.rank)
        if cointegration_rank is not None:
            if not 0 < cointegration_rank < len(variables):
                raise ValueError("VECM cointegration rank must be between zero and the number of variables.")
            if supported_rank == 0:
                raise ValueError(
                    "Johansen testing found no supported cointegrating relation at the selected level; "
                    "VECM is unsuitable. Consider a stationary transformed VAR instead."
                )
            supported_rank = int(cointegration_rank)
        if supported_rank <= 0 or supported_rank >= len(variables):
            raise ValueError(
                "The data do not support a non-zero, non-saturated cointegration rank for VECM. "
                "Consider a VAR on stationary transformations."
            )
        fitted = VECM(
            frame,
            k_ar_diff=max(1, selected_lag - 1),
            coint_rank=supported_rank,
            deterministic={"c": "co", "ct": "colo"}.get(deterministic, deterministic),
        ).fit()
        stability = None
        cointegration = {
            "rank": supported_rank,
            "trace_statistic": np.asarray(rank_test.test_stats, dtype=float).tolist(),
            "critical_values": np.asarray(rank_test.crit_vals, dtype=float).tolist(),
            "method": "Johansen trace test",
            "significance_level": significance_level,
        }
        granger = {}
        irf_object = fitted.irf(min(10, max(1, len(frame) // 5)))
        irf_output = {
            "periods": list(range(len(irf_object.irfs))),
            "variables": variables,
            "values": np.asarray(irf_object.irfs, dtype=float).tolist(),
        }
        fevd_output = {"error": "FEVD is provided only for a fitted VAR in this workflow."}

    horizon = int(forecast_horizon)
    evaluation_enabled = test_size != 0
    requested_test_size = (
        max(1, int(test_size))
        if test_size is not None and evaluation_enabled
        else max(1, int(math.ceil(len(frame) * 0.2)))
        if evaluation_enabled
        else 0
    )
    holdout_count = (
        min(requested_test_size, len(frame) - minimum_rows)
        if evaluation_enabled
        else 0
    )
    if evaluation_enabled and holdout_count < 1:
        raise ValueError(
            "The sample does not leave enough observations for a chronological multivariate holdout."
        )
    train, test = (
        (frame.iloc[:-holdout_count], frame.iloc[-holdout_count:])
        if holdout_count
        else (frame, frame.iloc[:0])
    )
    if model_name == "VAR":
        if holdout_count:
            train_lag_order = VAR(train).select_order(
                maxlags=min(lag_limit, max(1, len(train) // 5)), trend="c"
            )
            train_lag = max(1, int(train_lag_order.selected_orders.get("aic") or 1))
            train_fit = VAR(train).fit(maxlags=train_lag, trend="c")
            holdout_prediction = pd.DataFrame(
                train_fit.forecast(train.to_numpy(dtype=float)[-train_fit.k_ar :], steps=len(test)),
                index=test.index,
                columns=variables,
            )
        else:
            holdout_prediction = pd.DataFrame(index=test.index, columns=variables, dtype=float)
        fitted_predictions = fitted.forecast(
            frame.to_numpy(dtype=float)[-fitted.k_ar :], steps=horizon
        )
        future_lower, future_upper = fitted.forecast_interval(
            frame.to_numpy(dtype=float)[-fitted.k_ar :],
            steps=horizon,
            alpha=significance_level,
        )[1:]
    else:
        if holdout_count:
            train_rank_test = select_coint_rank(
                train,
                det_order=johansen_det_order,
                k_ar_diff=max(1, selected_lag - 1),
                method="trace",
                signif=significance_level,
            )
            if not 0 < int(train_rank_test.rank) < len(variables):
                raise ValueError(
                    "Cointegration rank was not supported in the training sample; "
                    "VECM holdout validation is unavailable."
                )
            train_fit = VECM(
                train,
                k_ar_diff=max(1, selected_lag - 1),
                coint_rank=int(train_rank_test.rank),
                deterministic={"c": "co", "ct": "colo"}.get(deterministic, deterministic),
            ).fit()
            holdout_array = train_fit.predict(steps=len(test))
            holdout_prediction = pd.DataFrame(
                holdout_array, index=test.index, columns=variables
            )
        else:
            holdout_prediction = pd.DataFrame(index=test.index, columns=variables, dtype=float)
        fitted_predictions = fitted.predict(steps=horizon)
        future_lower = None
        future_upper = None

    metrics_by_variable = (
        {
            column: _forecast_metrics(
                test[column].to_numpy(dtype=float),
                holdout_prediction[column].to_numpy(dtype=float),
            )
            for column in variables
        }
        if holdout_count
        else {}
    )
    future_index = pd.date_range(
        frame.index[-1], periods=horizon + 1, freq=inferred
    )[1:]
    future_frame = pd.DataFrame(
        fitted_predictions,
        index=future_index,
        columns=variables,
    )
    residuals = np.asarray(getattr(fitted, "resid", []), dtype=float)
    diagnostics = {
        "residual_whiteness_p_value": None,
        "max_root_modulus": None,
    }
    try:
        diagnostics["residual_whiteness_p_value"] = _finite_or_none(
            fitted.test_whiteness(nlags=max(fitted.k_ar + 1, min(10, len(frame) // 5))).pvalue
        )
    except (ValueError, AttributeError, np.linalg.LinAlgError):
        diagnostics["residual_whiteness_p_value"] = None
    if model_name == "VAR":
        roots = np.asarray(fitted.roots, dtype=complex)
        diagnostics["max_root_modulus"] = (
            float(np.max(np.abs(roots))) if roots.size else None
        )
    normality_p = None
    try:
        normality_p = _finite_or_none(fitted.test_normality().pvalue)
    except (ValueError, AttributeError, np.linalg.LinAlgError):
        pass
    diagnostics["residual_normality_p_value"] = normality_p
    return {
        "analysis_type": "multivariate",
        "date_column": date_column,
        "endogenous_variables": variables,
        "model_name": model_name,
        "model_specification": f"{model_name}({selected_lag})",
        "frequency": frequency,
        "rows": int(len(frame)),
        "forecast_horizon": horizon,
        "selected_lag": selected_lag,
        "lag_selection": {
            key: _finite_or_none(value) for key, value in selected_order.ics.items()
        },
        "stability": stability,
        "cointegration": cointegration,
        "stationarity_profiles": stationarity_profiles,
        "granger_causality": granger,
        "impulse_responses": irf_output,
        "impulse_response_note": (
            "Orthogonalized impulse responses depend on the ordering of endogenous variables."
        ),
        "fevd": fevd_output,
        "forecast": {
            "periods": [str(value) for value in future_index],
            "values": future_frame.to_dict(orient="list"),
            "lower": (
                pd.DataFrame(future_lower, columns=variables).to_dict(orient="list")
                if future_lower is not None
                else None
            ),
            "upper": (
                pd.DataFrame(future_upper, columns=variables).to_dict(orient="list")
                if future_upper is not None
                else None
            ),
        },
        "holdout": {
            "periods": [str(value) for value in test.index],
            "actual": test.to_dict(orient="list"),
            "predicted": holdout_prediction.to_dict(orient="list"),
        },
        "evaluation": metrics_by_variable,
        "diagnostics": diagnostics,
        "residuals": (
            residuals.tolist()
            if residuals.ndim == 1
            else residuals.tolist()
        ),
    }


def johansen_cointegration_test(
    dataframe: pd.DataFrame,
    date_column: str,
    endogenous_variables: list[str] | tuple[str, ...],
    deterministic: str = "n",
    significance_level: float = 0.05,
    maxlags: int | None = None,
) -> dict[str, Any]:
    """Run a date-aligned Johansen trace-rank test with explicit assumptions."""
    variables = list(endogenous_variables)
    if len(variables) < 2 or len(variables) != len(set(variables)):
        raise ValueError("Johansen testing requires at least two distinct variables.")
    if deterministic not in {"n", "c", "ct"}:
        raise ValueError("Choose no deterministic terms, a constant, or a constant and trend.")
    if significance_level not in {0.01, 0.05, 0.1}:
        raise ValueError("Johansen rank selection supports 1%, 5%, or 10% significance levels.")
    if any(column not in dataframe.columns for column in [date_column, *variables]):
        raise ValueError("The selected time or endogenous variable is not present.")
    dates = parse_time_values(dataframe[date_column])
    values = dataframe[variables].apply(pd.to_numeric, errors="coerce")
    values = values.where(np.isfinite(values), np.nan)
    if dates.isna().any() or values.isna().any().any():
        raise ValueError("Johansen testing requires complete numeric observations and valid dates.")
    frame = values.copy()
    frame.index = pd.DatetimeIndex(dates)
    if frame.index.has_duplicates:
        raise ValueError("Resolve duplicate timestamps before Johansen testing.")
    frame = frame.sort_index()
    frequency = infer_time_frequency(frame.index)
    expected = (
        pd.date_range(frame.index.min(), frame.index.max(), freq=frequency)
        if frequency
        else pd.DatetimeIndex([])
    )
    if not frequency or not expected.equals(frame.index):
        raise ValueError("Johansen testing requires a complete, regular multivariate time index.")
    if len(frame) < max(30, 5 * len(variables) + 10):
        raise ValueError("The sample is too small for a stable Johansen rank test.")
    if any(frame[column].nunique() < 2 for column in variables):
        raise ValueError("Johansen testing is unsuitable when any selected series is constant.")
    if maxlags is not None and (maxlags < 1 or maxlags >= len(frame) // 3):
        raise ValueError("Maximum lag must be positive and less than one third of the usable sample.")
    integration_profiles = {}
    for column in variables:
        level = frame[column].astype(float)
        first_difference = level.diff().dropna()
        try:
            level_adf = float(adfuller(level, regression="c", autolag="AIC")[1])
            level_kpss = float(kpss(level, regression="c", nlags="auto")[1])
            difference_adf = float(
                adfuller(first_difference, regression="c", autolag="AIC")[1]
            )
            difference_kpss = float(
                kpss(first_difference, regression="c", nlags="auto")[1]
            )
        except (ValueError, np.linalg.LinAlgError) as error:
            raise ValueError(
                f"Integration-order screening failed for {column}: {error}"
            ) from error
        is_i1 = (
            level_adf >= significance_level
            and level_kpss < significance_level
            and difference_adf < significance_level
            and difference_kpss >= significance_level
        )
        integration_profiles[column] = {
            "level_ADF_p_value": level_adf,
            "level_KPSS_p_value": level_kpss,
            "first_difference_ADF_p_value": difference_adf,
            "first_difference_KPSS_p_value": difference_kpss,
            "I1_evidence": is_i1,
        }
    incompatible = [
        column
        for column, profile in integration_profiles.items()
        if not profile["I1_evidence"]
    ]
    if incompatible:
        raise ValueError(
            "Johansen rank inference in this workflow requires compatible I(1) evidence "
            "for every selected variable. Review integration orders before testing: "
            + ", ".join(incompatible)
            + "."
        )
    lag_limit = maxlags or min(12, max(1, len(frame) // 5))
    selected_order = VAR(frame).select_order(maxlags=lag_limit, trend="c")
    lag = max(1, int(selected_order.selected_orders.get("aic") or 1))
    result = select_coint_rank(
        frame,
        det_order={"n": -1, "c": 0, "ct": 1}[deterministic],
        k_ar_diff=max(1, lag - 1),
        method="trace",
        signif=significance_level,
    )
    return {
        "analysis_type": "multivariate",
        "model_name": "Johansen cointegration",
        "model_specification": "Johansen trace-rank test",
        "method": "Johansen trace test",
        "date_column": date_column,
        "variables": variables,
        "rows": int(len(frame)),
        "lag_order": lag,
        "deterministic": deterministic,
        "significance_level": significance_level,
        "integration_profiles": integration_profiles,
        "rank": int(result.rank),
        "trace_statistics": np.asarray(result.test_stats, dtype=float).tolist(),
        "critical_values": np.asarray(result.crit_vals, dtype=float).tolist(),
        "interpretation_note": (
            "Rank inference assumes appropriate integration orders, lag specification, "
            "deterministic terms, and no unmodeled structural breaks."
        ),
    }


def transform_time_series(
    dataframe: pd.DataFrame,
    date_column: str,
    value_column: str,
    transformation: str,
    seasonal_period: int | None = None,
) -> pd.DataFrame:
    """Return a transformed copy; never overwrite the selected input variable."""
    frame = prepare_time_series_frame(dataframe, date_column, value_column)
    series = frame["value"]
    transformations = {
        "first_difference": lambda: series.diff(),
        "second_difference": lambda: series.diff().diff(),
        "log": lambda: np.log(series.where(series > 0)),
        "percentage_change": lambda: series.pct_change(fill_method=None) * 100,
        "seasonal_difference": lambda: series.diff(seasonal_period or 12),
        "moving_average": lambda: series.rolling(seasonal_period or 3, min_periods=1).mean(),
        "rolling_standard_deviation": lambda: series.rolling(seasonal_period or 3, min_periods=2).std(),
    }
    if transformation not in transformations:
        raise ValueError(f"Unsupported transformation: {transformation}")
    transformed = transformations[transformation]()
    return pd.DataFrame(
        {
            date_column: transformed.index,
            f"{value_column}_{transformation}": transformed.to_numpy(),
        }
    )


def create_time_series_charts(
    dataframe: pd.DataFrame, result: dict[str, Any]
) -> dict[str, Any]:
    """Create consistently formatted, export-ready figures for time-series results."""
    from app.statistics.time_series_charts import create_time_series_charts as _create_charts

    return _create_charts(dataframe, result)

def create_time_series_chart(dataframe: pd.DataFrame, result: dict[str, Any]):
    """Return the forecast figure for integrations expecting one chart."""
    return create_time_series_charts(dataframe, result)["Forecasts"]
