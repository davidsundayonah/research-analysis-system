import sqlite3

import pytest

from app.database.database import Database


@pytest.fixture
def database(tmp_path):
    instance = Database(tmp_path / "test.db")
    yield instance
    instance.close()


def test_default_database_path_does_not_depend_on_working_directory(
    monkeypatch,
    tmp_path,
):
    expected_path = Database.default_database_path()

    monkeypatch.chdir(tmp_path)

    assert Database.default_database_path() == expected_path


def test_dataset_revisions_have_one_active_snapshot_and_can_be_switched(tmp_path):
    database = Database(tmp_path / "revisions.db")
    project_id = database.create_project("Revision study")
    first = database.create_dataset(project_id, "first.csv", "first.csv", "csv", 2, 1)
    second = database.create_dataset(
        project_id,
        "second.csv",
        "second.csv",
        "csv",
        3,
        1,
        revision_of=first,
        revision_number=2,
    )

    assert database.get_active_dataset(project_id)["id"] == second
    database.set_active_dataset(project_id, first)
    assert database.get_active_dataset(project_id)["id"] == first
    assert database.get_dataset(second)["revision_of"] == first
    database.close()


def test_database_backup_and_integrity_check(tmp_path):
    database = Database(tmp_path / "backup.db")
    database.create_project("Backup study")
    assert database.integrity_check() == "ok"
    backup = database.backup(tmp_path / "backup-copy.db")
    assert backup.exists()
    database.close()


def test_variable_metadata_round_trip_and_revision_clone(tmp_path):
    database = Database(tmp_path / "metadata.db")
    project_id = database.create_project("Metadata study")
    first = database.create_dataset(
        project_id, "survey.csv", "survey.csv", "csv", 2, 1
    )
    database.replace_dataset_variables(first, [("q1", "int64")])
    database.update_variable_metadata(
        first,
        "q1",
        "Satisfaction response",
        "ordinal",
        {"1": "Strongly disagree", "5": "Strongly agree"},
    )

    revision = database.create_dataset(
        project_id,
        "survey-clean.csv",
        "survey-clean.csv",
        "csv",
        2,
        1,
        revision_number=2,
        revision_of=first,
    )
    database.clone_dataset_links(first, revision)

    row = database.get_dataset_variables(revision)[0]
    assert row["label"] == "Satisfaction response"
    assert row["measure"] == "ordinal"
    assert row["value_labels_json"] == (
        '{"1": "Strongly disagree", "5": "Strongly agree"}'
    )
    database.close()


def test_database_enforces_foreign_keys_and_cascades_project_deletes(database):
    project_id = database.create_project("Research project")
    dataset_id = database.create_dataset(
        project_id=project_id,
        filename="sample.csv",
        file_path="sample.csv",
        file_type="csv",
        row_count=2,
        column_count=1,
    )

    assert database.connection.execute(
        "PRAGMA foreign_keys"
    ).fetchone()[0] == 1

    database.delete_project(project_id)

    assert database.get_dataset(dataset_id) is None


def test_delete_project_returns_removed_dataset_revisions(database):
    project_id = database.create_project("Removable project")
    dataset_id = database.create_dataset(
        project_id, "managed.csv", "managed.csv", "csv", 1, 1
    )

    removed_datasets = database.delete_project(project_id)

    assert [row["id"] for row in removed_datasets] == [dataset_id]
    assert database.get_project(project_id) is None


def test_database_rejects_dataset_for_unknown_project(database):
    with pytest.raises(sqlite3.IntegrityError):
        database.create_dataset(
            project_id=999,
            filename="sample.csv",
            file_path="sample.csv",
            file_type="csv",
            row_count=2,
            column_count=1,
        )


def test_migration_preserves_existing_database_data(tmp_path):
    database_path = tmp_path / "existing.db"
    connection = sqlite3.connect(database_path)
    connection.executescript("""
        CREATE TABLE projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            research_title TEXT,
            researcher TEXT,
            institution TEXT,
            department TEXT,
            significance_level REAL DEFAULT 0.05,
            status TEXT DEFAULT 'New',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE datasets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            filename TEXT NOT NULL,
            file_path TEXT NOT NULL,
            file_type TEXT NOT NULL,
            row_count INTEGER DEFAULT 0,
            column_count INTEGER DEFAULT 0,
            imported_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
        );
        INSERT INTO projects (id, name) VALUES (17, 'Existing project');
        INSERT INTO datasets (
            id, project_id, filename, file_path, file_type, row_count, column_count
        ) VALUES (23, 17, 'old.csv', 'old.csv', 'csv', 4, 2);
    """)
    connection.close()

    database = Database(database_path)

    assert database.connection.execute(
        "PRAGMA user_version"
    ).fetchone()[0] == 12
    assert database.get_project(17)["name"] == "Existing project"
    assert database.get_dataset(23)["filename"] == "old.csv"
    assert database.connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' "
        "AND name = 'research_questions'"
    ).fetchone()[0] == "research_questions"
    assert database.connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' "
        "AND name = 'hypotheses'"
    ).fetchone()[0] == "hypotheses"
    assert database.connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' "
        "AND name = 'research_question_variables'"
    ).fetchone()[0] == "research_question_variables"
    assert database.connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' "
        "AND name = 'analysis_results'"
    ).fetchone()[0] == "analysis_results"
    assert database.connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' "
        "AND name = 'analysis_runs'"
    ).fetchone()[0] == "analysis_runs"

    database.close()


def test_version_three_migration_preserves_questions_and_hypotheses(tmp_path):
    database_path = tmp_path / "version_three.db"
    connection = sqlite3.connect(database_path)
    connection.executescript("""
        CREATE TABLE projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            research_title TEXT,
            researcher TEXT,
            institution TEXT,
            department TEXT,
            significance_level REAL DEFAULT 0.05,
            status TEXT DEFAULT 'New',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE datasets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            filename TEXT NOT NULL,
            file_path TEXT NOT NULL,
            file_type TEXT NOT NULL,
            row_count INTEGER DEFAULT 0,
            column_count INTEGER DEFAULT 0,
            imported_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
        );
        CREATE TABLE research_questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            question TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
        );
        CREATE TABLE hypotheses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            research_question_id INTEGER NOT NULL,
            hypothesis TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (research_question_id)
                REFERENCES research_questions(id) ON DELETE CASCADE
        );
        INSERT INTO projects (id, name) VALUES (5, 'Legacy project');
        INSERT INTO research_questions (id, project_id, question)
            VALUES (8, 5, 'Legacy question');
        INSERT INTO hypotheses (id, research_question_id, hypothesis)
            VALUES (11, 8, 'Legacy hypothesis text');
        PRAGMA user_version = 3;
    """)
    connection.close()

    database = Database(database_path)

    question = database.get_research_question(5, 8)
    hypothesis = database.get_hypothesis(5, 8, 11)
    assert question["code"] == "RQ1"
    assert question["position"] == 1
    assert hypothesis["null_hypothesis"] == ""
    assert hypothesis["alternative_hypothesis"] == "Legacy hypothesis text"
    assert hypothesis["directionality"] == "non-directional"
    database.close()
