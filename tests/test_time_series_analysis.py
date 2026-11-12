from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app.statistics.time_series_analysis import (
    _compare_forecasts,
    _combined_stationarity_interpretation,
    _finite_or_none,
    _forecast_metrics,
    _forecast_model,
    analyze_time_series,
    analyze_exogenous_time_series,
    analyze_multivariate_time_series,
    create_time_series_charts,
    detect_time_series,
    inspect_time_series_dataset,
    johansen_cointegration_test,
    parse_pasted_data,
    preprocess_time_series_dataframe,
    prepare_time_series_frame,
    recommend_time_series_methods,
    read_time_series_file,
    residual_diagnostic_warnings,
    stationarity_test_conclusion,
    stationarity_p_value_display,
    transform_time_series,
    validate_time_series,
)


@pytest.fixture
def monthly_data():
    dates = pd.date_range("2020-01-01", periods=48, freq="MS")
    values = 100 + np.arange(48) * 2 + np.sin(np.arange(48) * 2 * np.pi / 12) * 8
    return pd.DataFrame({"date": dates, "output": values})


def test_time_series_analysis_has_tests_forecast_and_chronological_evaluation(monthly_data):
    result = analyze_time_series(
        monthly_data,
        "date",
        "output",
        forecast_horizon=4,
        test_size=6,
    )

    assert result["rows"] == len(monthly_data)
    assert result["frequency_label"] == "Monthly"
    assert len(result["forecast_values"]) == 4
    assert len(result["forecast_lower"]) == 4
    assert len(result["forecast_upper"]) == 4
    assert {"ADF", "KPSS", "Phillips-Perron"} == set(result["stationarity_tests"])
    assert {"MSE", "MAE", "RMSE", "MAPE"} == set(result["evaluation"])
    assert result["evaluation"]["MSE"] == pytest.approx(result["evaluation"]["RMSE"] ** 2)
    assert result["evaluation"]["RMSE"] >= 0
    assert len(result["holdout"]["periods"]) == 6
    assert len(result["holdout"]["actual"]) == len(result["holdout"]["predicted"]) == 6
    assert {"acf", "pacf"} == set(result["correlogram"])
    assert result["seasonal_components"]
    assert "Jarque-Bera p-value" in result["diagnostics"]
    assert "ARCH LM p-value" in result["diagnostics"]
    assert {
        "Naive",
        "Mean",
        "Linear trend",
        "Holt",
        "ARIMA(1,1,1)",
        "Exponential smoothing",
    }.issubset(result["model_comparison"])
    assert result["model_evaluation_design"] == {
        "training_observations": 42,
        "holdout_observations": 6,
        "training_end": "2023-06-01",
        "holdout_start": "2023-07-01 00:00:00",
        "final_estimation_observations": 48,
        "final_model_refit_on_full_series": True,
        "evaluation_enabled": True,
        "validation_strategy": "holdout",
        "training_fraction": 0.875,
    }
    assert result["prediction_interval"]["confidence_level"] == pytest.approx(0.95)
    assert result["time_series_plot"]["rolling_mean"]
    assert result["residual_plot"]["values"]
    assert result["residual_acf"]
    assert "Time-series analysis" in result["summary"]


def test_default_nigeria_validation_is_chronological_eighty_twenty_split():
    dataset = Path(__file__).resolve().parents[1] / "time_series_example.csv"
    frame = pd.read_csv(dataset)

    result = analyze_time_series(
        frame,
        "Year",
        "Unemployment_Rate",
        test_size=None,
    )
    design = result["model_evaluation_design"]

    assert result["rows"] == 35
    assert design["training_observations"] == 28
    assert design["holdout_observations"] == 7
    assert design["training_end"] == "2018-01-01"
    assert design["holdout_start"] == "2019-01-01 00:00:00"
    assert design["final_estimation_observations"] == 35
    assert design["final_model_refit_on_full_series"] is True
    assert len(result["forecast_values"]) == 6
    assert len(result["holdout"]["actual"]) == len(result["holdout"]["predicted"]) == 7


