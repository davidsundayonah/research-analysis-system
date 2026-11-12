from __future__ import annotations

import json
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats
from statsmodels.stats.diagnostic import acorr_ljungbox, het_arch, breaks_cusumolsresid, het_breuschpagan
from statsmodels.stats.outliers_influence import variance_inflation_factor
from statsmodels.stats.stattools import jarque_bera
from statsmodels.tsa.ar_model import AutoReg
from statsmodels.tsa.arima.model import ARIMA
from statsmodels.tsa.holtwinters import Holt, SimpleExpSmoothing
from statsmodels.tsa.stattools import acf, adfuller, kpss, pacf, zivot_andrews
from statsmodels.stats.multitest import multipletests

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "time_series_example.csv"
OUT = ROOT / "analysis_outputs" / "comprehensive_time_series_revision"
TABLES = OUT / "tables"
FIGURES = OUT / "figures"
YEAR = "Year"
TARGET = "Unemployment_Rate"
SYNTHETIC = [
    "Synthetic_Inflation_Rate", "Synthetic_GDP_Growth",
    "Synthetic_Wage_Index", "Synthetic_Policy_Rate",
]
NUMERIC = [TARGET, *SYNTHETIC]
BLUE, RED, TEAL, ORANGE, PURPLE = "#2457A7", "#B8423C", "#16817A", "#C66A13", "#7653A6"


def load_and_validate():
    frame = pd.read_csv(SOURCE)
    frame[YEAR] = pd.to_numeric(frame[YEAR], errors="raise").astype(int)
    for col in NUMERIC:
        frame[col] = pd.to_numeric(frame[col], errors="raise")
    if frame[YEAR].tolist() != list(range(1991, 2026)):
        raise ValueError("Expected the supplied, complete annual series 1991–2025.")
    if frame[NUMERIC].isna().any().any() or not frame[YEAR].is_unique:
        raise ValueError("The source has missing selected values or duplicate years.")
    return frame


def _arima_fit(y, order, drift=False):
    trend = "t" if drift and order[1] else "c" if not order[1] else "n"
    return ARIMA(np.asarray(y, float), order=order, trend=trend).fit()


def forecast_model(name, y, horizon):
    """Fit a benchmark/model using only y, then forecast horizon steps."""
    arr = np.asarray(y, dtype=float)
    s = pd.Series(arr)
    if name == "Naive":
        return np.repeat(arr[-1], horizon), None
    if name == "Historical mean":
        return np.repeat(arr.mean(), horizon), None
    if name == "Linear trend":
        fit = sm.OLS(arr, sm.add_constant(np.arange(len(arr)))).fit()
        x_future = sm.add_constant(np.arange(len(arr), len(arr) + horizon), has_constant="add")
        return np.asarray(fit.predict(x_future)), fit
    if name == "SES":
        fit = SimpleExpSmoothing(s, initialization_method="estimated").fit(optimized=True)
    elif name == "Holt":
        fit = Holt(s, initialization_method="estimated", damped_trend=True).fit(optimized=True)
    elif name == "AR(1)":
        fit = AutoReg(s, lags=1, trend="c").fit()
    elif name == "MA(1)":
        fit = _arima_fit(arr, (0, 0, 1))
    elif name == "ARMA(1,1)":
        fit = _arima_fit(arr, (1, 0, 1))
    elif name == "ARIMA(0,1,0)":
        fit = _arima_fit(arr, (0, 1, 0))
    elif name == "ARIMA(0,1,0) with drift":
        fit = _arima_fit(arr, (0, 1, 0), drift=True)
    elif name == "ARIMA(1,1,0)":
        fit = _arima_fit(arr, (1, 1, 0))
    elif name == "ARIMA(0,1,1)":
        fit = _arima_fit(arr, (0, 1, 1))
    elif name == "ARIMA(0,1,1) with drift":
        fit = _arima_fit(arr, (0, 1, 1), drift=True)
    elif name == "ARIMA(1,1,1)":
        fit = _arima_fit(arr, (1, 1, 1))
    elif name == "ARIMA(1,1,1) with drift":
        fit = _arima_fit(arr, (1, 1, 1), drift=True)
    else:
        raise KeyError(name)
    return np.asarray(fit.forecast(horizon), dtype=float), fit


