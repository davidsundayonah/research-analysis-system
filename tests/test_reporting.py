import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from copy import deepcopy
from pathlib import Path

import pandas as pd
import pytest
from docx import Document
from openpyxl import load_workbook
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication

from app.database.database import Database
from app.reporting import ChapterFourExporter, ChapterFourGenerator
from app.statistics.statistical_engine import StatisticalEngine
from app.statistics.statistical_result import StatisticalResult
from app.statistics.statistical_workflow import StatisticalWorkflow
from app.ui.main_window import MainWindow
from app.ui.export_page import ExportPage


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


def add_analysis(database, project_id, question_id, hypothesis_id, dataset_id, dataframe, test):
    if test == "pearson_correlation":
        result = StatisticalResult(
            test=test,
            variables=["hours", "score"],
            sample_size=len(dataframe),
            statistic=0.72,
            degrees_of_freedom=len(dataframe) - 2,
            p_value=0.004,
            effect_size={"correlation": 0.72},
            confidence_interval=(0.3, 0.9),
            decision="reject_null",
            details={"method": "pearson", "alpha": 0.05},
        )
    else:
        result = StatisticalResult(
            test=test,
            variables=["score", "group"],
            sample_size=len(dataframe),
            statistic=2.5,
            degrees_of_freedom=10,
            p_value=0.03,
            effect_size={"cohens_d": 0.8, "hedges_g": 0.74},
            confidence_interval=(0.2, 3.2),
            decision="reject_null",
            details={
                "group_order": ["A", "B"],
                "group_sizes": [6, 6],
                "group_means": [5.0, 7.0],
                "group_standard_deviations": [1.0, 1.5],
                "alpha": 0.05,
            },
        )
    return database.create_analysis_run(
        project_id=project_id,
        question_id=question_id,
        hypothesis_id=hypothesis_id,
        dataset_id=dataset_id,
        dataset_signature=StatisticalWorkflow.dataset_signature(dataframe),
        actual_test=test,
        settings={"test": test, "parameters": {"alpha": 0.05}},
        result=result.to_dict(),
        hypothesis_decision=result.decision,
    )


@pytest.fixture
def reporting_context(tmp_path):
    database = Database(tmp_path / "chapter-four.db")
    project_id = database.create_project(
        "Community Learning Study",
        research_title="Learning Outcomes in Community Programs",
        researcher="Researcher A",
        institution="Example Institute",
        department="Education",
        significance_level=0.05,
    )
    first_path = tmp_path / "current.csv"
    first_data = pd.DataFrame({
        "hours": list(range(1, 13)),
        "score": [3, 4, 4, 5, 5, 6, 6, 7, 7, 8, 8, 9],
        "group": ["A"] * 6 + ["B"] * 6,
        "gender": ["F", "M"] * 6,
    })
    first_data.to_csv(first_path, index=False)
    first_dataset_id = database.create_dataset(
        project_id, "current.csv", str(first_path), "csv", len(first_data), len(first_data.columns)
    )
    database.replace_dataset_variables(
        first_dataset_id,
        [(str(column), str(dtype)) for column, dtype in first_data.dtypes.items()],
    )

    stale_path = tmp_path / "stale.csv"
    stale_data = first_data.copy()
    stale_data.to_csv(stale_path, index=False)
    stale_dataset_id = database.create_dataset(
        project_id, "stale.csv", str(stale_path), "csv", len(stale_data), len(stale_data.columns)
    )
    database.replace_dataset_variables(
        stale_dataset_id,
        [(str(column), str(dtype)) for column, dtype in stale_data.dtypes.items()],
    )

    questions = []
    for code, text, design in [
        ("RQ1", "Are hours associated with score?", "association"),
        ("RQ2", "Do groups differ in score?", "comparison"),
        ("RQ3", "What is the demographic profile?", "descriptive"),
    ]:
        question_id = database.create_research_question(
            project_id,
            text,
            code=code,
            design_type=design,
        )
        hypothesis_id = database.create_hypothesis(
            project_id,
            question_id,
            null_hypothesis="There is no effect.",
            alternative_hypothesis="There is an effect.",
        )
        questions.append((question_id, hypothesis_id))

    first_question, first_hypothesis = questions[0]
    first_run_id = add_analysis(
        database,
        project_id,
        first_question,
        first_hypothesis,
        first_dataset_id,
        first_data,
        "pearson_correlation",
    )
    second_question, second_hypothesis = questions[1]
    second_run_id = add_analysis(
        database,
        project_id,
        second_question,
        second_hypothesis,
        stale_dataset_id,
        stale_data,
        "independent_t_test",
    )

    original_run_json = {
        run_id: database.decode_analysis_run(
            database.connection.execute(
                "SELECT * FROM analysis_runs WHERE id = ?",
                (run_id,),
            ).fetchone()
        )["result"]
        for run_id in (first_run_id, second_run_id)
    }

    yield {
        "database": database,
        "project_id": project_id,
        "first_path": first_path,
        "stale_path": stale_path,
        "first_data": first_data,
        "stale_data": stale_data,
        "first_dataset_id": first_dataset_id,
        "stale_dataset_id": stale_dataset_id,
        "questions": questions,
        "run_ids": [first_run_id, second_run_id],
        "original_run_json": original_run_json,
        "tmp_path": tmp_path,
    }
    database.close()


