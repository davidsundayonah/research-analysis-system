import os
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pandas as pd
import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from app.database.database import Database
from app.ui.hypothesis_dialog import HypothesisDialog
from app.ui.main_window import MainWindow
from app.ui.hypotheses_page import HypothesesPage
from app.ui.analysis_page import AnalysisPage
from app.ui.research_question_dialog import ResearchQuestionDialog
from app.ui.research_questions_page import ResearchQuestionsPage


@pytest.fixture(scope="session")
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    app.processEvents()


def dispose_widgets(app, *widgets):
    for widget in widgets:
        if widget.isVisible():
            widget.close()
        widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    app.processEvents()


def test_question_dialog_rejects_empty_question_text(qt_app):
    dialog = ResearchQuestionDialog()

    dialog.validate_and_accept()

    assert dialog.result() == ResearchQuestionDialog.Rejected
    assert dialog.validation_label.text() == "Question text is required."
    dispose_widgets(qt_app, dialog)


def test_hypothesis_dialog_warns_when_hypotheses_are_incomplete(qt_app):
    dialog = HypothesisDialog()

    assert "incomplete" in dialog.warning_label.text().lower()

    dialog.null_input.setPlainText("There is no association.")
    dialog.alternative_input.setPlainText("There is an association.")

    assert dialog.warning_label.text() == ""
    dispose_widgets(qt_app, dialog)


def test_management_screens_track_project_dataset_variables_and_hypotheses(
    qt_app,
    tmp_path,
):
    dataset_path = tmp_path / "study.csv"
    pd.DataFrame({
        "Outcome": [1, 2, 3],
        "Predictor": [4, 5, 6],
    }).to_csv(dataset_path, index=False)

    database = Database(tmp_path / "study.db")
    project_id = database.create_project("Study")
    dataset_id = database.create_dataset(
        project_id,
        dataset_path.name,
        str(dataset_path),
        "csv",
        3,
        2,
    )
    question_id = database.create_research_question(
        project_id,
        "Are the variables associated?",
        design_type="association",
        proposed_test="Pearson correlation",
    )
    database.create_hypothesis(
        project_id,
        question_id,
        alternative_hypothesis="The variables are associated.",
    )

    window = MainWindow(database)
    window.open_project(project_id)

    questions_page = window.research_questions_page
    hypotheses_page = window.hypotheses_page
    assert window.data_page.current_dataset_id == dataset_id
    assert questions_page.variable_combo.count() == 2
    assert questions_page.question_list.item(0).text().startswith("RQ1")
    assert "Missing variable roles" in questions_page.validation_warnings.text()
    assert "missing H0 or H1" in questions_page.validation_warnings.text()

    questions_page.variable_combo.setCurrentText("Outcome")
    questions_page.role_combo.setCurrentText("outcome")
    questions_page.link_variable()
    questions_page.variable_combo.setCurrentText("Predictor")
    questions_page.role_combo.setCurrentText("predictor")
    questions_page.link_variable()

    assert "missing H0 or H1" in questions_page.validation_warnings.text()
    assert "incomplete" in hypotheses_page.validation_warning.text().lower()

    hypothesis = database.get_research_question_hypotheses(
        project_id,
        question_id,
    )[0]
    database.update_hypothesis(
        project_id,
        question_id,
        hypothesis["id"],
        null_hypothesis="There is no association.",
    )
    hypotheses_page.load_hypotheses()
    questions_page.update_selected_question()

    assert hypotheses_page.validation_warning.text() == "Hypotheses are complete."
    assert questions_page.validation_warnings.text() == "Design checks passed."
    assert window.navigation.item(3).text() == "Research Questions"
    assert window.navigation.item(4).text() == "Hypotheses"

    analysis_page = window.analysis_page
    analysis_page.refresh_project_data()
    assert analysis_page.recommendation_by_row[0]["test"] == "correlation"
    assert analysis_page.recommendation_by_row[0]["settings"]["method"] == "spearman"
    assert "ordinal" in analysis_page.recommendation_by_row[0]["reason"].lower()
    analysis_page.question_combo.setCurrentIndex(
        analysis_page.question_combo.findData(question_id)
    )
    analysis_page.hypothesis_combo.setCurrentIndex(
        analysis_page.hypothesis_combo.findData(hypothesis["id"])
    )
    analysis_page.recommendation_list.setCurrentRow(0)
    assert analysis_page.run_button.isEnabled()
    analysis_page.run_selected_analysis()

    stored_runs = database.get_question_analysis_runs(project_id, question_id)
    assert len(stored_runs) == 1
    assert window.results_page.question_combo.currentData() == question_id
    assert window.results_page.history_list.count() == 1
    saved_run = database.decode_analysis_run(stored_runs[0])
    assert saved_run["actual_test"] == "spearman_correlation"
    assert saved_run["dataset_signature"]
    assert saved_run["hypothesis_decision"] in {
        "reject_null",
        "fail_to_reject_null",
    }
    assert '"status": "ok"' in analysis_page.result_label.text()

    window.data_page.current_dataframe = pd.DataFrame({
        "Outcome_Renamed": [1, 2, 3],
        "Predictor": [4, 5, 6],
    })
    window.data_page.publish_dataset_state()
    assert "missing or renamed" in questions_page.validation_warnings.text()
    assert "Historical result" in analysis_page.result_label.text()

    second_dataset_id = database.create_dataset(
        project_id,
        "next.csv",
        str(dataset_path),
        "csv",
        3,
        2,
    )
    window.data_page.current_dataset_id = second_dataset_id
    window.data_page.publish_dataset_state()
    assert "stale: dataset changed" in questions_page.validation_warnings.text()

    dispose_widgets(qt_app, window)

    reopened_database = Database(tmp_path / "study.db")
    restarted_window = MainWindow(reopened_database)
    restarted_window.open_project(project_id)
    assert restarted_window.research_questions_page.question_list.count() == 1
    assert restarted_window.hypotheses_page.hypothesis_list.count() == 1
    assert "H1: The variables are associated." in (
        restarted_window.hypotheses_page.hypothesis_list.item(0).text()
    )
    dispose_widgets(qt_app, restarted_window)


