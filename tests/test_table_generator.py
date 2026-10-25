import copy

import pandas as pd
import pytest

from app.statistics.statistical_result import StatisticalError, StatisticalResult
from app.statistics.table_generator import TableGenerator, TableNumberingContext


def test_independent_t_table_formats_values_p_and_historical_missing_fields():
    generator = TableGenerator(decimal_places=2)
    result = {
        "test": "independent_t_test",
        "variables": ["score", "group"],
        "sample_size": 20,
        "statistic": 3.456,
        "degrees_of_freedom": 15.5,
        "p_value": 0.0004,
        "confidence_interval": [1.234, 5.678],
        "effect_size": {"cohens_d": 0.8, "hedges_g": 0.76},
        "assumptions": [],
        "decision": "reject_null",
        "details": {
            "group_order": ["Control", "Treatment"],
            "group_sizes": [10, 10],
            "group_means": [4.1, 7.5],
            "equal_variance_assumed": False,
        },
        "warnings": [],
    }
    original = copy.deepcopy(result)

    table = generator.from_result(result)

    assert table.title == "Independent-samples t-test"
    assert table.columns[-6:] == [
        "t", "df", "p", "95% CI", "Cohen's d", "Hedges' g"
    ]
    assert table.rows[0][1] == "Control"
    assert table.rows[0][2] == "10"
    assert table.rows[0][3] == "4.10"
    assert table.rows[0][4] == "Not available"
    assert table.rows[0][9] == "3.46"
    assert table.rows[0][11] == "p < .001"
    assert table.rows[0][12] == "1.23 to 5.68"
    assert "Group SDs were not stored" in " ".join(table.footnotes)
    assert result == original


def test_paired_anova_chi_square_correlation_and_regression_adapters():
    generator = TableGenerator()
    paired = generator.from_result({
        "test": "paired_t_test",
        "variables": ["pre", "post"],
        "sample_size": 8,
        "statistic": 2,
        "degrees_of_freedom": 7,
        "p_value": 0.04,
        "confidence_interval": [0.1, 2.2],
        "effect_size": {"cohens_dz": 0.5, "hedges_gz": 0.45},
        "details": {"mean_difference": 1.1, "standard_deviation_of_differences": 1.5},
    })
    assert paired.rows[0][2:4] == ["1.10", "1.50"]
    assert "Cohen's dz" in paired.columns

    anova = generator.from_result({
        "test": "one_way_anova",
        "variables": ["score", "group"],
        "sample_size": 12,
        "statistic": 4.25,
        "p_value": 0.02,
        "effect_size": {"eta_squared": 0.4, "omega_squared": 0.32},
        "details": {
            "sum_squares_between": 20,
            "degrees_of_freedom_between": 2,
            "mean_square_between": 10,
            "sum_squares_within": 21,
            "degrees_of_freedom_within": 9,
            "mean_square_within": 2.333,
            "sum_squares_total": 41,
            "degrees_of_freedom_total": 11,
        },
    })
    assert anova.rows[0] == ["Between groups", "20.00", "2", "10.00", "4.25", "p = .020"]
    assert anova.rows[-1][1:3] == ["41.00", "11"]

    chi = generator.from_result({
        "test": "chi_square_test",
        "variables": ["sex", "response"],
        "sample_size": 25,
        "statistic": 7.4,
        "degrees_of_freedom": 1,
        "p_value": 0.006,
        "effect_size": {"cramers_v": 0.54},
        "details": {
            "row_categories": ["A", "B"],
            "column_categories": ["Yes", "No"],
            "observed": [[10, 2], [3, 10]],
            "expected": [[6.24, 5.76], [6.76, 6.24]],
        },
    })
    assert chi.rows[0] == ["A", "Yes", "10", "6.24"]
    assert any(row[0] == "Effect size" for row in chi.rows)

    correlation = generator.from_result({
        "test": "spearman_correlation",
        "variables": ["x", "y"],
        "sample_size": 10,
        "statistic": 0.81,
        "p_value": 0.0005,
        "confidence_interval": None,
        "details": {"method": "spearman", "confidence_interval_note": "No CI available."},
    })
    assert correlation.rows[0] == ["x", "y", "10", "0.81", "p < .001", "Not available"]
    assert "No CI available." in " ".join(correlation.footnotes)

    regression = generator.from_result({
        "test": "linear_regression",
        "variables": ["hours", "score"],
        "sample_size": 20,
        "statistic": 12,
        "degrees_of_freedom": 18,
        "p_value": 0.002,
        "confidence_interval": [0.2, 1.2],
        "effect_size": {"r_squared": 0.4, "adjusted_r_squared": 0.37},
        "details": {
            "intercept": 1,
            "slope": 0.7,
            "slope_standard_error": 0.15,
            "slope_test_statistic": 4.67,
            "slope_p_value": 0.002,
            "intercept_standard_error": 0.5,
            "intercept_test_statistic": 2,
            "intercept_p_value": 0.06,
            "intercept_confidence_interval": [-0.1, 2.1],
            "f_statistic": 12,
            "f_degrees_of_freedom": [1, 18],
        },
    })
    assert regression.rows[0] == ["Intercept", "1.00", "0.50", "2.00", "p = .060", "-0.10 to 2.10"]
    assert regression.rows[1] == ["hours", "0.70", "0.15", "4.67", "p = .002", "0.20 to 1.20"]


