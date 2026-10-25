import pandas as pd

from app.database.database import Database
from app.questionnaire import generate_blank_template, safe_variable_name


def test_questionnaire_schema_and_paper_entry_are_project_scoped(tmp_path):
    database = Database(tmp_path / "research.db")
    project_id = database.create_project("Paper study")
    other_project = database.create_project("Other study")
    schema_id = database.create_questionnaire_schema(project_id, "Paper form", expected_sample_size=200)
    database.add_questionnaire_question(
        schema_id, "What is your age?", "Age", question_type="integer", data_type="integer", measure="scale", required=True
    )
    database.add_questionnaire_question(
        schema_id, "Select your sex", "Sex", question_type="single_choice", data_type="text", measure="nominal",
        options=[{"value": "M", "label": "Male"}, {"value": "F", "label": "Female"}],
    )
    database.add_questionnaire_question(
        schema_id, "Additional comments", "Comments", question_type="long_text", data_type="text", measure="text"
    )
    database.approve_questionnaire_schema(schema_id)
    record_id = database.create_paper_entry_record(project_id, schema_id, "R001")
    result = database.save_paper_entry_record(record_id, {"Age": "21", "Sex": "F", "Comments": "Actual answer"})
    assert result["status"] == "complete"
    assert result["valid"] is True
    assert database.get_paper_entry_progress(schema_id) == {
        "expected": 200, "entered": 1, "complete": 1, "incomplete": 0, "valid": 1, "invalid": 0
    }
    try:
        database.create_paper_entry_record(other_project, schema_id, "R002")
    except ValueError as error:
        assert "project" in str(error).lower()
    else:
        raise AssertionError("A questionnaire must not be usable by another project")


def test_invalid_codes_are_retained_as_reviewable_errors(tmp_path):
    database = Database(tmp_path / "research.db")
    project_id = database.create_project("Validation study")
    schema_id = database.create_questionnaire_schema(project_id, "Form")
    database.add_questionnaire_question(
        schema_id, "Agreement", "Agree", question_type="likert", data_type="integer", measure="ordinal",
        options=[{"value": 1, "label": "No"}, {"value": 2, "label": "Yes"}],
    )
    record_id = database.create_paper_entry_record(project_id, schema_id, "R001")
    result = database.save_paper_entry_record(record_id, {"Agree": 9})
    assert result["valid"] is False
    assert "Agree" in result["errors"][0]
    assert database.get_paper_entry_records(schema_id)[0]["status"] == "invalid"


def test_blank_xlsx_template_has_responses_and_codebook_sheets(tmp_path):
    database = Database(tmp_path / "research.db")
    project_id = database.create_project("Template study")
    schema_id = database.create_questionnaire_schema(project_id, "Template", expected_sample_size=3)
    database.add_questionnaire_question(
        schema_id, "Name", "Name", question_type="short_text", data_type="text", measure="text"
    )
    questions = database.get_questionnaire_questions(schema_id)
    output = generate_blank_template(questions, tmp_path / "template.xlsx", expected_sample_size=3)
    sheets = pd.ExcelFile(output).sheet_names
    response_frame = pd.read_excel(output, sheet_name="Responses")
    from openpyxl import load_workbook
    workbook = load_workbook(output)
    assert sheets == ["Responses", "Codebook"]
    assert list(response_frame.columns) == ["Respondent_ID", "Name"]
    assert workbook["Responses"].max_row == 4
    assert response_frame.empty


def test_safe_variable_name_is_deterministic_and_collision_safe():
    assert safe_variable_name("Age range") == "Age_range"
    assert safe_variable_name("Age range", {"Age_range"}) == "Age_range_2"
