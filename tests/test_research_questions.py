import pytest

from app.database.database import Database


@pytest.fixture
def database(tmp_path):
    instance = Database(tmp_path / "research_questions.db")
    yield instance
    instance.close()


def test_research_question_create_read_update_delete(database):
    project_id = database.create_project("Study")

    question_id = database.create_research_question(
        project_id,
        "Does the intervention affect outcomes?",
    )

    created = database.get_research_question(project_id, question_id)
    assert created["question"] == "Does the intervention affect outcomes?"
    assert len(database.get_project_research_questions(project_id)) == 1

    assert database.update_research_question(
        project_id,
        question_id,
        "How does the intervention affect outcomes?",
    )
    assert database.get_research_question(
        project_id,
        question_id,
    )["question"] == "How does the intervention affect outcomes?"

    assert database.delete_research_question(project_id, question_id)
    assert database.get_research_question(project_id, question_id) is None


def test_research_questions_are_isolated_by_project(database):
    first_project_id = database.create_project("First project")
    second_project_id = database.create_project("Second project")
    question_id = database.create_research_question(
        first_project_id,
        "Question owned by first project",
    )

    assert database.get_project_research_questions(second_project_id) == []
    assert database.get_research_question(
        second_project_id,
        question_id,
    ) is None
    assert not database.update_research_question(
        second_project_id,
        question_id,
        "Unauthorized update",
    )
    assert not database.delete_research_question(
        second_project_id,
        question_id,
    )
    assert database.get_research_question(
        first_project_id,
        question_id,
    )["question"] == "Question owned by first project"


def test_question_codes_order_design_and_duplicate_validation(database):
    project_id = database.create_project("Study")
    first_id = database.create_research_question(
        project_id,
        "First question",
        design_type="association",
        proposed_test="Pearson correlation",
    )
    second_id = database.create_research_question(
        project_id,
        "Second question",
        code="CUSTOM-2",
        position=1,
        design_type="comparison",
    )

    questions = database.get_project_research_questions(project_id)
    assert [row["id"] for row in questions] == [second_id, first_id]
    assert [row["code"] for row in questions] == ["CUSTOM-2", "RQ1"]
    assert questions[0]["design_type"] == "comparison"
    assert database.get_research_question(
        project_id,
        first_id,
    )["proposed_test"] == "Pearson correlation"

    with pytest.raises(ValueError, match="cannot be empty"):
        database.create_research_question(project_id, "  ")
    with pytest.raises(ValueError, match="already exists"):
        database.create_research_question(project_id, " first QUESTION ")
    with pytest.raises(ValueError, match="code already exists"):
        database.create_research_question(
            project_id,
            "Third question",
            code="custom-2",
        )

    assert database.update_research_question(
        project_id,
        first_id,
        "First question",
        position=1,
    )
    assert [
        row["id"]
        for row in database.get_project_research_questions(project_id)
    ] == [first_id, second_id]