@pytest.mark.parametrize("strategy", ["rolling-window", "expanding-window"])
def test_rolling_and_expanding_validation_are_chronological(monthly_data, strategy):
    result = analyze_time_series(
        monthly_data,
        "date",
        "output",
        test_size=6,
        validation_strategy=strategy,
    )

    assert result["model_evaluation_design"]["validation_strategy"] == strategy
    assert result["model_evaluation_design"]["training_observations"] == 42
    assert result["model_evaluation_design"]["holdout_observations"] == 6
    assert len(result["model_comparison"]["Naive"]["actual"]) == 6
    assert len(result["model_comparison"]["Naive"]["predicted"]) == 6
    assert len(result["holdout"]["actual"]) == len(result["holdout"]["predicted"]) == 6


def test_evaluation_can_be_disabled_and_small_samples_are_not_scored():
    dates = pd.date_range("2020-01-01", periods=6, freq="YS")
    frame = pd.DataFrame({"date": dates, "value": np.arange(6, dtype=float) + 10})

    disabled = analyze_time_series(frame, "date", "value", test_size=0)
    small = analyze_time_series(frame, "date", "value")

    assert disabled["model_comparison"] == {}
    assert disabled["model_evaluation_design"]["evaluation_enabled"] is False
    assert any("evaluation was disabled" in issue for issue in disabled["validation"]["issues"])
    assert small["model_comparison"] == {}
    assert any("fewer than eight observations" in issue for issue in small["validation"]["issues"])


def test_arima_and_holt_style_forecasts_are_available(monthly_data):
    result = analyze_time_series(
        monthly_data,
        "date",
        "output",
        forecast_horizon=3,
        model_name="ARIMA",
    )
    assert len(result["forecast_values"]) == 3
    assert all(np.isfinite(result["forecast_values"]))


def test_sarima_uses_detected_seasonal_period(monthly_data):
    result = analyze_time_series(
        monthly_data,
        "date",
        "output",
        forecast_horizon=2,
        model_name="SARIMA",
        seasonal_order=(1, 0, 0),
    )

    assert len(result["forecast_values"]) == 2
    assert result["model_specification"] == "SARIMA(1,1,1)(1,0,0,12)"


def test_constant_series_results_remain_json_safe():
    frame = pd.DataFrame(
        {"date": pd.date_range("2022-01-01", periods=24, freq="MS"), "value": 5.0}
    )
    result = analyze_time_series(frame, "date", "value")

    assert all(
        value is None or np.isfinite(value)
        for value in result["descriptive_statistics"].values()
    )
    assert all(value is None or np.isfinite(value) for value in result["correlogram"]["acf"])


@pytest.mark.parametrize("test_name", ["ADF", "PP", "KPSS"])
@pytest.mark.parametrize("alpha", [0.01, 0.05, 0.10])
def test_stationarity_decisions_use_strict_alpha_boundary(test_name, alpha):
    at_alpha = stationarity_test_conclusion(test_name, alpha, alpha)
    below_alpha = stationarity_test_conclusion(test_name, alpha - 0.001, alpha)

    assert at_alpha["reject_null"] is False
    assert below_alpha["reject_null"] is True
    if test_name == "KPSS":
        assert "stationarity null" in below_alpha["conclusion"]
        assert "not proof of stationarity" in at_alpha["conclusion"]
    else:
        assert "does not establish that a unit root exists" in at_alpha["conclusion"]


def test_full_precision_p_value_decision_is_independent_of_rounded_display():
    below_alpha = stationarity_test_conclusion("ADF", 0.00099, 0.001)
    above_alpha = stationarity_test_conclusion("ADF", 0.00101, 0.001)

    assert below_alpha["reject_null"] is True
    assert above_alpha["reject_null"] is False
    assert stationarity_p_value_display(
        {"p_value": 0.00099, "null": "The series has a unit root."}
    ) == "p < 0.001"
    assert stationarity_p_value_display(
        {"p_value": 0.00101, "null": "The series has a unit root."}
    ) == "p = 0.001"


def test_stationarity_interpretation_reflects_selected_alpha():
    values = np.cumsum(np.random.default_rng(42).normal(size=48)) + 100
    frame = pd.DataFrame(
        {"date": pd.date_range("2020-01-01", periods=48, freq="MS"), "value": values}
    )
    strict = analyze_time_series(frame, "date", "value", significance_level=0.01)
    relaxed = analyze_time_series(frame, "date", "value", significance_level=0.10)

    assert strict["significance_level"] == 0.01
    assert relaxed["significance_level"] == 0.10
    assert strict["stationarity_assessment"]["level"]["ADF"]["reject_null"] == (
        strict["stationarity_assessment"]["level"]["ADF"]["p_value"] < 0.01
    )
    assert relaxed["stationarity_assessment"]["level"]["ADF"]["reject_null"] == (
        relaxed["stationarity_assessment"]["level"]["ADF"]["p_value"] < 0.10
    )


