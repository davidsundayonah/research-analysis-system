import copy

import pytest

from app.statistics.interpretation_engine import (
    InterpretationEngine,
    InterpretationResult,
)


def saved_run(test, result, *, alpha=0.05, hypothesis_id=8, run_id=31):
    return {
        "id": run_id,
        "project_id": 2,
        "research_question_id": 4,
        "hypothesis_id": hypothesis_id,
        "dataset_id": 6,
        "dataset_signature": "saved-fingerprint",
        "actual_test": test,
        "settings": {"parameters": {"alpha": alpha}},
        "result": {"test": test, "status": "ok", **result},
    }


def test_pearson_significance_direction_causality_and_hypothesis_link():
    run = saved_run(
        "pearson_correlation",
        {
            "variables": ["study_hours", "score"],
            "sample_size": 42,
            "statistic": 0.42,
            "p_value": 0.003,
            "effect_size": {"correlation": 0.42},
            "confidence_interval": [0.15, 0.63],
            "details": {"method": "pearson", "alpha": 0.05},
        },
    )

    interpretation = InterpretationEngine().interpret(
        run,
        "More study hours are associated with higher scores.",
    )

    assert isinstance(interpretation, InterpretationResult)
    assert interpretation.source_run_id == 31
    assert interpretation.significance_status == "significant"
    assert interpretation.alpha == 0.05
    assert "statistically significant positive association" in interpretation.finding
    assert "r = .42" in interpretation.finding
    assert "p = .003" in interpretation.finding
    assert "does not, by itself, establish causation" in " ".join(interpretation.caveats)
    assert "More study hours" in interpretation.conclusion
    assert "does not prove the alternative" in interpretation.conclusion


def test_negative_and_non_significant_correlations_are_cautious():
    run = saved_run(
        "spearman_correlation",
        {
            "variables": ["x", "y"],
            "statistic": -0.55,
            "p_value": 0.2,
            "effect_size": {"correlation": -0.55},
            "details": {"method": "spearman", "alpha": 0.05},
        },
    )

    interpretation = InterpretationEngine().interpret(run)

    assert interpretation.significance_status == "not_significant"
    assert "estimated negative association" in interpretation.finding
    assert "not statistically significant" in interpretation.finding
    assert "causation" in " ".join(interpretation.caveats)
    assert "does not prove there is no effect" in interpretation.conclusion


def test_independent_t_test_non_significance_does_not_claim_equivalence():
    run = saved_run(
        "independent_t_test",
        {
            "variables": ["outcome", "group"],
            "statistic": 1.1,
            "p_value": 0.29,
            "effect_size": {"cohens_d": 0.4},
            "confidence_interval": [-0.2, 1.1],
            "details": {
                "group_order": ["Control", "Treatment"],
                "group_means": [3.2, 3.7],
                "alpha": 0.05,
            },
        },
    )

    interpretation = InterpretationEngine().interpret(run)

    assert interpretation.significance_status == "not_significant"
    assert "Control" in interpretation.finding
    assert "Treatment" in interpretation.finding
    assert "not statistically significant" in interpretation.finding
    assert "does not prove there is no effect" in interpretation.conclusion
    assert "equivalent" in interpretation.conclusion


def test_significant_paired_t_test_uses_stored_difference_direction():
    run = saved_run(
        "paired_t_test",
        {
            "variables": ["after", "before"],
            "statistic": 2.7,
            "p_value": 0.02,
            "effect_size": {"cohens_dz": 0.6},
            "details": {"mean_difference": 1.25, "alpha": 0.05},
        },
    )

    interpretation = InterpretationEngine().interpret(run)

    assert interpretation.significance_status == "significant"
    assert "positive mean difference" in interpretation.finding
    assert "1.250" in interpretation.finding
    assert "against the null" in interpretation.conclusion


def test_anova_is_omnibus_and_does_not_claim_pairwise_differences():
    run = saved_run(
        "one_way_anova",
        {
            "variables": ["score", "group"],
            "statistic": 4.2,
            "p_value": 0.02,
            "effect_size": {"eta_squared": 0.3},
            "details": {"group_order": ["A", "B", "C"], "alpha": 0.05},
        },
    )

    interpretation = InterpretationEngine().interpret(run)

    assert interpretation.significance_status == "significant"
    assert "at least one group mean differed across 3 groups" in interpretation.finding
    assert "omnibus" in " ".join(interpretation.caveats)
    assert "Post-hoc" in " ".join(interpretation.caveats)