def test_question_and_hypothesis_screens_handle_crud_and_ordering(
    qt_app,
    tmp_path,
):
    database = Database(tmp_path / "screen-crud.db")
    project_id = database.create_project("Study")
    questions_page = ResearchQuestionsPage(database)
    questions_page.set_project(project_id)

    with (
        patch(
            "app.ui.research_questions_page.ResearchQuestionDialog.exec",
            return_value=QDialog.Accepted,
        ),
        patch(
            "app.ui.research_questions_page.ResearchQuestionDialog.get_question_data",
            return_value={
                "question": "First question",
                "code": "Q-A",
                "position": 1,
                "design_type": "descriptive",
                "proposed_test": "Summary statistics",
            },
        ),
    ):
        questions_page.add_question()

    first_id = database.get_project_research_questions(project_id)[0]["id"]
    with (
        patch(
            "app.ui.research_questions_page.ResearchQuestionDialog.exec",
            return_value=QDialog.Accepted,
        ),
        patch(
            "app.ui.research_questions_page.ResearchQuestionDialog.get_question_data",
            return_value={
                "question": "Second question",
                "code": "Q-B",
                "position": 2,
                "design_type": "comparison",
                "proposed_test": "t-test",
            },
        ),
    ):
        questions_page.add_question()

    second_id = database.get_project_research_questions(project_id)[1]["id"]
    questions_page.question_list.setCurrentRow(1)
    questions_page.move_question(-1)
    assert [
        row["id"]
        for row in database.get_project_research_questions(project_id)
    ] == [second_id, first_id]

    questions_page.question_list.setCurrentRow(0)
    with (
        patch(
            "app.ui.research_questions_page.ResearchQuestionDialog.exec",
            return_value=QDialog.Accepted,
        ),
        patch(
            "app.ui.research_questions_page.ResearchQuestionDialog.get_question_data",
            return_value={
                "question": "Edited second question",
                "code": "Q-B",
                "position": 1,
                "design_type": "comparison",
                "proposed_test": "Welch t-test",
            },
        ),
    ):
        questions_page.edit_question()
    assert database.get_research_question(
        project_id,
        second_id,
    )["question"] == "Edited second question"

    hypotheses_page = HypothesesPage(database)
    hypotheses_page.set_project(project_id)
    with (
        patch(
            "app.ui.hypotheses_page.HypothesisDialog.exec",
            return_value=QDialog.Accepted,
        ),
        patch(
            "app.ui.hypotheses_page.HypothesisDialog.get_hypothesis_data",
            return_value={
                "null_hypothesis": "No group difference.",
                "alternative_hypothesis": "Groups differ.",
                "directionality": "non-directional",
            },
        ),
    ):
        hypotheses_page.add_hypothesis()

    hypothesis_item = hypotheses_page.hypothesis_list.item(0)
    hypotheses_page.hypothesis_list.setCurrentItem(hypothesis_item)
    with (
        patch(
            "app.ui.hypotheses_page.HypothesisDialog.exec",
            return_value=QDialog.Accepted,
        ),
        patch(
            "app.ui.hypotheses_page.HypothesisDialog.get_hypothesis_data",
            return_value={
                "null_hypothesis": "No difference exists.",
                "alternative_hypothesis": "The intervention group scores higher.",
                "directionality": "directional",
            },
        ),
    ):
        hypotheses_page.edit_hypothesis()

    hypothesis_id = database.get_research_question_hypotheses(
        project_id,
        second_id,
    )[0]["id"]
    assert database.get_hypothesis(
        project_id,
        second_id,
        hypothesis_id,
    )["directionality"] == "directional"

    hypotheses_page.hypothesis_list.setCurrentRow(0)
    with patch(
        "app.ui.hypotheses_page.QMessageBox.question",
        return_value=QMessageBox.Yes,
    ):
        hypotheses_page.delete_hypothesis()
    assert database.get_research_question_hypotheses(
        project_id,
        second_id,
    ) == []

    questions_page.question_list.setCurrentRow(0)
    with patch(
        "app.ui.research_questions_page.QMessageBox.question",
        return_value=QMessageBox.Yes,
    ):
        questions_page.delete_question()
    assert database.get_research_question(project_id, second_id) is None
    database.close()
    dispose_widgets(qt_app, questions_page, hypotheses_page)


