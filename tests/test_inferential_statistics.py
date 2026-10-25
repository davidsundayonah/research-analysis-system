import numpy as np
import pandas as pd
import pytest
from scipy import stats
from scipy.special import gammaln

from app.statistics.statistical_engine import StatisticalEngine


def assert_close(actual, expected, *, rel=1e-10, abs_=1e-12):
    assert actual == pytest.approx(expected, rel=rel, abs=abs_)


def test_independent_t_test_matches_scipy_welch_and_independent_ci_formula():
    first = np.array([4.0, 5.0, 7.0, 8.0, 9.0])
    second = np.array([1.0, 2.0, 4.0, 5.0])
    frame = pd.DataFrame({
        "score": np.r_[first, second],
        "group": ["A"] * len(first) + ["B"] * len(second),
    })

    result = StatisticalEngine(frame).independent_t_test("score", "group")
    reference = stats.ttest_ind(first, second, equal_var=False)
    v1, v2 = first.var(ddof=1), second.var(ddof=1)
    term1, term2 = v1 / len(first), v2 / len(second)
    degrees = (term1 + term2) ** 2 / (
        term1**2 / (len(first) - 1) + term2**2 / (len(second) - 1)
    )
    difference = first.mean() - second.mean()
    standard_error = np.sqrt(term1 + term2)
    critical = stats.t.ppf(0.975, degrees)

    assert result.status == "ok"
    assert_close(result.statistic, reference.statistic)
    assert_close(result.p_value, reference.pvalue)
    assert_close(result.degrees_of_freedom, degrees)
    assert result.confidence_interval == pytest.approx((
        difference - critical * standard_error,
        difference + critical * standard_error,
    ))
    assert result.effect_size["cohens_d"] is not None
    pooled_sd = np.sqrt(
        ((len(first) - 1) * v1 + (len(second) - 1) * v2)
        / (len(first) + len(second) - 2)
    )
    expected_d = difference / pooled_sd
    pooled_degrees = len(first) + len(second) - 2
    correction = np.exp(
        gammaln(pooled_degrees / 2)
        - 0.5 * np.log(pooled_degrees / 2)
        - gammaln((pooled_degrees - 1) / 2)
    )
    assert_close(result.effect_size["cohens_d"], expected_d)
    assert_close(result.effect_size["hedges_g"], expected_d * correction)
    assert "pooled within-group" in result.details["effect_size_convention"]
    assert result.details["test_method"] == "welch"
    assert result.to_dict()["test"] == "independent_t_test"


def test_equal_variance_independent_t_test_matches_pooled_scipy():
    frame = pd.DataFrame({
        "score": [2, 4, 6, 7, 8, 10],
        "group": ["left"] * 3 + ["right"] * 3,
    })
    result = StatisticalEngine(frame).independent_t_test(
        "score", "group", equal_var=True
    )
    expected = stats.ttest_ind([2, 4, 6], [7, 8, 10], equal_var=True)

    assert result.status == "ok"
    assert_close(result.statistic, expected.statistic)
    assert_close(result.p_value, expected.pvalue)
    assert result.degrees_of_freedom == 4


def test_t_test_handles_one_constant_group_and_rejects_two_constant_groups():
    one_constant = pd.DataFrame({
        "score": [2, 2, 2, 5, 7, 9],
        "group": ["constant"] * 3 + ["variable"] * 3,
    })
    two_constant = pd.DataFrame({
        "score": [2, 2, 2, 9, 9, 9],
        "group": ["A"] * 3 + ["B"] * 3,
    })

    valid = StatisticalEngine(one_constant).independent_t_test("score", "group")
    invalid = StatisticalEngine(two_constant).independent_t_test("score", "group")

    assert valid.status == "ok"
    assert np.isfinite(valid.statistic)
    assert valid.confidence_interval[0] < valid.confidence_interval[1]
    assert invalid.error.code == "ZERO_VARIANCE"


def test_paired_t_test_matches_scipy_and_difference_effect_size():
    before = np.array([10.0, 12.0, 9.0, 15.0, 11.0, 14.0])
    after = np.array([12.0, 13.0, 11.0, 14.0, 15.0, 17.0])
    frame = pd.DataFrame({"before": before, "after": after})

    result = StatisticalEngine(frame).paired_t_test("before", "after")
    reference = stats.ttest_rel(before, after)
    differences = before - after
    expected_dz = differences.mean() / differences.std(ddof=1)

    assert result.status == "ok"
    assert_close(result.statistic, reference.statistic)
    assert_close(result.p_value, reference.pvalue)
    assert result.degrees_of_freedom == len(before) - 1
    assert_close(result.effect_size["cohens_dz"], expected_dz)
    correction = np.exp(
        gammaln((len(before) - 1) / 2)
        - 0.5 * np.log((len(before) - 1) / 2)
        - gammaln((len(before) - 2) / 2)
    )
    assert_close(result.effect_size["hedges_gz"], expected_dz * correction)
    assert "Cohen's dz" in result.details["effect_size_convention"]