def test_combined_interpretation_reports_conflicting_tests_without_forcing_a_label():
    tests = {
        "ADF": {"reject_null": True},
        "Phillips-Perron": {"reject_null": False},
        "KPSS": {"reject_null": True},
    }

    interpretation = _combined_stationarity_interpretation(tests, "level")

    assert "conflicting evidence" in interpretation
    assert "Do not force a definitive" in interpretation


def test_first_difference_interpretation_is_distinct_from_level():
    tests = {
        "ADF": {"reject_null": True},
        "Phillips-Perron": {"reject_null": False},
        "KPSS": {"reject_null": True},
    }

    level = _combined_stationarity_interpretation(tests, "trend", "level")
    difference = _combined_stationarity_interpretation(
        tests, "trend", "first_difference"
    )

    assert "trend stationarity in levels" in level
    assert "first-difference stationarity" in difference
    assert level != difference
    assert "conflicting evidence" in difference


def test_capped_kpss_p_value_display_preserves_lookup_limit():
    capped = {
        "p_value": 0.1,
        "null": "The series is stationary under the specified deterministic terms.",
        "warnings": ["The actual p-value is greater than the returned value."],
    }
    ordinary = {
        "p_value": 0.0007,
        "null": "The series has a unit root.",
        "warnings": [],
    }

    assert stationarity_p_value_display(capped) == "p >= 0.100"
    assert stationarity_p_value_display(ordinary) == "p < 0.001"


def test_six_time_series_figures_are_independently_exportable(monthly_data, tmp_path):
    result = analyze_time_series(
        monthly_data,
        "date",
        "output",
        test_size=6,
        include_second_difference=True,
    )

    figures = create_time_series_charts(monthly_data, result)

    assert list(figures) == [
        "Original series and trend",
        "Seasonal decomposition",
        "Rolling statistics",
        "Differences",
        "ACF and PACF",
        "Residual diagnostics",
        "Forecasts",
        "Model comparison",
    ]
    assert len(figures["Rolling statistics"].axes) == 2
    assert "Rolling mean" in figures["Rolling statistics"].axes[0].get_title(loc="left")
    assert "Rolling standard deviation" in figures["Rolling statistics"].axes[1].get_title(loc="left")
    assert len(figures["ACF and PACF"].axes) == 2
    assert len(figures["Residual diagnostics"].axes) == 4
    for index, (name, figure) in enumerate(figures.items()):
        output = tmp_path / f"chart_{index}.png"
        figure.savefig(output, dpi=80)
        assert output.stat().st_size > 0, name


def test_original_first_and_optional_second_difference_tests_are_reported(monthly_data):
    result = analyze_time_series(
        monthly_data,
        "date",
        "output",
        include_second_difference=True,
        deterministic_specification="Constant and trend",
    )

    assert set(result["stationarity_assessment"]) == {
        "level",
        "first_difference",
        "second_difference",
    }
    assert "trend stationarity" in result["stationarity_interpretations"]["level"]
    assert "first-difference stationarity" in result["stationarity_interpretations"]["first_difference"]
    assert len(result["time_series_plot"]["second_difference"]) == len(monthly_data)


def test_chronological_model_comparison_uses_training_only(monthly_data):
    series = prepare_time_series_frame(monthly_data, "date", "output")["value"]
    train, test = series.iloc[:-6], series.iloc[-6:]
    altered_test = test + 1000
    first, _ = _compare_forecasts(train, test, "ARIMA", (1, 1, 1), (1, 1, 1), 12)
    second, _ = _compare_forecasts(
        train, altered_test, "ARIMA", (1, 1, 1), (1, 1, 1), 12
    )

    assert first.keys() == second.keys()
    for model in first:
        assert first[model]["predicted"] == pytest.approx(second[model]["predicted"])
    assert first["Mean"]["RMSE"] != second["Mean"]["RMSE"]