MODEL_NAMES = [
    "Naive", "Historical mean", "Linear trend", "SES", "Holt", "AR(1)",
    "MA(1)", "ARMA(1,1)", "ARIMA(0,1,0)", "ARIMA(0,1,0) with drift",
    "ARIMA(1,1,0)", "ARIMA(0,1,1)", "ARIMA(0,1,1) with drift",
    "ARIMA(1,1,1)", "ARIMA(1,1,1) with drift",
]


def score_errors(rows):
    table = pd.DataFrame(rows)
    scored = []
    for model, group in table.groupby("Model", sort=False):
        e = group["Actual"].to_numpy() - group["Predicted"].to_numpy()
        scale = group["Training_MASE_scale"].to_numpy()
        scored.append({
            "Model": model,
            "Origins": int(group["Origin_year"].nunique()),
            "Forecast_errors": len(e),
            "RMSE": float(np.sqrt(np.mean(e ** 2))),
            "MAE": float(np.mean(np.abs(e))),
            "MAPE_percent": float(np.mean(np.abs(e / group["Actual"].to_numpy())) * 100),
            "MASE": float(np.mean(np.abs(e) / scale)),
        })
    return pd.DataFrame(scored).sort_values(["MAE", "RMSE"]).reset_index(drop=True)


def validation(frame):
    y = frame[TARGET].to_numpy(float)
    years = frame[YEAR].to_numpy(int)
    rows_h5, rows_h1 = [], []
    min_train, horizon = 20, 5
    for origin in range(min_train, len(y) - horizon + 1):
        train = y[:origin]
        scale = float(np.mean(np.abs(np.diff(train))))
        for model in MODEL_NAMES:
            try:
                pred, _ = forecast_model(model, train, horizon)
                for step, value in enumerate(pred, 1):
                    rows_h5.append({
                        "Model": model, "Origin_year": int(years[origin - 1]),
                        "Forecast_year": int(years[origin + step - 1]),
                        "Horizon": step, "Actual": float(y[origin + step - 1]),
                        "Predicted": float(value), "Training_MASE_scale": scale,
                    })
            except (ValueError, np.linalg.LinAlgError, IndexError, ZeroDivisionError):
                continue
    # Preserve the earlier one-step design as a comparison, while selecting
    # against the five-step task that matches the requested forecast horizon.
    for origin in range(min_train, len(y)):
        train = y[:origin]
        scale = float(np.mean(np.abs(np.diff(train))))
        for model in MODEL_NAMES:
            try:
                pred, _ = forecast_model(model, train, 1)
                rows_h1.append({
                    "Model": model, "Origin_year": int(years[origin - 1]),
                    "Forecast_year": int(years[origin]), "Horizon": 1,
                    "Actual": float(y[origin]), "Predicted": float(pred[0]),
                    "Training_MASE_scale": scale,
                })
            except (ValueError, np.linalg.LinAlgError, IndexError, ZeroDivisionError):
                continue
    errors5, errors1 = pd.DataFrame(rows_h5), pd.DataFrame(rows_h1)
    summary5, summary1 = score_errors(rows_h5), score_errors(rows_h1)
    # Terminal five-year holdout exactly explains the user's ARIMA concern.
    origin = len(y) - horizon
    train = y[:origin]
    terminal = []
    for model in MODEL_NAMES:
        try:
            pred, _ = forecast_model(model, train, horizon)
            for step, value in enumerate(pred, 1):
                terminal.append({
                    "Model": model, "Origin_year": int(years[origin - 1]),
                    "Forecast_year": int(years[origin + step - 1]),
                    "Horizon": step, "Actual": float(y[origin + step - 1]),
                    "Predicted": float(value),
                })
        except (ValueError, np.linalg.LinAlgError, IndexError, ZeroDivisionError):
            continue
    terminal_df = pd.DataFrame(terminal)
    terminal_summary = []
    for model, group in terminal_df.groupby("Model", sort=False):
        e = group.Actual.to_numpy() - group.Predicted.to_numpy()
        terminal_summary.append({
            "Model": model, "Origins": 1, "Forecast_errors": len(e),
            "RMSE": float(np.sqrt(np.mean(e ** 2))),
            "MAE": float(np.mean(np.abs(e))),
            "MAPE_percent": float(np.mean(np.abs(e / group.Actual.to_numpy())) * 100),
        })
    terminal_summary = pd.DataFrame(terminal_summary).sort_values(["RMSE", "MAE"])
    errors5.to_csv(TABLES / "expanding_window_5year_forecasts.csv", index=False)
    errors1.to_csv(TABLES / "expanding_window_1step_forecasts.csv", index=False)
    terminal_df.to_csv(TABLES / "terminal_5year_holdout_predictions.csv", index=False)
    summary5.to_csv(TABLES / "expanding_window_5year_model_comparison.csv", index=False)
    summary1.to_csv(TABLES / "expanding_window_1step_model_comparison.csv", index=False)
    terminal_summary.to_csv(TABLES / "terminal_5year_model_comparison.csv", index=False)
    return {"h5_errors": errors5, "h1_errors": errors1, "terminal_errors": terminal_df,
            "h5": summary5, "h1": summary1, "terminal": terminal_summary}


