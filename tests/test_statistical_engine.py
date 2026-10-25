import pandas as pd
import pytest

from app.statistics.statistical_engine import StatisticalEngine
from app.statistics.statistical_result import StatisticalError, StatisticalResult


def test_result_uses_explicit_unavailable_values_and_stable_schema():
    result = StatisticalResult(
        test="independent_t_test",
        variables=["score", "group"],
        sample_size=12,
    ).to_dict()

    assert result == {
        "test": "independent_t_test",
        "variables": ["score", "group"],
        "sample_size": 12,
        "statistic": None,
        "degrees_of_freedom": None,
        "p_value": None,
        "effect_size": None,
        "confidence_interval": None,
        "assumptions": [],
        "decision": None,
        "interpretation": None,
        "status": "ok",
        "error": None,
        "missing_data": {},
        "warnings": [],
        "details": {},
    }


def test_result_serializes_structured_errors_and_confidence_intervals():
    result = StatisticalResult(
        test="correlation",
        variables=["x", "y"],
        sample_size=8,
        confidence_interval=(0.1, 0.8),
        status="invalid_input",
        error=StatisticalError(
            "VARIABLE_NOT_FOUND",
            "A variable was not found.",
            {"variables": ["y"]},
        ),
    ).to_dict()

    assert result["confidence_interval"] == [0.1, 0.8]
    assert result["error"] == {
        "code": "VARIABLE_NOT_FOUND",
        "message": "A variable was not found.",
        "details": {"variables": ["y"]},
    }


@pytest.mark.parametrize(
    "kwargs",
    [
        {"test": "", "variables": ["x"]},
        {"test": "t_test", "variables": [""]},
        {"test": "t_test", "variables": ["x"], "p_value": 1.1},
        {"test": "t_test", "variables": ["x"], "degrees_of_freedom": 0},
        {
            "test": "t_test",
            "variables": ["x"],
            "confidence_interval": (2.0, 1.0),
        },
        {"test": "t_test", "variables": ["x"], "statistic": float("inf")},
        {"test": "t_test", "variables": ["x"], "status": "invalid_input"},
        {"test": "t_test", "variables": ["x"], "status": "error"},
    ],
)
def test_result_rejects_invalid_fields(kwargs):
    with pytest.raises(ValueError):
        StatisticalResult(**kwargs)


def test_listwise_preparation_reports_missing_and_coerced_values():
    frame = pd.DataFrame({
        "score": [1, "2", None, "bad"],
        "predictor": [10, 20, 30, 40],
    })

    prepared = StatisticalEngine(frame).prepare_numeric_data(
        ["score", "predictor"]
    )

    assert prepared.result.status == "ok"
    assert prepared.data.to_dict("list") == {
        "score": [1.0, 2.0],
        "predictor": [10, 20],
    }
    assert prepared.result.sample_size == 2
    assert prepared.result.missing_data == {"score": 2, "predictor": 0}
    assert prepared.result.details["coerced_to_missing"] == {
        "score": 1,
        "predictor": 0,
    }
    assert prepared.result.details["rows_omitted"] == 2
    assert "listwise deletion" in prepared.result.warnings[0]


def test_raise_policy_returns_structured_missing_data_error():
    frame = pd.DataFrame({"score": [1, None, 3]})

    prepared = StatisticalEngine(frame).prepare_numeric_data(
        ["score"],
        missing_policy="raise",
    )

    assert prepared.result.status == "invalid_input"
    assert prepared.result.error.code == "MISSING_DATA"
    assert prepared.result.missing_data == {"score": 1}
    assert prepared.data.empty


def test_validation_reports_missing_duplicate_and_ambiguous_variables():
    frame = pd.DataFrame([[1, 2]], columns=["score", "score"])
    engine = StatisticalEngine(frame)

    missing = engine.prepare_numeric_data(["unknown"])
    duplicate = engine.prepare_numeric_data(["score", "score"])
    ambiguous = engine.prepare_numeric_data(["score"])

    assert missing.result.error.code == "VARIABLE_NOT_FOUND"
    assert duplicate.result.error.code == "DUPLICATE_VARIABLES"
    assert ambiguous.result.error.code == "AMBIGUOUS_COLUMNS"


def test_invalid_missing_policy_and_empty_data_are_reported():
    frame = pd.DataFrame({"score": pd.Series(dtype="float64")})
    engine = StatisticalEngine(frame)

    bad_policy = engine.prepare_numeric_data(["score"], "pairwise")
    empty = engine.prepare_numeric_data(["score"])
    no_variables = engine.prepare_numeric_data([])

    assert bad_policy.result.error.code == "INVALID_MISSING_POLICY"
    assert empty.result.error.code == "NO_COMPLETE_CASES"
    assert empty.result.sample_size == 0
    assert no_variables.result.error.code == "INVALID_VARIABLES"


def test_boolean_and_datetime_inputs_are_not_treated_as_numeric_measures():
    frame = pd.DataFrame({
        "flag": [True, False],
        "when": pd.to_datetime(["2025-01-01", "2025-01-02"]),
    })
    engine = StatisticalEngine(frame)

    boolean = engine.prepare_numeric_data(["flag"])
    datetime = engine.prepare_numeric_data(["when"])

    assert boolean.result.error.code == "NON_NUMERIC_VARIABLE"
    assert datetime.result.error.code == "NON_NUMERIC_VARIABLE"


def test_fully_nonnumeric_and_infinite_values_have_specific_errors():
    frame = pd.DataFrame({
        "labels": ["low", "high"],
        "measure": [1.0, float("inf")],
    })
    engine = StatisticalEngine(frame)

    nonnumeric = engine.prepare_numeric_data(["labels"])
    infinite = engine.prepare_numeric_data(["measure"])

    assert nonnumeric.result.error.code == "NON_NUMERIC_VARIABLE"
    assert infinite.result.error.code == "NON_FINITE_VALUES"


def test_engine_requires_a_dataframe():
    with pytest.raises(TypeError, match="pandas DataFrame"):
        StatisticalEngine([1, 2, 3])