def test_chapter_four_covers_multiple_questions_and_flags_stale_missing_results(
    reporting_context,
    monkeypatch,
):
    context = reporting_context

    def fail_if_engine_runs(*_args, **_kwargs):
        raise AssertionError("Chapter Four must not rerun saved inferential analyses.")

    monkeypatch.setattr("app.statistics.statistical_engine.StatisticalEngine", fail_if_engine_runs)
    monkeypatch.setattr("app.statistics.statistical_workflow.StatisticalEngine", fail_if_engine_runs)

    changed_stale_data = context["stale_data"].copy()
    changed_stale_data.loc[0, "score"] += 100
    changed_stale_data.to_csv(context["stale_path"], index=False)

    report = ChapterFourGenerator(context["database"]).generate(context["project_id"])
    by_question = {
        section.source_question_id: section
        for section in report.sections
        if section.source_question_id is not None
    }
    first_question, second_question, third_question = [item[0] for item in context["questions"]]

    assert len(by_question) == 3
    assert report.source_analysis_ids == context["run_ids"]
    assert any(table.source.get("run_id") == context["run_ids"][0] for table in by_question[first_question].tables)
    assert any("There was a statistically significant" in paragraph for paragraph in by_question[first_question].paragraphs)
    assert any("Historical analysis run" in paragraph for paragraph in by_question[second_question].paragraphs)
    assert any("No saved analysis" in paragraph for paragraph in by_question[third_question].paragraphs)
    assert any("no longer matches the saved analysis snapshot" in warning for warning in report.warnings)
    assert any(table.source.get("section") == "frequency_tables" for table in report.sections[1].tables)

    for run_id in context["run_ids"]:
        stored = context["database"].decode_analysis_run(
            context["database"].connection.execute(
                "SELECT * FROM analysis_runs WHERE id = ?",
                (run_id,),
            ).fetchone()
        )
        assert stored["result"] == context["original_run_json"][run_id]


def test_docx_and_xlsx_exports_preserve_structure_and_analysis_traceability(
    qt_app,
    reporting_context,
    monkeypatch,
):
    context = reporting_context
    generator = ChapterFourGenerator(context["database"])
    exporter = ChapterFourExporter()
    page = ExportPage(generator, exporter)
    page.set_project(context["project_id"])

    def fail_if_engine_runs(*_args, **_kwargs):
        raise AssertionError("Export must use saved results and not rerun analysis.")

    monkeypatch.setattr("app.statistics.statistical_engine.StatisticalEngine", fail_if_engine_runs)
    monkeypatch.setattr("app.statistics.statistical_workflow.StatisticalEngine", fail_if_engine_runs)

    changed_stale_data = context["stale_data"].copy()
    changed_stale_data.loc[0, "score"] += 100
    changed_stale_data.to_csv(context["stale_path"], index=False)

    docx_path = context["tmp_path"] / "chapter-four.docx"
    xlsx_path = context["tmp_path"] / "chapter-four.xlsx"
    assert page.export_to(docx_path, "docx", confirm_revision=True) == docx_path
    assert page.export_to(xlsx_path, "xlsx", confirm_revision=True) == xlsx_path
    assert docx_path.exists() and docx_path.stat().st_size > 0
    assert xlsx_path.exists() and xlsx_path.stat().st_size > 0

    document = Document(docx_path)
    paragraphs = [paragraph.text for paragraph in document.paragraphs]
    document_text = "\n".join(paragraphs)
    assert any("CHAPTER FOUR" in paragraph for paragraph in paragraphs)
    assert any("Introduction" in paragraph for paragraph in paragraphs)
    assert any("Research question findings: RQ1" in paragraph for paragraph in paragraphs)
    assert any("Summary of findings" in paragraph for paragraph in paragraphs)
    assert str(context["run_ids"][0]) in document_text
    assert len(document.tables) >= 4

    workbook = load_workbook(xlsx_path, data_only=True)
    assert {"Overview", "Descriptive", "RQ1", "RQ2", "RQ3", "Warnings"}.issubset(workbook.sheetnames)
    all_cells = [
        str(cell.value)
        for sheet in workbook.worksheets
        for row in sheet.iter_rows()
        for cell in row
        if cell.value is not None
    ]
    assert any("Source run" in cell and str(context["run_ids"][0]) in cell for cell in all_cells)
    assert any("Historical" in cell or "no longer matches" in cell for cell in all_cells)

    for run_id in context["run_ids"]:
        stored = context["database"].decode_analysis_run(
            context["database"].connection.execute(
                "SELECT * FROM analysis_runs WHERE id = ?",
                (run_id,),
            ).fetchone()
        )
        assert stored["result"] == context["original_run_json"][run_id]

    dispose_widgets(qt_app, page)


def test_export_requires_explicit_revision_confirmation(reporting_context, qt_app):
    page = ExportPage(ChapterFourGenerator(reporting_context["database"]), ChapterFourExporter())
    page.set_project(reporting_context["project_id"])
    with pytest.raises(ValueError, match="different dataset revisions"):
        page.export_to(reporting_context["tmp_path"] / "blocked.docx", "docx")
    dispose_widgets(qt_app, page)


def test_main_window_routes_chapter_four_and_export_for_selected_project(
    qt_app,
    reporting_context,
):
    context = reporting_context
    window = MainWindow(context["database"])

    assert window.navigation.item(7).text() == "Chapter Four"
    assert window.navigation.item(8).text() == "Export"
    assert window.pages.widget(7) is window.chapter_four_page
    assert window.pages.widget(8) is window.export_page

    window.open_project(context["project_id"])
    window.navigation.setCurrentRow(7)
    assert window.pages.currentWidget() is window.chapter_four_page
    assert window.chapter_four_page.project_id == context["project_id"]
    window.navigation.setCurrentRow(8)
    assert window.pages.currentWidget() is window.export_page
    assert window.export_page.project_id == context["project_id"]

    dispose_widgets(qt_app, window)