def test_optional_information_criteria_and_forecast_metrics_are_safe():
    assert _finite_or_none(None) is None
    assert _finite_or_none(float("nan")) is None
    assert _finite_or_none(float("inf")) is None
    assert _finite_or_none(2.5) == 2.5
    metrics = _forecast_metrics(np.array([1.0, 2.0, 0.0]), np.array([2.0, 4.0, 1.0]))
    assert metrics["MSE"] == pytest.approx(2.0)
    assert metrics["RMSE"] == pytest.approx(np.sqrt(2.0))
    assert metrics["MAE"] == pytest.approx(4.0 / 3.0)
    assert metrics["MAPE"] == pytest.approx(100.0)


def test_forecast_intervals_are_labeled_and_calculated_by_method(monthly_data):
    series = prepare_time_series_frame(monthly_data, "date", "output")["value"]
    fitted, forecast, lower, upper = _forecast_model(
        series, 3, "ARIMA", None, (1, 1, 1), (1, 1, 1), alpha=0.05
    )

    assert len(lower) == len(upper) == len(forecast) == 3
    assert np.all(np.asarray(lower) < np.asarray(forecast))
    assert np.all(np.asarray(forecast) < np.asarray(upper))
    assert fitted.get_forecast(3).conf_int(alpha=0.05).iloc[:, 0].to_numpy() == pytest.approx(
        np.asarray(lower)
    )

    result = analyze_time_series(monthly_data, "date", "output", model_name="ARIMA")
    assert result["prediction_interval"]["method"] == "Formal model-based prediction interval"


def test_exponential_smoothing_interval_uses_documented_residual_scale(monthly_data):
    series = prepare_time_series_frame(monthly_data, "date", "output")["value"]
    fitted, forecast, lower, upper = _forecast_model(
        series, 3, "Exponential smoothing", 12
    )
    residual_scale = np.std(np.asarray(fitted.resid, dtype=float), ddof=1)
    expected_width = 1.96 * residual_scale * np.sqrt(np.arange(1, 4))

    assert np.asarray(forecast) - np.asarray(lower) == pytest.approx(
        expected_width, abs=1e-8
    )
    assert np.asarray(upper) - np.asarray(forecast) == pytest.approx(
        expected_width, abs=1e-8
    )
    result = analyze_time_series(monthly_data, "date", "output")
    assert result["prediction_interval"]["method"] == "Approximate residual-based interval"
    assert "approximately Gaussian" in result["prediction_interval"]["assumptions"]


def test_diagnostic_warning_thresholds_and_nonconvergence():
    warnings = residual_diagnostic_warnings(
        {
            "Ljung-Box p-value": 0.01,
            "Jarque-Bera p-value": 0.20,
            "ARCH LM p-value": 0.03,
        },
        "Did not converge.",
        0.05,
    )

    assert len(warnings) == 3
    assert any("autocorrelation" in warning for warning in warnings)
    assert any("heteroskedasticity" in warning for warning in warnings)
    assert any("did not converge" in warning for warning in warnings)


def test_supplied_unemployment_series_regression():
    dataset = Path(__file__).resolve().parents[1] / "time_series_example.csv"
    frame = pd.read_csv(dataset)
    result = analyze_time_series(
        frame,
        "Year",
        "Unemployment_Rate",
        forecast_horizon=3,
        test_size=5,
    )

    assert result["rows"] == 35
    assert result["start_date"] == "1991-01-01"
    assert result["end_date"] == "2025-01-01"
    assert len(result["forecast_values"]) == 3
    assert len(result["holdout"]["actual"]) == 5
    assert result["model_evaluation_design"]["training_observations"] == 30
    assert result["model_evaluation_design"]["holdout_observations"] == 5
    assert result["model_evaluation_design"]["final_estimation_observations"] == 35
    # The fixture contains 35 annual level observations with no missing values.
    # Under the default constant specification, AIC selects 3 ADF lags, leaving
    # 31 effective observations; the current fixture's p-value is about 0.0881.
    # The older 0.016789 expectation does not match this data/specification.
    assert result["stationarity_tests"]["ADF"]["p_value"] == pytest.approx(
        0.088058, abs=0.001
    )
    assert result["stationarity_tests"]["ADF"]["autolag"] == "AIC"
    assert result["stationarity_tests"]["ADF"]["used_lags"] == 3
    assert result["stationarity_tests"]["ADF"]["observations"] == 31
    # Independently reproduced with arch PhillipsPerron on the same 35
    # untransformed level observations and constant specification.
    assert result["stationarity_tests"]["Phillips-Perron"]["p_value"] == pytest.approx(
        0.605358, abs=0.001
    )
    assert result["stationarity_tests"]["KPSS"]["p_value"] == 0.1
    assert stationarity_p_value_display(result["stationarity_tests"]["KPSS"]) == "p >= 0.100"
    assert "p >= 0.100" in result["summary"]
    assert any(
        "actual p-value is greater" in warning
        for warning in result["stationarity_tests"]["KPSS"]["warnings"]
    )
    assert "do not provide a decisive result" in result["stationarity_interpretations"]["level"]
    assert result["convergence_status"] == "Converged."
    assert all(
        value is not None
        for value in result["model_comparison"]["Naive"].values()
        if isinstance(value, float)
    )


