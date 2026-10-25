import pandas as pd
import pytest

from app.database.database import Database
from app.import_workflow import apply_import_mapping, inspect_import, validate_import


def _schema(database):
    project = database.create_project("Import project")
    schema = database.create_questionnaire_schema(project, "Import form")
    database.add_questionnaire_question(schema, "Age", "Age", question_type="integer", data_type="integer", measure="scale", required=True)
    database.add_questionnaire_question(schema, "Sex", "Sex", question_type="single_choice", data_type="text", measure="nominal", options=[{"value": "M"}, {"value": "F"}])
    return database.get_questionnaire_questions(schema)


def test_import_preview_maps_normalized_names_and_keeps_unexpected_columns(tmp_path):
    database = Database(tmp_path / "import.db")
    questions = _schema(database)
    dataframe = pd.DataFrame({"age": [20, 21], "Sex": ["M", "F"], "Notes": ["a", "b"]})
    report = inspect_import(dataframe, questions)
    assert report["mapping"] == {"Age": "age", "Sex": "Sex"}
    assert report["unexpected_columns"] == ["Notes"]
    result = apply_import_mapping(dataframe, questions, report["mapping"])
    assert list(result.columns) == ["Age", "Sex", "Notes"]
    assert result["Age"].tolist() == [20, 21]


def test_import_validation_reports_invalid_values_without_dropping_rows(tmp_path):
    database = Database(tmp_path / "import.db")
    questions = _schema(database)
    dataframe = pd.DataFrame({"Age": [20, "bad", 22], "Sex": ["M", "X", "F"], "Extra": [1, 2, 3]})
    report = validate_import(dataframe, questions, {"Age": "Age", "Sex": "Sex"})
    assert report["row_count"] == 3
    assert report["invalid_row_count"] == 1
    assert report["valid_row_count"] == 2
    assert len(report["errors"]) >= 2
    assert report["missing_counts"]["Extra"] == 0


def test_missing_expected_column_is_explicit(tmp_path):
    database = Database(tmp_path / "import.db")
    questions = _schema(database)
    report = inspect_import(pd.DataFrame({"Age": [20]}), questions)
    assert report["missing_expected"] == ["Sex"]
    with pytest.raises(ValueError):
        apply_import_mapping(pd.DataFrame({"Age": [20]}), questions, {"Age": "missing"})