def test_analysis_recommendation_selection_and_refresh_follow_context(
    qt_app,
    tmp_path,
):
    database = Database(tmp_path / "recommendation-ui.db")
    project_id = database.create_project("Recommendation study")
    dataset_id = database.create_dataset(
        project_id,
        "active.csv",
        str(tmp_path / "active.csv"),
        "csv",
        12,
        5,
    )
    dataframe = pd.DataFrame({
        "x": list(range(12)),
        "y": [2, 4, 3, 7, 6, 8, 9, 11, 10, 14, 13, 16],
        "group": ["A"] * 6 + ["B"] * 6,
        "before": [10, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22],
        "after": [11, 13, 12, 15, 16, 17, 18, 19, 20, 21, 22, 23],
    })
    database.replace_dataset_variables(
        dataset_id,
        [(str(column), str(dtype)) for column, dtype in dataframe.dtypes.items()],
    )

    association_id = database.create_research_question(
        project_id,
        "Are x and y associated?",
        design_type="association",
    )
    comparison_id = database.create_research_question(
        project_id,
        "Do scores differ?",
        design_type="comparison",
    )
    for question_id in (association_id, comparison_id):
        database.create_hypothesis(
            project_id,
            question_id,
            null_hypothesis="No effect.",
            alternative_hypothesis="An effect exists.",
        )

    for variable, role in (("x", "predictor"), ("y", "outcome")):
        database.set_question_variable(
            project_id,
            association_id,
            dataset_id,
            variable,
            role,
        )
    for variable, role in (
        ("y", "outcome"),
        ("before", "outcome"),
        ("after", "outcome"),
        ("group", "grouping"),
    ):
        database.set_question_variable(
            project_id,
            comparison_id,
            dataset_id,
            variable,
            role,
        )

    page = AnalysisPage(database)
    page.set_context(project_id, dataset_id, dataframe)

    assert page.question_combo.currentData() == association_id
    assert [
        page.recommendation_by_row[row]["settings"]["method"]
        for row in range(page.recommendation_list.count())
    ] == ["pearson", "spearman"]
    page.recommendation_list.setCurrentRow(1)
    assert page.recommendation_by_row[
        page.recommendation_list.currentRow()
    ]["settings"]["method"] == "spearman"
    assert page.run_button.isEnabled()

    page.sample_structure_combo.setCurrentIndex(
        page.sample_structure_combo.findData("paired")
    )
    page.question_combo.setCurrentIndex(
        page.question_combo.findData(comparison_id)
    )
    assert page.question_combo.currentData() == comparison_id
    assert page.recommendation_list.count() == 3
    page.recommendation_list.setCurrentRow(2)
    selected_pair = page.recommendation_by_row[2]["settings"]
    assert selected_pair == {
        "first_variable": "before",
        "second_variable": "after",
    }

    page.sample_structure_combo.setCurrentIndex(
        page.sample_structure_combo.findData("independent")
    )
    assert page.recommendation_list.count() == 3
    assert page.recommendation_by_row[0]["test"] == "independent_t_test"

    replacement_id = database.create_dataset(
        project_id,
        "replacement.csv",
        str(tmp_path / "replacement.csv"),
        "csv",
        12,
        5,
    )
    database.replace_dataset_variables(
        replacement_id,
        [(str(column), str(dtype)) for column, dtype in dataframe.dtypes.items()],
    )
    page.set_context(project_id, replacement_id, dataframe.copy())

    assert page.recommendation_by_row[0]["test"] is None
    assert any(
        "stale" in warning
        for warning in page.recommendation_by_row[0]["warnings"]
    )
    assert not page.run_button.isEnabled()

    database.close()
    dispose_widgets(qt_app, page)