def test_time_detection_supports_year_and_quarter_values():
    yearly = pd.DataFrame({"Year": [2020, 2021, 2022], "GDP": [1.0, 2.0, 3.0]})
    quarterly = pd.DataFrame({"period": ["2022Q1", "2022Q2", "2022Q3"], "rate": [1.2, 1.4, 1.6]})

    year_result = detect_time_series(yearly)
    quarter_result = detect_time_series(quarterly)

    assert year_result["date_column"] == "Year"
    assert year_result["frequency_label"] == "Annual"
    assert quarter_result["date_column"] == "period"
    assert quarter_result["frequency_label"] == "Quarterly"


def test_validation_reports_missing_periods_and_duplicate_dates():
    frame = pd.DataFrame(
        {
            "date": ["2024-01-01", "2024-03-01", "2024-03-01"],
            "value": [1, 3, 4],
        }
    )
    report = validate_time_series(frame, "date", "value")
    assert report["duplicate_periods"] == 1
    assert report["missing_periods"] == 0
    with pytest.raises(ValueError, match="Duplicate time periods"):
        prepare_time_series_frame(frame, "date", "value")


def test_missing_month_is_reported_without_filling_it():
    frame = pd.DataFrame(
        {"date": ["2024-01-01", "2024-03-01", "2024-04-01"], "value": [1, 3, 4]}
    )
    report = validate_time_series(frame, "date", "value")

    assert report["frequency"] == "MS"
    assert report["missing_periods"] == 1
    assert "no values were imputed" in " ".join(report["issues"])


def test_pasted_tabular_data_and_transformations_keep_a_new_column(monthly_data):
    pasted = parse_pasted_data("date\toutput\n2024-01-01\t2\n2024-02-01\t4")
    transformed = transform_time_series(monthly_data, "date", "output", "first_difference")

    assert pasted.shape == (2, 2)
    assert transformed.columns.tolist() == ["date", "output_first_difference"]
    assert monthly_data.columns.tolist() == ["date", "output"]


def test_missing_columns_are_reported(monthly_data):
    with pytest.raises(ValueError, match="not present"):
        prepare_time_series_frame(monthly_data, "date", "missing")


