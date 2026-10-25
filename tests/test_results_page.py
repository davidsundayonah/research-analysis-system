import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pandas as pd
import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication

from app.database.database import Database
from app.statistics.statistical_result import StatisticalResult
from app.statistics.table_generator import TableGenerator, TableNumberingContext
from app.statistics.statistical_workflow import StatisticalWorkflow
from app.ui.main_window import MainWindow
from app.ui.results_page import ResultsPage


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


@pytest.fixture
def results_context(tmp_path):
    database = Database(tmp_path / "results.db")
    project_id = database.create_project("Results study")
    question_id = database.create_research_question(
        project_id,
        "Are study measures associated?",
    )
    hypothesis_id = database.create_hypothesis(
        project_id,
        question_id,
        null_hypothesis="There is no association.",
        alternative_hypothesis="The measures are associated.",
    )
    dataset_id = database.create_dataset(
        project_id,
        "results.csv",
        str(tmp_path / "results.csv"),
        "csv",
        5,
        2,
    )
    dataframe = pd.DataFrame({
        "x": [1, 2, 3, 4, 5],
        "y": [2, 1, 4, 3, 7],
    })
    result = StatisticalResult(
        test="pearson_correlation",
        variables=["x", "y"],
        sample_size=5,
        statistic=0.8,
        degrees_of_freedom=3,
        p_value=0.1,
        effect_size={"correlation": 0.8},
        confidence_interval=(0.1, 0.95),
        decision="fail_to_reject_null",
        details={"method": "pearson", "standard_error": 0.2},
    )
    database.create_analysis_run(
        project_id=project_id,
        question_id=question_id,
        hypothesis_id=hypothesis_id,
        dataset_id=dataset_id,
        dataset_signature=StatisticalWorkflow.dataset_signature(dataframe),
        actual_test="pearson_correlation",
        settings={"test": "correlation", "parameters": {"method": "pearson", "alpha": 0.05}},
        result=result.to_dict(),
        hypothesis_decision=result.decision,
    )
    yield {
        "database": database,
        "project_id": project_id,
        "question_id": question_id,
        "dataset_id": dataset_id,
        "dataframe": dataframe,
    }
    database.close()


def table_values(page):
    return {
        page.summary_table.horizontalHeaderItem(column).text(): page.summary_table.item(0, column).text()
        for column in range(page.summary_table.columnCount())
        if page.summary_table.rowCount() > 0
    }


def test_results_page_retrieves_formats_and_shows_full_saved_result(
    qt_app,
    results_context,
    monkeypatch,
):
    context = results_context
    page = ResultsPage(context["database"])
    original_result = context["database"].decode_analysis_run(
        context["database"].get_question_analysis_runs(
            context["project_id"],
            context["question_id"],
        )[0]
    )["result"]

    def fail_if_recalculated(*_args, **_kwargs):
        raise AssertionError("Results display must not call the statistical engine.")

    monkeypatch.setattr(
        "app.statistics.statistical_engine.StatisticalEngine",
        fail_if_recalculated,
    )

    page.set_context(
        context["project_id"],
        context["dataset_id"],
        context["dataframe"],
    )

    assert page.history_list.count() == 1
    assert "Pearson correlation" in page.history_list.item(0).text()
    assert "Fail to reject null hypothesis" in page.history_list.item(0).text()
    assert "Current snapshot" in page.history_list.item(0).text()
    assert page.historical_warning.text() == ""

    summary = table_values(page)
    assert summary["Variable 1"] == "x"
    assert summary["Variable 2"] == "y"
    assert summary["N"] == "5"
    assert summary["r"] == "0.80"
    assert summary["p"] == "p = .100"
    assert summary["95% CI"] == "0.10 to 0.95"
    assert '"standard_error": 0.2' in page.full_details.toPlainText()
    saved_row = context["database"].decode_analysis_run(
        context["database"].get_question_analysis_runs(
            context["project_id"],
            context["question_id"],
        )[0]
    )
    assert page.generated_table.source["run_id"] == saved_row["id"]
    assert page.generated_table.source["dataset_signature"] == saved_row["dataset_signature"]
    assert page.generated_table.rows[0][3] == "0.80"
    assert page.runs_by_row[0]["result"] == original_result
    assert "not statistically significant" in page.interpretation_finding.text()
    assert "does not prove there is no effect" in page.research_conclusion.text()
    assert "H0: There is no association" in page.research_conclusion.text()
    assert "does not, by itself, establish causation" in page.interpretation_caveats.text()

    page.set_numbering_context(TableNumberingContext("chapter-four"))
    assert page.generated_table.number == 1
    page.refresh_runs()
    assert page.generated_table.number == 1
    assert page.generated_table.source["run_id"] == page.runs_by_row[0]["id"]

    changed = context["dataframe"].copy()
    changed.loc[0, "x"] = 100
    page.set_context(
        context["project_id"],
        context["dataset_id"],
        changed,
    )
    assert "content differs" in page.historical_warning.text()
    assert "Historical" in page.history_list.item(0).text()

    other_dataset_id = context["database"].create_dataset(
        context["project_id"],
        "replacement.csv",
        "replacement.csv",
        "csv",
        5,
        2,
    )
    page.set_context(
        context["project_id"],
        other_dataset_id,
        context["dataframe"],
    )
    assert "different from the dataset" in page.historical_warning.text()

    dispose_widgets(qt_app, page)