def variable_summaries(frame):
    rows = []
    for col in NUMERIC:
        x = frame[col]
        rows.append({
            "Variable": col, "Status": "Observed series; source not documented" if col == TARGET else "Synthetic demonstration variable",
            "N": int(x.count()), "Mean": float(x.mean()), "SD": float(x.std(ddof=1)),
            "Median": float(x.median()), "Min": float(x.min()), "Max": float(x.max()),
            "Skewness": float(x.skew()), "Excess_kurtosis": float(x.kurt()),
            "Mean_abs_annual_change": float(x.diff().abs().mean()),
        })
    out = pd.DataFrame(rows)
    out.to_csv(TABLES / "descriptive_statistics_all_numeric.csv", index=False)
    frame[NUMERIC].corr(method="pearson").to_csv(TABLES / "pearson_correlation_matrix.csv")
    frame[NUMERIC].corr(method="spearman").to_csv(TABLES / "spearman_correlation_matrix.csv")
    frame.groupby("Period_Type", dropna=False)[TARGET].agg(["count", "mean", "std", "min", "max"]).to_csv(TABLES / "unemployment_by_period_type.csv")
    return out, frame[NUMERIC].corr(method="pearson"), frame[NUMERIC].corr(method="spearman")


def stationarity_all(frame):
    rows = []
    for col in NUMERIC:
        for label, series in (("Level", frame[col]), ("First difference", frame[col].diff().dropna())):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                try:
                    adf = adfuller(series, regression="c", autolag="AIC")
                    kp = kpss(series, regression="c", nlags="auto")
                    rows.append({"Variable": col, "Series": label, "ADF_statistic": float(adf[0]),
                                 "ADF_p": float(adf[1]), "KPSS_statistic": float(kp[0]),
                                 "KPSS_p_table_bound": float(kp[1])})
                except (ValueError, np.linalg.LinAlgError) as exc:
                    rows.append({"Variable": col, "Series": label, "Error": str(exc)})
    out = pd.DataFrame(rows)
    out.to_csv(TABLES / "stationarity_all_numeric.csv", index=False)
    return out


