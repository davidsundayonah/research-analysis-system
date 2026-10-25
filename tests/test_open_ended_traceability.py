import pytest

from app.database.database import Database


def test_open_ended_response_is_linked_to_real_paper_record(tmp_path):
    database = Database(tmp_path / "qualitative.db")
    project = database.create_project("Mixed study")
    schema = database.create_questionnaire_schema(project, "Form")
    record = database.create_paper_entry_record(project, schema, "R001")
    response = database.create_open_ended_response(project, "R001", "Comments", "Actual participant text", schema, record)
    stored = database.get_open_ended_responses(project)[0]
    assert stored["id"] == response
    assert stored["source_record_id"] == record
    assert stored["response_text"] == "Actual participant text"


def test_open_ended_and_theme_validation_is_project_scoped(tmp_path):
    database = Database(tmp_path / "qualitative.db")
    project = database.create_project("Study")
    other = database.create_project("Other")
    question = database.create_research_question(project, "What did participants report?")
    theme = database.create_qualitative_theme(project, "Access barriers", "Reviewed theme", question, approved=True)
    assert database.get_qualitative_themes(project, approved_only=True)[0]["id"] == theme
    schema = database.create_questionnaire_schema(project, "Form")
    with pytest.raises(ValueError):
        database.create_open_ended_response(other, "R001", "Comments", "Text", schema_id=schema)
    with pytest.raises(ValueError):
        database.create_qualitative_theme(project, "Access barriers")