def test_chi_square_interprets_association_without_causal_language():
    run = saved_run(
        "chi_square_test",
        {
            "variables": ["region", "response"],
            "statistic": 8.8,
            "degrees_of_freedom": 2,
            "p_value": 0.012,
            "effect_size": {"cramers_v": 0.4},
            "details": {"alpha": 0.05},
        },
    )

    interpretation = InterpretationEngine().interpret(run)

    assert "association between region and response" in interpretation.finding
    assert "statistically significant" in interpretation.finding
    assert "α = .050" in interpretation.finding
    assert "does not, by itself, establish causation" in " ".join(interpretation.caveats)


def test_regression_describes_model_fit_and_individual_coefficient():
    run = saved_run(
        "linear_regression",
        {
            "variables": ["hours", "score"],
            "statistic": 10.1,
            "p_value": 0.004,
            "effect_size": {"r_squared": 0.35, "adjusted_r_squared": 0.32},
            "confidence_interval": [0.2, 0.8],
            "details": {
                "slope": 0.5,
                "slope_p_value": 0.006,
                "slope_confidence_interval": [0.2, 0.8],
                "alpha": 0.05,
            },
        },
    )

    interpretation = InterpretationEngine().interpret(run)

    assert "overall model was statistically significant" in interpretation.finding
    assert "35.0%" in interpretation.finding
    assert "coefficient for hours was 0.500" in interpretation.finding
    assert "individual p = .006" in interpretation.finding
    assert any("do not, by themselves, establish causation" in caveat for caveat in interpretation.caveats)


def test_saved_alpha_is_authoritative_and_missing_alpha_is_unavailable():
    result = {
        "variables": ["x", "y"],
        "statistic": 0.4,
        "p_value": 0.04,
        "effect_size": {"correlation": 0.4},
        "details": {"alpha": 0.01},
    }
    run = saved_run("pearson_correlation", result, alpha=0.01)
    significant_at_project_default = InterpretationEngine().interpret(run)
    del run["settings"]["parameters"]["alpha"]
    del run["result"]["details"]["alpha"]
    missing_alpha = InterpretationEngine().interpret(run)

    assert significant_at_project_default.significance_status == "not_significant"
    assert significant_at_project_default.alpha == 0.01
    assert missing_alpha.significance_status == "unavailable"
    assert "alpha" in missing_alpha.unavailable_fields
    assert "could not be classified" in missing_alpha.finding


def test_missing_statistics_are_reported_without_inventing_values():
    run = saved_run(
        "independent_t_test",
        {"variables": ["score", "group"], "details": {}},
    )
    original = copy.deepcopy(run)

    interpretation = InterpretationEngine().interpret(run)

    assert interpretation.significance_status == "unavailable"
    assert "direction of the group mean difference is unavailable" in interpretation.finding
    assert "p_value" in interpretation.unavailable_fields
    assert "alpha" not in interpretation.unavailable_fields
    assert "cannot be determined" in interpretation.conclusion
    assert run == original


def test_missing_regression_coefficients_and_result_errors_are_explicit():
    regression = saved_run(
        "linear_regression",
        {"variables": ["x", "y"], "p_value": 0.2, "details": {"alpha": 0.05}},
    )
    unavailable = InterpretationEngine().interpret(regression)
    failed_run = saved_run(
        "linear_regression",
        {
            "status": "invalid_input",
            "error": {"code": "CONSTANT_PREDICTOR", "message": "Predictor is constant."},
        },
    )
    failed = InterpretationEngine().interpret(failed_run)

    assert "coefficient information is unavailable" in unavailable.finding
    assert "r_squared" in unavailable.unavailable_fields
    assert "slope" in unavailable.unavailable_fields
    assert "CONSTANT_PREDICTOR" in failed.caveats[0] or "Predictor is constant" in failed.caveats[0]
    assert failed.significance_status == "unavailable"


def test_unsupported_test_returns_safe_unavailable_interpretation():
    run = saved_run("future_test", {"variables": ["x"], "p_value": 0.001})

    interpretation = InterpretationEngine().interpret(run)

    assert "No interpretation rule" in interpretation.finding
    assert "test-specific interpretation" in interpretation.unavailable_fields
    assert "no supported rule" in " ".join(interpretation.caveats)