def test_one_way_anova_matches_scipy_and_effect_sizes():
    groups = [
        np.array([4.0, 5.0, 6.0, 5.0]),
        np.array([7.0, 8.0, 9.0, 8.0]),
        np.array([3.0, 4.0, 5.0, 4.0]),
    ]
    frame = pd.DataFrame({
        "score": np.concatenate(groups),
        "group": sum(([f"G{i}"] * len(values) for i, values in enumerate(groups)), []),
    })

    result = StatisticalEngine(frame).one_way_anova("score", "group")
    reference = stats.f_oneway(*groups)
    grand_mean = np.concatenate(groups).mean()
    ss_between = sum(len(group) * (group.mean() - grand_mean) ** 2 for group in groups)
    ss_within = sum(((group - group.mean()) ** 2).sum() for group in groups)
    eta_squared = ss_between / (ss_between + ss_within)

    assert result.status == "ok"
    assert_close(result.statistic, reference.statistic)
    assert_close(result.p_value, reference.pvalue)
    assert result.details["degrees_of_freedom_between"] == 2
    assert result.details["degrees_of_freedom_within"] == 9
    assert_close(result.effect_size["eta_squared"], eta_squared)
    assert result.assumptions[0]["name"] == "normality"
    assert result.assumptions[1]["name"] == "equal_variances"


def test_two_group_anova_matches_equal_variance_t_test_and_clamps_omega_squared():
    values_a = np.array([0.0, 1.0, 0.0, 1.0])
    values_b = np.array([0.0, 1.0, 0.0, 1.1])
    frame = pd.DataFrame({
        "score": np.r_[values_a, values_b],
        "group": ["A"] * 4 + ["B"] * 4,
    })

    engine = StatisticalEngine(frame)
    anova = engine.one_way_anova("score", "group")
    t_test = engine.independent_t_test("score", "group", equal_var=True)

    assert anova.status == "ok"
    assert_close(anova.statistic, t_test.statistic**2)
    assert anova.effect_size["omega_squared"] >= 0
    assert anova.details["degrees_of_freedom_between"] == 1


def test_anova_flags_unequal_variances_and_rejects_undefined_variance():
    unequal = pd.DataFrame({
        "score": [0, 1, -1, 2, 3, -3, 10, -10, 20, -20, 30, -30],
        "group": ["A"] * 4 + ["B"] * 4 + ["C"] * 4,
    })
    undefined = pd.DataFrame({
        "score": [1, 1, 1, 2, 2, 2],
        "group": ["A"] * 3 + ["B"] * 3,
    })

    result = StatisticalEngine(unequal).one_way_anova("score", "group")
    invalid = StatisticalEngine(undefined).one_way_anova("score", "group")

    assert result.status == "ok"
    assert result.assumptions[1]["passed"] is False
    assert any("Equal-variance" in warning for warning in result.warnings)
    assert invalid.error.code == "ZERO_WITHIN_GROUP_VARIANCE"


def test_chi_square_matches_scipy_and_reports_expected_count_assumption():
    observed = np.array([[20, 10, 5], [10, 15, 20]])
    rows = []
    for row_index, label in enumerate(["A", "B"]):
        for column_index, category in enumerate(["X", "Y", "Z"]):
            rows.extend([(label, category)] * observed[row_index, column_index])
    frame = pd.DataFrame(rows, columns=["group", "response"])

    result = StatisticalEngine(frame).chi_square_test("group", "response")
    reference = stats.chi2_contingency(observed, correction=False)
    expected_v = np.sqrt(reference.statistic / observed.sum())

    assert result.status == "ok"
    assert_close(result.statistic, reference.statistic)
    assert_close(result.p_value, reference.pvalue)
    assert result.degrees_of_freedom == reference.dof
    assert_close(result.effect_size["cramers_v"], expected_v)
    assert result.assumptions[0]["passed"] is True


def test_chi_square_warns_for_sparse_expected_cells():
    frame = pd.DataFrame({
        "group": ["A"] * 9 + ["B"] * 9,
        "category": ["common"] * 8 + ["rare"] + ["common"] * 4 + ["rare"] * 5,
    })

    result = StatisticalEngine(frame).chi_square_test("group", "category")

    assert result.status == "ok"
    assert result.assumptions[0]["passed"] is False
    assert any("below 5" in warning for warning in result.warnings)


