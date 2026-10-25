import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtWidgets import QApplication, QMessageBox

from app.database.database import Database
from app.ui.main_window import MainWindow


@pytest.fixture(scope="session")
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    app.processEvents()


def dispose_window(app, window):
    if window.isVisible():
        window.close()
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    app.processEvents()


def test_dashboard_metrics_count_projects_runs_and_completed_status(tmp_path):
    database = Database(tmp_path / "dashboard.db")
    completed_project = database.create_project("Completed study")
    active_project = database.create_project("Active study")
    database.connection.execute(
        "UPDATE projects SET status = ? WHERE id = ?",
        ("Completed", completed_project),
    )
    database.connection.commit()

    question_id = database.create_research_question(
        active_project,
        "Does the intervention affect outcomes?",
    )
    dataset_id = database.create_dataset(
        active_project,
        "study.csv",
        str(tmp_path / "study.csv"),
        "csv",
        4,
        1,
    )
    database.create_analysis_run(
        project_id=active_project,
        question_id=question_id,
        hypothesis_id=None,
        dataset_id=dataset_id,
        dataset_signature="fingerprint",
        actual_test="pearson_correlation",
        settings={"parameters": {"alpha": 0.05}},
        result={"test": "pearson_correlation", "status": "ok", "variables": ["x", "y"]},
        hypothesis_decision=None,
    )

    assert database.get_dashboard_metrics() == {
        "projects": 2,
        "analyses": 1,
        "completed": 1,
    }
    database.close()


def test_dashboard_cards_load_and_refresh_from_database(qt_app, tmp_path):
    database = Database(tmp_path / "dashboard-ui.db")
    project_id = database.create_project("Initial project")
    window = MainWindow(database)

    assert window.dashboard_metric_labels["projects"].text() == "1"
    assert window.dashboard_metric_labels["analyses"].text() == "0"
    assert window.dashboard_metric_labels["completed"].text() == "0"

    second_project_id = database.create_project("New project")
    window.projects_page.projects_changed.emit()
    assert window.dashboard_metric_labels["projects"].text() == "2"

    question_id = database.create_research_question(
        second_project_id,
        "Is there an association?",
    )
    dataset_id = database.create_dataset(
        second_project_id,
        "association.csv",
        str(tmp_path / "association.csv"),
        "csv",
        4,
        2,
    )
    database.create_analysis_run(
        project_id=second_project_id,
        question_id=question_id,
        hypothesis_id=None,
        dataset_id=dataset_id,
        dataset_signature="snapshot",
        actual_test="pearson_correlation",
        settings={"parameters": {"alpha": 0.05}},
        result={"test": "pearson_correlation", "status": "ok", "variables": ["a", "b"]},
        hypothesis_decision="reject_null",
    )
    window.analysis_page.analysis_saved.emit(second_project_id, question_id)
    assert window.dashboard_metric_labels["analyses"].text() == "1"

    database.connection.execute(
        "UPDATE projects SET status = ? WHERE id = ?",
        ("Completed", project_id),
    )
    database.connection.commit()
    window.navigation.setCurrentRow(1)
    window.navigation.setCurrentRow(0)
    assert window.dashboard_metric_labels["completed"].text() == "1"

    dispose_window(qt_app, window)


def test_dashboard_can_delete_selected_project_and_clear_active_context(
    qt_app,
    tmp_path,
    monkeypatch,
):
    database = Database(tmp_path / "delete-project.db")
    project_id = database.create_project("Project to delete")
    dataset_path = tmp_path / "study.csv"
    dataset_path.write_text("value\n1\n2\n", encoding="utf-8")
    dataset_id = database.create_dataset(
        project_id,
        "study.csv",
        str(dataset_path),
        "csv",
        2,
        1,
    )
    window = MainWindow(database)
    window.projects_page.load_projects()
    window.open_project(project_id)
    row = next(
        row
        for row in range(window.projects_page.project_list.count())
        if window.projects_page.project_list.item(row).data(Qt.UserRole) == project_id
    )
    window.navigation.setCurrentRow(1)
    window.projects_page.project_list.setCurrentRow(row)
    row_widget = window.projects_page.project_list.itemWidget(
        window.projects_page.project_list.item(row)
    )
    row_widget.selection_checkbox.setChecked(True)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.Yes,
    )
    monkeypatch.setattr(
        QMessageBox,
        "information",
        lambda *args, **kwargs: QMessageBox.Ok,
    )

    window.projects_page.delete_selected_project()

    assert database.get_project(project_id) is None
    assert database.get_dataset(dataset_id) is None
    assert window.data_page.current_project_id is None
    assert window.projects_page.delete_button.isEnabled() is False
    dispose_window(qt_app, window)


def test_dashboard_select_all_deletes_multiple_projects(qt_app, tmp_path, monkeypatch):
    database = Database(tmp_path / "delete-multiple-projects.db")
    first_id = database.create_project("First project")
    second_id = database.create_project("Second project")
    window = MainWindow(database)
    window.projects_page.load_projects()

    window.projects_page.select_all_checkbox.setChecked(True)

    assert window.projects_page.checked_project_ids() == [first_id, second_id]
    assert window.projects_page.delete_button.text() == "Delete Selected Projects (2)"
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.Yes,
    )
    monkeypatch.setattr(
        QMessageBox,
        "information",
        lambda *args, **kwargs: QMessageBox.Ok,
    )

    window.projects_page.delete_selected_projects()

    assert database.get_project(first_id) is None
    assert database.get_project(second_id) is None
    assert window.projects_page.project_list.count() == 1
    dispose_window(qt_app, window)


def test_project_checkbox_does_not_open_project(qt_app, tmp_path):
    database = Database(tmp_path / "checkbox-isolation.db")
    project_id = database.create_project("Checkbox project")
    window = MainWindow(database)
    opened = []
    window.projects_page.project_selected.connect(opened.append)
    row_widget = window.projects_page.project_list.itemWidget(
        window.projects_page.project_list.item(0)
    )

    row_widget.selection_checkbox.click()

    assert opened == []
    assert window.projects_page.checked_project_ids() == [project_id]
    assert window.navigation.currentRow() == 0
    dispose_window(qt_app, window)


def test_project_open_control_preserves_opening_behaviour(qt_app, tmp_path):
    database = Database(tmp_path / "project-open.db")
    project_id = database.create_project("Open project")
    window = MainWindow(database)
    opened = []
    window.projects_page.project_selected.connect(opened.append)
    row_widget = window.projects_page.project_list.itemWidget(
        window.projects_page.project_list.item(0)
    )

    row_widget.open_button.click()

    assert opened == [project_id]
    assert window.navigation.currentRow() == 2
    dispose_window(qt_app, window)


def test_cancel_bulk_deletion_preserves_selection_and_projects(
    qt_app, tmp_path, monkeypatch
):
    database = Database(tmp_path / "cancel-delete.db")
    first_id = database.create_project("Keep first")
    second_id = database.create_project("Keep second")
    window = MainWindow(database)
    window.projects_page.select_all_checkbox.setChecked(True)
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.No)

    window.projects_page.delete_selected_projects()

    assert database.get_project(first_id) is not None
    assert database.get_project(second_id) is not None
    assert set(window.projects_page.checked_project_ids()) == {first_id, second_id}
    dispose_window(qt_app, window)