def test_dataset_inspection_and_recommendations_respect_selected_roles(monthly_data):
    univariate = recommend_time_series_methods(
        monthly_data, "date", dependent_variables=["output"]
    )
    assert "ARIMA" in {item["method"] for item in univariate["recommended"]}
    assert "VAR" not in {item["method"] for item in univariate["recommended"]}

    multicolumn = monthly_data.assign(
        predictor=np.cos(np.arange(len(monthly_data))),
        second=np.arange(len(monthly_data), dtype=float) ** 2,
        group=["A", "B"] * (len(monthly_data) // 2),
    )
    inspection = inspect_time_series_dataset(multicolumn, "date")
    assert inspection["numeric_columns"] == ["output", "predictor", "second"]
    assert inspection["categorical_columns"] == ["group"]
    exogenous = recommend_time_series_methods(
        multicolumn,
        "date",
        dependent_variables=["output"],
        exogenous_variables=["predictor"],
    )
    assert "ARIMAX" in {item["method"] for item in exogenous["recommended"]}
    assert "VAR" not in {item["method"] for item in exogenous["recommended"]}
    vector = recommend_time_series_methods(
        multicolumn,
        "date",
        endogenous_variables=["output", "second"],
    )
    assert "stationarity_profiles" in vector
    assert any(
        item["method"] == "VECM" for item in vector["conditional"]
    )


def test_preprocessing_changes_only_a_working_copy_and_records_operations():
    source = pd.DataFrame(
        {
            "date": ["2024-01-01", "2024-02-01", "2024-02-01", "2024-03-01"],
            "value": [1.0, 3.0, 5.0, 7.0],
        }
    )
    before = source.copy(deep=True)
    working, operations = preprocess_time_series_dataframe(
        source, "date", [{"action": "aggregate_mean"}]
    )
    assert len(working) == 3
    assert working.loc[1, "value"] == pytest.approx(4.0)
    assert operations[-1]["action"] == "aggregate_mean"
    assert operations[-1]["rows_changed"] == 1
    pd.testing.assert_frame_equal(source, before)


def test_csv_and_excel_import_preserve_multiple_columns(tmp_path, monthly_data):
    csv_path = tmp_path / "multiple.csv"
    excel_path = tmp_path / "multiple.xlsx"
    monthly_data.assign(predictor=np.arange(len(monthly_data))).to_csv(
        csv_path, index=False
    )
    monthly_data.assign(predictor=np.arange(len(monthly_data))).to_excel(
        excel_path, index=False
    )
    for path in (csv_path, excel_path):
        loaded = read_time_series_file(path)
        assert loaded.columns.tolist() == ["date", "output", "predictor"]
        assert len(loaded) == len(monthly_data)


def test_exogenous_forecasting_requires_and_labels_future_predictors():
    rng = np.random.default_rng(42)
    count = 120
    dates = pd.date_range("2018-01-01", periods=count, freq="MS")
    predictor = np.zeros(count)
    outcome = np.zeros(count)
    for index in range(1, count):
        predictor[index] = 0.45 * predictor[index - 1] + rng.normal()
        outcome[index] = 0.6 * outcome[index - 1] + 0.5 * predictor[index] + rng.normal()
    frame = pd.DataFrame({"date": dates, "outcome": outcome, "predictor": predictor})

    unavailable = analyze_exogenous_time_series(
        frame,
        "date",
        "outcome",
        ["predictor"],
        forecast_horizon=3,
        model_name="ARIMAX",
        order=(1, 0, 0),
    )
    assert not unavailable["forecast_values"]
    assert "were not produced" in unavailable["forecast_limitation"]
    assert unavailable["evaluation"]["MSE"] == pytest.approx(
        unavailable["evaluation"]["RMSE"] ** 2
    )

    future_dates = pd.date_range(
        dates[-1] + pd.offsets.MonthBegin(), periods=3, freq="MS"
    )
    baseline = pd.DataFrame(
        {"date": future_dates, "predictor": [1.0, 2.0, 3.0]}
    )
    optimistic = baseline.assign(predictor=[2.0, 3.0, 4.0])
    result = analyze_exogenous_time_series(
        frame,
        "date",
        "outcome",
        ["predictor"],
        forecast_horizon=3,
        model_name="ARIMAX",
        order=(1, 0, 0),
        future_exog=baseline,
        scenarios={"Optimistic": optimistic},
    )
    assert result["future_predictor_source"] == "researcher-supplied scenario values"
    assert set(result["scenario_forecasts"]) == {"Baseline", "Optimistic"}
    assert len(result["forecast_values"]) == 3
    assert result["parameter_inference"]["predictor"]["p_value"] is not None

    estimated = analyze_exogenous_time_series(
        frame,
        "date",
        "outcome",
        ["predictor"],
        forecast_horizon=3,
        model_name="Regression",
        auto_forecast_exog=True,
    )
    assert estimated["future_predictor_source"] == "estimated by independent time-series forecasts"
    assert len(estimated["forecast_values"]) == 3


def test_exogenous_recommendations_and_fits_require_stationary_predictors():
    rng = np.random.default_rng(128)
    count = 120
    dates = pd.date_range("2018-01-01", periods=count, freq="MS")
    stationary = np.zeros(count)
    integrated = np.cumsum(rng.normal(size=count))
    outcome = np.zeros(count)
    for index in range(1, count):
        stationary[index] = 0.4 * stationary[index - 1] + rng.normal()
        outcome[index] = 0.5 * outcome[index - 1] + stationary[index] + rng.normal()
    frame = pd.DataFrame(
        {"date": dates, "outcome": outcome, "stationary": stationary, "integrated": integrated}
    )

    recommendation = recommend_time_series_methods(
        frame,
        "date",
        dependent_variables=["outcome"],
        exogenous_variables=["integrated"],
    )
    assert "ARIMAX" not in {item["method"] for item in recommendation["recommended"]}
    assert any("level-stationarity" in item["reason"] for item in recommendation["conditional"])
    with pytest.raises(ValueError, match="level-stationary exogenous predictors"):
        analyze_exogenous_time_series(
            frame,
            "date",
            "outcome",
            ["integrated"],
            model_name="ARIMAX",
            test_size=0,
        )

    valid = analyze_exogenous_time_series(
        frame,
        "date",
        "outcome",
        ["stationary"],
        model_name="Regression",
        test_size=0,
    )
    assert valid["evaluation"] == {}
    assert valid["model_evaluation_design"]["holdout_observations"] == 0


def test_johansen_rejects_series_without_compatible_i1_evidence():
    dates = pd.date_range("2018-01-01", periods=60, freq="MS")
    frame = pd.DataFrame(
        {
            "date": dates,
            "first": np.sin(np.arange(60)),
            "second": np.cos(np.arange(60)),
        }
    )
    with pytest.raises(ValueError, match="compatible I\\(1\\) evidence"):
        johansen_cointegration_test(frame, "date", ["first", "second"])


def test_var_forecasting_causality_fevd_and_holdout_are_computed():
    rng = np.random.default_rng(9)
    count = 120
    dates = pd.date_range("2018-01-01", periods=count, freq="MS")
    first = np.zeros(count)
    second = np.zeros(count)
    first[0] = rng.normal() / np.sqrt(1 - 0.2**2)
    second[0] = rng.normal() / np.sqrt(1 - 0.35**2)
    for index in range(1, count):
        first[index] = 0.2 * first[index - 1] + rng.normal()
        second[index] = 0.35 * second[index - 1] + 0.25 * first[index - 1] + rng.normal()
    frame = pd.DataFrame({"date": dates, "first": first, "second": second})
    result = analyze_multivariate_time_series(
        frame, "date", ["first", "second"], forecast_horizon=3
    )
    assert result["analysis_type"] == "multivariate"
    assert result["stability"] is True
    assert set(result["granger_causality"]) == {"first", "second"}
    assert "values" in result["fevd"]
    assert set(result["forecast"]["values"]) == {"first", "second"}
    assert len(result["holdout"]["periods"]) > 0

    without_evaluation = analyze_multivariate_time_series(
        frame,
        "date",
        ["first", "second"],
        forecast_horizon=2,
        test_size=0,
    )
    assert without_evaluation["evaluation"] == {}
    assert without_evaluation["holdout"]["periods"] == []
    assert set(result["evaluation"]["first"]) == {"MSE", "RMSE", "MAE", "MAPE"}


def test_johansen_and_vecm_work_on_a_cointegrated_fixture():
    rng = np.random.default_rng(4)
    count = 180
    dates = pd.date_range("2000-01-01", periods=count, freq="MS")
    common_trend = np.cumsum(rng.normal(size=count))
    spread = np.zeros(count)
    for index in range(1, count):
        spread[index] = 0.6 * spread[index - 1] + rng.normal(scale=0.5)
    frame = pd.DataFrame(
        {"date": dates, "first": common_trend, "second": common_trend + spread}
    )
    rank = johansen_cointegration_test(
        frame, "date", ["first", "second"], deterministic="n"
    )
    assert rank["rank"] == 1
    result = analyze_multivariate_time_series(
        frame,
        "date",
        ["first", "second"],
        model_name="VECM",
        forecast_horizon=3,
        deterministic="n",
        cointegration_rank=1,
    )
    assert result["cointegration"]["rank"] == 1
    assert result["forecast"]["values"].keys() == {"first", "second"}
    assert result["fevd"]["error"].startswith("FEVD is provided only")


def test_multivariate_analysis_rejects_missing_duplicate_and_short_data(monthly_data):
    frame = monthly_data.assign(second=np.arange(len(monthly_data), dtype=float))
    missing = frame.copy()
    missing.loc[4, "second"] = np.nan
    with pytest.raises(ValueError, match="missing or non-numeric"):
        analyze_multivariate_time_series(missing, "date", ["output", "second"])
    duplicate = frame.copy()
    duplicate.loc[3, "date"] = duplicate.loc[2, "date"]
    with pytest.raises(ValueError, match="Duplicate timestamps"):
        analyze_multivariate_time_series(duplicate, "date", ["output", "second"])
    with pytest.raises(ValueError, match="requires at least"):
        analyze_multivariate_time_series(
            frame.iloc[:20], "date", ["output", "second"]
        )
