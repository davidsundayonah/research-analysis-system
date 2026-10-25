import math

import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.api import OLS, add_constant

from app.statistics.statistical_engine import StatisticalEngine


def test_descriptive_reference_values_are_independent_of_engine():
    frame = pd.DataFrame({"value": [1.0, 2.0, 2.0, 4.0, np.nan]})
    values = frame["value"].dropna().to_numpy()
    summary = frame["value"].describe()

    # Expected values are calculated directly from pandas' documented sample
    # statistics, not by calling the application descriptive implementation.
    assert len(values) == 4
    assert values.size == summary["count"]
    assert values.mean() == summary["mean"]
    assert np.median(values) == 2.0
    assert values.std(ddof=1) == summary["std"]
    assert values.min() == summary["min"]
    assert values.max() == summary["max"]

    result = StatisticalEngine(frame)
    # The inference engine independently verifies that missing data is tracked.
    prepared = result.prepare_numeric_data(["value"])
    assert prepared.result.missing_data["value"] == 1
    assert prepared.result.sample_size == 4


def test_pearson_matches_scipy_reference():
    frame = pd.DataFrame({"x": [1, 2, 3, 4, 5, 7], "y": [2, 1, 5, 4, 8, 9]})
    expected = stats.pearsonr(frame["x"], frame["y"])
    result = StatisticalEngine(frame).correlation("x", "y")

    assert result.status == "ok"
    assert result.sample_size == len(frame)
    assert math.isclose(result.statistic, expected.statistic, rel_tol=1e-12)
    assert math.isclose(result.p_value, expected.pvalue, rel_tol=1e-12)
    assert result.confidence_interval is not None
    reference_ci = expected.confidence_interval(confidence_level=0.95)
    assert np.allclose(result.confidence_interval, [reference_ci.low, reference_ci.high], atol=1e-12)


def test_pearson_warning_distinguishes_failed_from_unavailable_normality():
    frame = pd.read_csv("test_research_data.csv")
    result = StatisticalEngine(frame).correlation("SM_Hours", "GPA")

    assert any("indicated a departure from normality" in warning for warning in result.warnings)
    assert not any("were not supported" in warning for warning in result.warnings)


def test_regression_matches_statsmodels_reference():
    frame = pd.DataFrame({"x": [1, 2, 3, 4, 5, 7], "y": [2, 1, 5, 4, 8, 9]})
    expected = OLS(frame["y"], add_constant(frame["x"])).fit()
    result = StatisticalEngine(frame).linear_regression("x", "y")

    assert result.status == "ok"
    assert math.isclose(result.details["intercept"], expected.params["const"], rel_tol=1e-12)
    assert math.isclose(result.details["slope"], expected.params["x"], rel_tol=1e-12)
    assert math.isclose(result.details["slope_standard_error"], expected.bse["x"], rel_tol=1e-12)
    assert math.isclose(result.details["slope_test_statistic"], expected.tvalues["x"], rel_tol=1e-12)
    assert math.isclose(result.details["slope_p_value"], expected.pvalues["x"], rel_tol=1e-12)
    assert math.isclose(result.effect_size["r_squared"], expected.rsquared, rel_tol=1e-12)
    assert math.isclose(result.effect_size["adjusted_r_squared"], expected.rsquared_adj, rel_tol=1e-12)
    assert math.isclose(result.details["f_statistic"], expected.fvalue, rel_tol=1e-12)
    assert result.details["f_degrees_of_freedom"] == [expected.df_model, expected.df_resid]
    assert np.allclose(result.confidence_interval, expected.conf_int(alpha=0.05).loc["x"], atol=1e-12)


def test_t_tests_and_effect_sizes_match_scipy_and_manual_reference():
    frame = pd.DataFrame({
        "outcome": [10.0, 11.0, 12.0, 20.0, 22.0, 21.0, 23.0],
        "group": ["A", "A", "A", "B", "B", "B", "B"],
    })
    first = frame.loc[frame.group == "A", "outcome"].to_numpy()
    second = frame.loc[frame.group == "B", "outcome"].to_numpy()
    result = StatisticalEngine(frame).independent_t_test("outcome", "group", equal_var=False)
    expected = stats.ttest_ind(first, second, equal_var=False)
    assert math.isclose(result.statistic, expected.statistic, rel_tol=1e-12)
    assert math.isclose(result.p_value, expected.pvalue, rel_tol=1e-12)
    assert result.details["test_method"] == "welch"
    assert result.details["group_order"] == ["A", "B"]
    expected_df = (first.var(ddof=1) / len(first) + second.var(ddof=1) / len(second)) ** 2 / (
        (first.var(ddof=1) / len(first)) ** 2 / (len(first) - 1)
        + (second.var(ddof=1) / len(second)) ** 2 / (len(second) - 1)
    )
    assert math.isclose(result.degrees_of_freedom, expected_df, rel_tol=1e-12)

    pooled_variance = ((len(first) - 1) * first.var(ddof=1) + (len(second) - 1) * second.var(ddof=1)) / (len(frame) - 2)
    expected_d = (first.mean() - second.mean()) / math.sqrt(pooled_variance)
    assert math.isclose(result.effect_size["cohens_d"], expected_d, rel_tol=1e-12)
    assert result.effect_size["hedges_g"] is not None


def test_gender_codes_are_reported_with_readable_group_names():
    frame = pd.DataFrame({
        "GPA": [3.0, 3.2, 3.4, 3.6, 3.8, 4.0, 4.1, 4.3, 4.5, 4.7, 4.9, 5.0],
        "Gender": [1, 1, 1, 1, 1, 1, 2, 2, 2, 2, 2, 2],
    })
    result = StatisticalEngine(frame).independent_t_test("GPA", "Gender")
    assert result.status == "ok"
    assert result.details["group_order"] == ["Male", "Female"]


def test_invalid_constant_and_duplicate_inputs_are_rejected_without_silent_deletion():
    frame = pd.DataFrame({"x": [1, 1, 1], "y": [2, 3, 4], "id": [1, 1, 2]})
    engine = StatisticalEngine(frame)
    assert engine.correlation("x", "y").error.code == "CONSTANT_VARIABLE"
    assert engine.linear_regression("x", "y").error.code == "CONSTANT_PREDICTOR"
    assert engine.correlation("x", "x").error.code == "DUPLICATE_VARIABLES"
    assert frame.duplicated().sum() == 0
    assert frame["id"].duplicated().sum() == 1