def test_chi_square_zero_observed_cells_are_valid_but_zero_margins_are_invalid():
    complete_separation = pd.DataFrame({
        "row": ["A"] * 10 + ["B"] * 10,
        "column": ["X"] * 10 + ["Y"] * 10,
    })
    zero_margin = pd.DataFrame({
        "row": ["A"] * 5,
        "column": ["X"] * 5,
    })

    valid = StatisticalEngine(complete_separation).chi_square_test("row", "column")
    invalid = StatisticalEngine(zero_margin).chi_square_test("row", "column")

    assert valid.status == "ok"
    assert valid.details["observed"] == [[10, 0], [0, 10]]
    assert invalid.error.code == "INSUFFICIENT_CATEGORIES"


def test_pearson_and_spearman_correlations_match_scipy():
    x = np.array([1.0, 2.0, 3.0, 4.0, 6.0, 8.0, 9.0])
    y = np.array([1.0, 3.0, 2.0, 7.0, 5.0, 9.0, 8.0])
    engine = StatisticalEngine(pd.DataFrame({"x": x, "y": y}))

    pearson = engine.correlation("x", "y")
    pearson_reference = stats.pearsonr(x, y)
    spearman = engine.correlation("x", "y", method="spearman")
    spearman_reference = stats.spearmanr(x, y)

    assert_close(pearson.statistic, pearson_reference.statistic)
    assert_close(pearson.p_value, pearson_reference.pvalue)
    assert pearson.confidence_interval is not None
    assert_close(spearman.statistic, spearman_reference.statistic)
    assert_close(spearman.p_value, spearman_reference.pvalue)
    assert spearman.confidence_interval is None
    assert any("confidence interval is not provided" in item for item in spearman.warnings)


def test_correlation_perfect_association_has_unavailable_pearson_interval():
    frame = pd.DataFrame({
        "x": [1, 2, 3, 4, 5],
        "positive": [2, 4, 6, 8, 10],
        "negative": [10, 8, 6, 4, 2],
    })
    engine = StatisticalEngine(frame)

    positive = engine.correlation("x", "positive")
    negative = engine.correlation("x", "negative")
    tiny = StatisticalEngine(pd.DataFrame({"x": [1, 2], "y": [2, 3]})).correlation(
        "x", "y"
    )

    assert positive.statistic == pytest.approx(1)
    assert positive.confidence_interval is None
    assert any("perfect" in warning.lower() for warning in positive.warnings)
    assert negative.statistic == pytest.approx(-1)
    assert negative.confidence_interval is None
    assert tiny.error.code == "INSUFFICIENT_SAMPLE_SIZE"


def test_simple_regression_matches_closed_form_and_scipy_reference():
    x = np.array([1.0, 2.0, 4.0, 5.0, 7.0, 8.0, 9.0])
    y = np.array([2.2, 2.9, 5.1, 6.2, 7.0, 9.5, 10.1])
    result = StatisticalEngine(pd.DataFrame({"x": x, "y": y})).linear_regression(
        "x", "y"
    )
    reference = stats.linregress(x, y)
    slope = np.sum((x - x.mean()) * (y - y.mean())) / np.sum((x - x.mean()) ** 2)
    intercept = y.mean() - slope * x.mean()
    residuals = y - (intercept + slope * x)
    residual_variance = np.sum(residuals**2) / (len(x) - 2)
    slope_se = np.sqrt(residual_variance / np.sum((x - x.mean()) ** 2))
    critical = stats.t.ppf(0.975, len(x) - 2)

    assert result.status == "ok"
    assert_close(result.details["slope"], reference.slope)
    assert_close(result.details["intercept"], reference.intercept)
    assert_close(result.details["slope_p_value"], reference.pvalue)
    assert_close(result.effect_size["r_squared"], reference.rvalue**2)
    assert result.confidence_interval == pytest.approx((
        slope - critical * slope_se,
        slope + critical * slope_se,
    ))
    assert result.details["durbin_watson"] >= 0
    assert any(assumption["name"] == "constant_variance" for assumption in result.assumptions)