def regression_all(frame):
    y = frame[TARGET].to_numpy(float)
    X = sm.add_constant(frame[SYNTHETIC].astype(float))
    ols = sm.OLS(y, X).fit()
    hc3 = ols.get_robustcov_results(cov_type="HC3")
    hac = ols.get_robustcov_results(cov_type="HAC", maxlags=1, use_correction=True)
    params = pd.DataFrame({
        "Term": X.columns, "Coefficient": ols.params,
        "HC3_SE": hc3.bse, "HC3_p": hc3.pvalues,
        "HC3_CI_low": hc3.conf_int()[:, 0], "HC3_CI_high": hc3.conf_int()[:, 1],
        "HAC1_SE": hac.bse, "HAC1_p": hac.pvalues,
        "HAC1_CI_low": hac.conf_int()[:, 0], "HAC1_CI_high": hac.conf_int()[:, 1],
    })
    vif = pd.DataFrame([
        {"Variable": name, "VIF": float(variance_inflation_factor(X.to_numpy(), i))}
        for i, name in enumerate(X.columns) if name != "const"
    ])
    residual = np.asarray(ols.resid)
    bp = het_breuschpagan(residual, X.to_numpy())
    jb = jarque_bera(residual)
    lb = acorr_ljungbox(residual, lags=[min(5, max(1, len(residual) // 5))], return_df=True)
    diagnostics = {
        "N": len(frame), "R_squared": float(ols.rsquared), "Adjusted_R_squared": float(ols.rsquared_adj),
        "HC3_joint_F": float(hc3.fvalue), "HC3_joint_p": float(hc3.f_pvalue),
        "HAC1_joint_F": float(hac.fvalue), "HAC1_joint_p": float(hac.f_pvalue),
        "Breusch_Pagan_LM": float(bp[0]), "Breusch_Pagan_p": float(bp[1]),
        "Jarque_Bera": float(jb[0]), "Jarque_Bera_p": float(jb[1]),
        "Durbin_Watson": float(sm.stats.stattools.durbin_watson(residual)),
        "Ljung_Box_lag5_p": float(lb.lb_pvalue.iloc[0]),
        "Condition_number": float(np.linalg.cond(X.to_numpy())),
    }
    params.to_csv(TABLES / "multivariable_regression_HC3_HAC1.csv", index=False)
    vif.to_csv(TABLES / "multivariable_regression_VIF.csv", index=False)
    (TABLES / "multivariable_regression_diagnostics.json").write_text(json.dumps(diagnostics, indent=2))
    pd.DataFrame({"Year": frame[YEAR], "Actual": y, "Fitted": ols.fittedvalues, "Residual": residual}).to_csv(TABLES / "multivariable_regression_fitted_residuals.csv", index=False)
    return ols, params, vif, diagnostics


def structural_breaks(frame):
    y = frame[TARGET].to_numpy(float)
    years = frame[YEAR].to_numpy(int)
    t = years - years[0]
    rows = []
    # Include 2015 to reconcile the earlier classical Chow screen with the
    # HAC-robust prespecified break tests; adjust all five dates together.
    candidate_years = [2008, 2009, 2015, 2019, 2020]
    for cut in candidate_years:
        post = (years >= cut).astype(float)
        X = np.column_stack([np.ones(len(y)), t, post, t * post])
        model = sm.OLS(y, X).fit(cov_type="HAC", cov_kwds={"maxlags": 1})
        R = np.array([[0, 0, 1, 0], [0, 0, 0, 1]], float)
        test = model.wald_test(R, use_f=True, scalar=True)
        rows.append({"Break_year": cut, "Before_n": int((years < cut).sum()),
                     "After_n": int((years >= cut).sum()), "HAC_joint_F": float(test.statistic),
                     "p_raw": float(test.pvalue), "Method": "HAC(1) joint level/slope change"})
    adjusted = multipletests([r["p_raw"] for r in rows], method="holm")[1]
    for row, p in zip(rows, adjusted):
        row["p_Holm_5_candidates"] = float(p)
    tests = pd.DataFrame(rows)

    # Data-selected single-break sup-F search; bootstrap the maximum statistic
    # under the no-break linear-trend null using centered residual resampling.
    base_X = sm.add_constant(t)
    base = sm.OLS(y, base_X).fit()
    candidates = np.arange(6, len(y) - 5)
    fs = []
    for ix in candidates:
        D = (np.arange(len(y)) >= ix).astype(float)
        X = np.column_stack([np.ones(len(y)), t, D, t * D])
        alt = sm.OLS(y, X).fit()
        df_num = 2
        df_den = len(y) - X.shape[1]
        fs.append(max(0.0, ((base.ssr - alt.ssr) / df_num) / (alt.ssr / df_den)))
    observed_supf = float(max(fs))
    best_ix = int(candidates[int(np.argmax(fs))])
    rng = np.random.default_rng(20261112)
    fitted = np.asarray(base.fittedvalues)
    errors = np.asarray(base.resid) - np.mean(base.resid)
    B = 1999
    boot_sup = np.zeros(B)
    # Circular moving-block resampling, block length 2, for short-run dependence.
    block = 2
    for b in range(B):
        pieces = []
        while len(pieces) < len(y):
            start = int(rng.integers(0, len(errors)))
            pieces.extend(errors[(start + j) % len(errors)] for j in range(block))
        yb = fitted + np.asarray(pieces[:len(y)])
        bb = sm.OLS(yb, base_X).fit()
        vals = []
        for ix in candidates:
            D = (np.arange(len(yb)) >= ix).astype(float)
            X = np.column_stack([np.ones(len(yb)), t, D, t * D])
            alt = sm.OLS(yb, X).fit()
            vals.append(max(0.0, ((bb.ssr - alt.ssr) / 2) / (alt.ssr / (len(yb) - 4))))
        boot_sup[b] = max(vals)
    sup_p = float((1 + np.sum(boot_sup >= observed_supf)) / (B + 1))
    data_selected = {"Method": "Sup-F over one-break linear-trend dates; circular residual block bootstrap",
                     "Selected_break_year": int(years[best_ix]), "Sup_F": observed_supf,
                     "Bootstrap_replicates": B, "Block_length": block, "Bootstrap_p": sup_p,
                     "Caveat": "Exploratory; bootstrap assumes short-run residual blocks are informative under the no-break null."}
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            za = zivot_andrews(y, regression="c", autolag="AIC")
        za_result = {"Method": "Zivot-Andrews one-intercept-break unit-root test",
                     "Selected_break_year": int(years[int(za[4])]),
                     "Statistic": float(za[0]), "p_value": float(za[1]),
                     "Critical_values": {k: float(v) for k, v in za[2].items()}}
    except (ValueError, np.linalg.LinAlgError) as exc:
        za_result = {"Method": "Zivot-Andrews one-intercept-break unit-root test", "Error": str(exc)}
    tests.to_csv(TABLES / "candidate_structural_break_tests.csv", index=False)
    (TABLES / "data_selected_supf.json").write_text(json.dumps(data_selected, indent=2))
    (TABLES / "zivot_andrews_break_test.json").write_text(json.dumps(za_result, indent=2))
    return tests, data_selected, za_result


def candidate_diagnostics(name, y):
    _, fit = forecast_model(name, y, 5)
    if fit is None:
        if name == "Historical mean":
            residuals = np.asarray(y, float) - np.mean(y)
        elif name == "Naive":
            residuals = np.diff(np.asarray(y, float))
        else:
            residuals = sm.OLS(y, sm.add_constant(np.arange(len(y)))).fit().resid
    else:
        residuals = np.asarray(fit.resid, float)
    residuals = residuals[np.isfinite(residuals)]
    lb_lag = min(5, max(1, len(residuals) // 5))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        lb = acorr_ljungbox(residuals, lags=[lb_lag], return_df=True)
    jb = jarque_bera(residuals)
    arch = het_arch(residuals, nlags=min(4, max(1, len(residuals) // 5))) if len(residuals) >= 8 else (np.nan, np.nan)
    return {"Model": name, "Residual_n": len(residuals), "Ljung_Box_lag": lb_lag,
            "Ljung_Box_p": float(lb.lb_pvalue.iloc[0]), "Jarque_Bera": float(jb[0]),
            "Jarque_Bera_p": float(jb[1]), "ARCH_LM": float(arch[0]), "ARCH_LM_p": float(arch[1]),
            "Residual_min": float(np.min(residuals)), "Residual_max": float(np.max(residuals)),
            "Residual_SD": float(np.std(residuals, ddof=1))}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    TABLES.mkdir(parents=True, exist_ok=True)
    FIGURES.mkdir(parents=True, exist_ok=True)
    frame = load_and_validate()
    (OUT / "source_sha256.txt").write_text(__import__("hashlib").sha256(SOURCE.read_bytes()).hexdigest())
    desc, pearson, spearman = variable_summaries(frame)
    stat = stationarity_all(frame)
    cv = validation(frame)
    breaks = structural_breaks(frame)
    ols, coef, vif, reg_diag = regression_all(frame)
    diagnostics = pd.DataFrame([candidate_diagnostics(name, frame[TARGET].to_numpy(float)) for name in MODEL_NAMES])
    diagnostics.to_csv(TABLES / "candidate_residual_diagnostics.csv", index=False)
    print("Five-step expanding window:")
    print(cv["h5"].to_string(index=False))
    print("Terminal five-year holdout:")
    print(cv["terminal"].to_string(index=False))
    print("Structural breaks:")
    print(breaks[0].to_string(index=False))
    print("Regression diagnostics:", reg_diag)
    print("Stationarity:")
    print(stat.to_string(index=False))
    print("Source hash:", (OUT / "source_sha256.txt").read_text())


if __name__ == "__main__":
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        main()