def test_error_and_unavailable_values_are_explicit():
    result = StatisticalResult(
        test="independent_t_test",
        variables=["score", "group"],
        status="invalid_input",
        error=StatisticalError("INVALID_GROUP_COUNT", "Two groups required."),
    )
    table = TableGenerator().from_result(result)

    assert table.rows == [[
        "score, group",
        "Not available",
        "INVALID_GROUP_COUNT",
        "Two groups required.",
    ]]
    assert table.to_dict()["source"]["test"] == "independent_t_test"


def test_descriptive_and_demographic_adapters_reuse_supplied_values():
    generator = TableGenerator(decimal_places=1)
    descriptive = generator.from_descriptive_summary(pd.DataFrame([
        {"Variable": "age", "N": 4, "Mean": 22.25, "Std. Deviation": 1.5, "Minimum": 20, "Maximum": 24},
    ]), source={"report_id": "r1"})
    frequency = generator.from_frequency_table(pd.DataFrame([
        {"Value": "A", "Frequency": 3, "Percent": 75.0},
        {"Value": "B", "Frequency": 1, "Percent": 25.0},
    ]), variable="gender", source={"report_id": "r1"})

    assert descriptive.rows == [["age", "4", "22.2", "1.5", "20.0", "24.0"]]
    assert frequency.rows == [["A", "3", "75.0%"], ["B", "1", "25.0%"]]
    assert descriptive.source["report_id"] == "r1"
    assert frequency.source["variable"] == "gender"

    report_tables = generator.from_descriptive_report(
        {
            "numeric_summary": pd.DataFrame([
                {"Variable": "age", "N": 4, "Mean": 22.25, "Std. Deviation": 1.5, "Minimum": 20, "Maximum": 24},
            ]),
            "frequency_tables": {
                "gender": pd.DataFrame([
                    {"Value": "A", "Frequency": 3, "Percent": 75.0},
                ]),
            },
        },
        report_id="report-9",
    )
    assert len(report_tables) == 2
    assert report_tables[0].source["section"] == "numeric_summary"
    assert report_tables[1].source["variable"] == "gender"


def test_report_scoped_numbering_is_stable_and_independent():
    generator = TableGenerator()
    numbering = TableNumberingContext("chapter-four")
    result = {
        "test": "pearson_correlation",
        "variables": ["x", "y"],
        "sample_size": 8,
        "statistic": 0.7,
        "p_value": 0.04,
        "details": {"method": "pearson"},
    }
    first = generator.from_result(result, source_key="run-1", numbering=numbering)
    repeated = generator.from_result(result, source_key="run-1", numbering=numbering)
    second = generator.from_result(result, source_key="run-2", numbering=numbering)
    next_report = generator.from_result(
        result,
        source_key="run-1",
        numbering=TableNumberingContext("appendix"),
    )

    assert first.number == repeated.number == 1
    assert second.number == 2
    assert next_report.number == 1
    assert first.numbering_scope_id == "chapter-four"
    assert first.to_dict()["numbering_scope_id"] == "chapter-four"
    assert next_report.numbering_scope_id == "appendix"
    assert first.display_title == "Table 1. Pearson correlation"


def test_saved_run_adapter_preserves_source_traceability_and_never_calls_engine(monkeypatch):
    run = {
        "id": 72,
        "project_id": 3,
        "research_question_id": 4,
        "hypothesis_id": 5,
        "dataset_id": 6,
        "dataset_signature": "fingerprint",
        "actual_test": "pearson_correlation",
        "created_at": "2026-10-11 12:00:00",
        "settings": {"parameters": {"method": "pearson"}},
        "result": {
            "test": "pearson_correlation",
            "variables": ["x", "y"],
            "sample_size": 8,
            "statistic": 0.7,
            "p_value": 0.04,
            "details": {"method": "pearson"},
        },
    }

    def should_not_run(*_args, **_kwargs):
        raise AssertionError("Table generation must not calculate statistics.")

    monkeypatch.setattr("app.statistics.statistical_engine.StatisticalEngine", should_not_run)
    table = TableGenerator().from_saved_run(run)

    assert table.source == {
        "type": "analysis_run",
        "run_id": 72,
        "project_id": 3,
        "question_id": 4,
        "hypothesis_id": 5,
        "dataset_id": 6,
        "dataset_signature": "fingerprint",
        "actual_test": "pearson_correlation",
        "created_at": "2026-10-11 12:00:00",
    }
    assert table.rows[0][3] == "0.70"


def test_future_engine_results_include_table_sufficient_fields():
    from app.statistics.statistical_engine import StatisticalEngine

    t_result = StatisticalEngine(pd.DataFrame({
        "score": [2, 3, 5, 6, 8, 9],
        "group": ["A", "A", "A", "B", "B", "B"],
    })).independent_t_test("score", "group")
    a_result = StatisticalEngine(pd.DataFrame({
        "score": [1, 2, 3, 5, 6, 7, 2, 3, 4],
        "group": ["A"] * 3 + ["B"] * 3 + ["C"] * 3,
    })).one_way_anova("score", "group")
    r_result = StatisticalEngine(pd.DataFrame({
        "x": [1, 2, 3, 4, 5, 6],
        "y": [2, 3, 5, 4, 7, 8],
    })).linear_regression("x", "y")

    assert len(t_result.details["group_standard_deviations"]) == 2
    assert t_result.details["group_standard_deviations"][0] is not None
    assert a_result.details["mean_square_between"] is not None
    assert a_result.details["mean_square_within"] is not None
    assert a_result.details["sum_squares_total"] is not None
    assert r_result.details["intercept_standard_error"] is not None
    assert r_result.details["intercept_p_value"] is not None
    assert r_result.details["slope_test_statistic"] is not None