def test_result_formatter_uses_test_specific_fields():
    t_result = {
        "variables": ["score", "group"],
        "sample_size": 12,
        "statistic": 2.4,
        "degrees_of_freedom": 9.5,
        "p_value": 0.03,
        "confidence_interval": [0.2, 4.0],
        "effect_size": {"cohens_d": 0.7, "hedges_g": 0.65},
        "decision": "reject_null",
        "warnings": [],
        "details": {"group_means": [5, 2], "group_sizes": [6, 6]},
    }
    t_rows = dict(ResultsPage.format_result("independent_t_test", t_result))

    anova_result = {
        **t_result,
        "effect_size": {"eta_squared": 0.3, "omega_squared": 0.25},
        "details": {
            "degrees_of_freedom_between": 2,
            "degrees_of_freedom_within": 9,
            "group_means": [2, 3, 5],
            "group_sizes": [4, 4, 4],
        },
    }
    anova_rows = dict(ResultsPage.format_result("one_way_anova", anova_result))

    regression_result = {
        **t_result,
        "details": {
            "intercept": 1.2,
            "slope": 0.8,
            "slope_p_value": 0.02,
            "f_statistic": 8.5,
            "durbin_watson": 1.9,
        },
        "effect_size": {"r_squared": 0.64, "adjusted_r_squared": 0.6},
    }
    regression_rows = dict(ResultsPage.format_result("linear_regression", regression_result))

    assert t_rows["t"] == "2.40"
    assert t_rows["Hedges' g"] == "0.65"
    assert anova_rows["F"] == "2.40"
    assert regression_rows["Coefficient"] == "1.20"
    assert regression_rows["SE"] == "Not available"
    regression_table = TableGenerator().from_result(
        regression_result,
        "linear_regression",
    )
    assert any("R² = 0.64" in footnote for footnote in regression_table.footnotes)

    paired_result = {
        **t_result,
        "effect_size": {"cohens_dz": 0.4, "hedges_gz": 0.35},
        "details": {"mean_difference": 2.1},
    }
    paired_rows = dict(ResultsPage.format_result("paired_t_test", paired_result))
    chi_result = {
        **t_result,
        "effect_size": {"cramers_v": 0.2},
        "details": {
            "row_categories": ["A", "B"],
            "column_categories": ["Yes", "No"],
            "observed": [[10, 4], [5, 12]],
            "expected": [[7, 7], [8, 9]],
        },
    }
    chi_rows = dict(ResultsPage.format_result("chi_square_test", chi_result))
    corr_result = {
        **t_result,
        "statistic": 0.8,
        "effect_size": {"correlation": 0.8},
        "details": {"method": "spearman"},
    }
    corr_rows = dict(ResultsPage.format_result("spearman_correlation", corr_result))

    assert paired_rows["Cohen's dz"] == "0.40"
    assert paired_rows["Mean difference"] == "2.10"
    assert chi_rows["Expected / test"] == "7.00"
    assert corr_rows["rs"] == "0.80"


def test_main_window_has_results_page_wired_to_navigation(qt_app, tmp_path):
    database = Database(tmp_path / "main-window.db")
    window = MainWindow(database)

    assert window.navigation.item(6).text() == "Results"
    assert window.pages.widget(6) is window.results_page

    project_id = database.create_project("Results navigation")
    window.open_project(project_id)
    window.navigation.setCurrentRow(6)
    assert window.pages.currentWidget() is window.results_page
    assert window.results_page.project_id == project_id

    dispose_widgets(qt_app, window)
