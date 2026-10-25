import pytest

from app.database.database import Database


@pytest.fixture
def database(tmp_path):
    instance = Database(tmp_path / "question_variables.db")
    yield instance
    instance.close()


def test_question_variables_validate_dataset_project_role_and_name(database):
    project_id = database.create_project("Study")
    other_project_id = database.create_project("Other study")
    question_id = database.create_research_question(project_id, "Question")
    dataset_id = database.create_dataset(
        project_id,
        "sample.csv",
        "sample.csv",
        "csv",
        5,
        2,
    )
    other_dataset_id = database.create_dataset(
        other_project_id,
        "other.csv",
        "other.csv",
        "csv",
        5,
        1,
    )
    database.replace_dataset_variables(
        dataset_id,
        [("Outcome", "int64"), ("Group", "object")],
    )
    database.replace_dataset_variables(
        other_dataset_id,
        [("Other", "int64")],
    )

    variable_id = database.set_question_variable(
        project_id,
        question_id,
        dataset_id,
        "Outcome",
        "outcome",
    )
    assert database.get_question_variables(project_id, question_id)[0]["role"] == (
        "outcome"
    )

    with pytest.raises(ValueError, match="does not exist"):
        database.set_question_variable(
            project_id,
            question_id,
            dataset_id,
            "Missing",
            "predictor",
        )
    with pytest.raises(ValueError, match="belong to this project"):
        database.set_question_variable(
            project_id,
            question_id,
            other_dataset_id,
            "Other",
            "predictor",
        )
    with pytest.raises(ValueError, match="Unsupported variable role"):
        database.set_question_variable(
            project_id,
            question_id,
            dataset_id,
            "Group",
            "confounder",
        )

    database.replace_dataset_variables(
        dataset_id,
        [("Renamed_Outcome", "int64"), ("Group", "object")],
    )
    assert database.get_question_variables(
        project_id,
        question_id,
    )[0]["variable_exists"] == 0
    assert database.delete_question_variable(
        project_id,
        question_id,
        variable_id,
    )


def test_question_variables_are_removed_when_project_is_deleted(database):
    project_id = database.create_project("Study")
    question_id = database.create_research_question(project_id, "Question")
    dataset_id = database.create_dataset(
        project_id,
        "sample.csv",
        "sample.csv",
        "csv",
        5,
        1,
    )
    database.replace_dataset_variables(dataset_id, [("Outcome", "int64")])
    database.set_question_variable(
        project_id,
        question_id,
        dataset_id,
        "Outcome",
        "outcome",
    )

    database.delete_project(project_id)

    assert database.get_project_research_questions(project_id) == []
    assert database.connection.execute(
        "SELECT COUNT(*) FROM research_question_variables"
    ).fetchone()[0] == 0