def test_regression_flags_autocorrelation_and_heteroscedasticity():
    rng = np.random.default_rng(812)
    x = np.linspace(1, 20, 120)
    innovations = rng.normal(0, 1, len(x))
    residuals = np.zeros(len(x))
    for index in range(1, len(x)):
        residuals[index] = 0.9 * residuals[index - 1] + innovations[index]
    autocorrelated = StatisticalEngine(
        pd.DataFrame({"x": x, "y": 3 * x + residuals})
    ).linear_regression("x", "y")

    hetero_error = rng.normal(0, x, len(x))
    heteroscedastic = StatisticalEngine(
        pd.DataFrame({"x": x, "y": 2 * x + hetero_error})
    ).linear_regression("x", "y")

    assert autocorrelated.details["durbin_watson"] < 1.5
    assert any("autocorrelation" in warning.lower() for warning in autocorrelated.warnings)
    variance_check = next(
        check for check in heteroscedastic.assumptions
        if check["name"] == "constant_variance"
    )
    assert variance_check["passed"] is False
    assert any("heteroscedasticity" in warning.lower() for warning in heteroscedastic.warnings)


def test_regression_handles_singular_and_insufficient_designs():
    constant_predictor = StatisticalEngine(
        pd.DataFrame({"x": [1, 1, 1, 1], "y": [2, 3, 5, 8]})
    ).linear_regression("x", "y")
    too_small = StatisticalEngine(
        pd.DataFrame({"x": [1, 2], "y": [2, 4]})
    ).linear_regression("x", "y")
    limited_residuals = StatisticalEngine(
        pd.DataFrame({"x": [1, 2, 3, 4], "y": [1, 4, 2, 5]})
    ).linear_regression("x", "y")

    assert constant_predictor.error.code == "CONSTANT_PREDICTOR"
    assert too_small.error.code == "INSUFFICIENT_SAMPLE_SIZE"
    normality = limited_residuals.assumptions[0]
    assert normality["passed"] is None
    assert "fewer than 3 residual" in normality["details"]["reason"]


def test_inferential_methods_report_missing_and_input_edge_cases():
    frame = pd.DataFrame({
        "score": [1.0, 2.0, None, 4.0, 5.0, 7.0],
        "other": [1.0, 3.0, 2.0, 4.0, 6.0, 9.0],
        "group": ["A", "B", "B", "B", "B", "B"],
        "constant": [1, 1, 1, 1, 1, 1],
    })
    engine = StatisticalEngine(frame)

    omitted = engine.paired_t_test("score", "other")
    rejected = engine.correlation("score", "other", missing_policy="raise")
    missing_variable = engine.linear_regression("not_here", "score")
    constant = engine.correlation("constant", "other")
    too_few_groups = engine.independent_t_test("score", "group")
    invalid_alpha = engine.one_way_anova("score", "group", alpha=1.0)
    invalid_variable = engine.correlation(None, "other")

    assert omitted.status == "ok"
    assert omitted.sample_size == 5
    assert omitted.missing_data["score"] == 1
    assert rejected.error.code == "MISSING_DATA"
    assert missing_variable.error.code == "VARIABLE_NOT_FOUND"
    assert constant.error.code == "CONSTANT_VARIABLE"
    assert too_few_groups.error.code == "INSUFFICIENT_GROUP_SIZE"
    assert invalid_alpha.error.code == "INVALID_ALPHA"
    assert invalid_variable.error.code == "INVALID_VARIABLES"


def test_strict_missing_policy_applies_to_group_and_categorical_variables():
    frame = pd.DataFrame({
        "score": [1, 2, 3, 4, 5, 6],
        "group": ["A", "A", "B", "B", None, "B"],
        "category": ["X", "Y", "X", "Y", "X", None],
    })
    engine = StatisticalEngine(frame)

    t_test = engine.independent_t_test(
        "score", "group", missing_policy="raise"
    )
    anova = engine.one_way_anova("score", "group", missing_policy="raise")
    chi_square = engine.chi_square_test(
        "group", "category", missing_policy="raise"
    )
    dropped = engine.chi_square_test("group", "category")

    assert t_test.error.code == "MISSING_DATA"
    assert anova.error.code == "MISSING_DATA"
    assert chi_square.error.code == "MISSING_DATA"
    assert any("listwise deletion" in warning for warning in dropped.warnings)


def test_inferential_results_can_all_be_serialized():
    frame = pd.DataFrame({
        "score": [2, 3, 4, 5, 7, 8],
        "paired": [1, 2, 1, 4, 3, 5],
        "group": ["A", "A", "A", "B", "B", "B"],
        "category": ["X", "Y", "X", "Y", "X", "Y"],
    })
    engine = StatisticalEngine(frame)
    results = [
        engine.independent_t_test("score", "group"),
        engine.paired_t_test("score", "paired"),
        engine.one_way_anova("score", "group"),
        engine.chi_square_test("group", "category"),
        engine.correlation("score", "paired"),
        engine.correlation("score", "paired", method="spearman"),
        engine.linear_regression("paired", "score"),
    ]

    assert all(isinstance(result.to_dict(), dict) for result in results)
    assert all(result.to_dict()["status"] == "ok" for result in results)
