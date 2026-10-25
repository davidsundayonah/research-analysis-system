import pytest

from app.database.database import Database


@pytest.fixture
def database(tmp_path):
    instance = Database(tmp_path / "hypotheses.db")
    yield instance
    instance.close()


def test_hypothesis_create_read_update_delete(database):
    project_id = database.create_project("Study")
    question_id = database.create_research_question(
        project_id,
        "Does the intervention affect outcomes?",
    )

    hypothesis_id = database.create_hypothesis(
        project_id,
        question_id,
        "The intervention improves outcomes.",
    )

    created = database.get_hypothesis(
        project_id,
        question_id,
        hypothesis_id,
    )
    assert created["research_question_id"] == question_id
    assert created["hypothesis"] == "The intervention improves outcomes."
    assert len(database.get_research_question_hypotheses(
        project_id,
        question_id,
    )) == 1

    assert database.update_hypothesis(
        project_id,
        question_id,
        hypothesis_id,
        "The intervention has a positive effect.",
    )
    assert database.get_hypothesis(
        project_id,
        question_id,
        hypothesis_id,
    )["hypothesis"] == "The intervention has a positive effect."

    assert database.delete_hypothesis(
        project_id,
        question_id,
        hypothesis_id,
    )
    assert database.get_hypothesis(
        project_id,
        question_id,
        hypothesis_id,
    ) is None


def test_hypothesis_operations_are_scoped_to_owning_project_and_question(
    database,
):
    first_project_id = database.create_project("First project")
    second_project_id = database.create_project("Second project")
    first_question_id = database.create_research_question(
        first_project_id,
        "First question",
    )
    second_question_id = database.create_research_question(
        second_project_id,
        "Second question",
    )
    hypothesis_id = database.create_hypothesis(
        first_project_id,
        first_question_id,
        "First hypothesis",
    )

    with pytest.raises(ValueError):
        database.create_hypothesis(
            second_project_id,
            first_question_id,
            "Wrong project",
        )

    assert database.get_research_question_hypotheses(
        second_project_id,
        second_question_id,
    ) == []
    assert database.get_hypothesis(
        second_project_id,
        first_question_id,
        hypothesis_id,
    ) is None
    assert not database.update_hypothesis(
        second_project_id,
        first_question_id,
        hypothesis_id,
        "Unauthorized edit",
    )
    assert not database.delete_hypothesis(
        second_project_id,
        first_question_id,
        hypothesis_id,
    )


def test_deleting_research_question_cascades_to_its_hypotheses(database):
    project_id = database.create_project("Study")
    question_id = database.create_research_question(
        project_id,
        "Study question",
    )
    database.create_hypothesis(project_id, question_id, "Study hypothesis")

    assert database.delete_research_question(project_id, question_id)
    assert database.get_research_question_hypotheses(
        project_id,
        question_id,
    ) == []


def test_hypotheses_store_null_alternative_and_direction_separately(database):
    project_id = database.create_project("Study")
    question_id = database.create_research_question(
        project_id,
        "Does the intervention improve the outcome?",
    )
    hypothesis_id = database.create_hypothesis(
        project_id,
        question_id,
        null_hypothesis="There is no effect.",
        alternative_hypothesis="The intervention improves the outcome.",
        directionality="directional",
    )

    hypothesis = database.get_hypothesis(
        project_id,
        question_id,
        hypothesis_id,
    )
    assert hypothesis["null_hypothesis"] == "There is no effect."
    assert hypothesis["alternative_hypothesis"] == (
        "The intervention improves the outcome."
    )
    assert hypothesis["directionality"] == "directional"

    assert database.update_hypothesis(
        project_id,
        question_id,
        hypothesis_id,
        null_hypothesis="No measurable change occurs.",
        alternative_hypothesis="The outcome changes.",
        directionality="non-directional",
    )
    updated = database.get_hypothesis(
        project_id,
        question_id,
        hypothesis_id,
    )
    assert updated["null_hypothesis"] == "No measurable change occurs."
    assert updated["alternative_hypothesis"] == "The outcome changes."
    assert updated["directionality"] == "non-directional"


def test_actual_analysis_results_are_separate_from_proposed_test(database):
    project_id = database.create_project("Study")
    question_id = database.create_research_question(
        project_id,
        "Are the variables associated?",
        design_type="association",
        proposed_test="Pearson correlation",
    )
    database.create_analysis_result(
        project_id,
        question_id,
        actual_test="Spearman correlation",
        result_summary="Significant positive association.",
    )

    question = database.get_research_question(project_id, question_id)
    result = database.get_question_analysis_results(
        project_id,
        question_id,
    )[0]
    assert question["proposed_test"] == "Pearson correlation"
    assert result["actual_test"] == "Spearman correlation"
    assert result["result_summary"] == "Significant positive association."


def test_records_survive_database_reopen_and_project_delete_cascades(database):
    database_path = database.database_path
    project_id = database.create_project("Persistent study")
    question_id = database.create_research_question(
        project_id,
        "Persistent question",
    )
    hypothesis_id = database.create_hypothesis(
        project_id,
        question_id,
        null_hypothesis="H0",
        alternative_hypothesis="H1",
    )
    database.close()

    reopened = Database(database_path)
    assert reopened.get_research_question(project_id, question_id)["question"] == (
        "Persistent question"
    )
    assert reopened.get_hypothesis(
        project_id,
        question_id,
        hypothesis_id,
    )["alternative_hypothesis"] == "H1"

    reopened.delete_project(project_id)
    assert reopened.get_project_research_questions(project_id) == []
    assert reopened.get_research_question_hypotheses(
        project_id,
        question_id,
    ) == []
    reopened.close()