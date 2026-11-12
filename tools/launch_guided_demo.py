"""Seed a clearly labelled practice project and open it in the desktop app."""

from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd
import json
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.database.database import Database
from app.statistics.statistical_workflow import StatisticalWorkflow
from app.ui.main_window import MainWindow


PROJECT_NAME = "Guided walkthrough — sample data (practice only)"
TRANSCRIPT_SOURCE = "SIMULATED TRAINING TRANSCRIPT — not from survey CSV"


def _get_or_create_question(database, project_id, code, text, design):
    questions = database.get_project_research_questions(project_id)
    existing = next((row for row in questions if row["code"] == code), None)
    if existing:
        return existing["id"]
    return database.create_research_question(
        project_id, text, code=code, design_type=design
    )


def _get_or_create_hypothesis(database, project_id, question_id, null, alternative):
    hypotheses = database.get_research_question_hypotheses(project_id, question_id)
    if hypotheses:
        return hypotheses[0]["id"]
    return database.create_hypothesis(
        project_id,
        question_id,
        null_hypothesis=null,
        alternative_hypothesis=alternative,
        directionality="non-directional",
    )


def seed_practice_project(database):
    project = next(
        (row for row in database.get_projects() if row["name"] == PROJECT_NAME),
        None,
    )
    project_id = project["id"] if project else database.create_project(
        PROJECT_NAME,
        research_title="Guided practice with supplied sample files",
        significance_level=0.05,
    )

    survey = pd.read_csv(ROOT / "test_research_data.csv")
    ts_frame = pd.read_csv(ROOT / "time_series_example.csv")
    datasets = {
        row["filename"]: row["id"]
        for row in database.get_project_datasets(project_id)
    }
    survey_id = datasets.get("test_research_data.csv")
    if survey_id is None:
        survey_id = database.create_dataset_from_frame(
            project_id,
            "test_research_data.csv",
            survey,
            source_path=str(ROOT / "test_research_data.csv"),
        )
    ts_id = datasets.get("time_series_example.csv")
    if ts_id is None:
        ts_id = database.create_dataset_from_frame(
            project_id,
            "time_series_example.csv",
            ts_frame,
            source_path=str(ROOT / "time_series_example.csv"),
        )
    database.set_active_dataset(project_id, survey_id)

    # Descriptive summaries across the example's non-ID variables.
    descriptive_id = _get_or_create_question(
        database,
        project_id,
        "DEMO_DESC",
        "What does the practice survey dataset look like?",
        "descriptive",
    )
    for name in survey.columns:
        if name != "ID":
            database.set_question_variable(
                project_id, descriptive_id, survey_id, name, "outcome"
            )
    workflow = StatisticalWorkflow(database)
    if not database.get_question_analysis_runs(project_id, descriptive_id):
        workflow.run_analysis(
            project_id,
            descriptive_id,
            None,
            survey_id,
            survey,
            workflow.DESCRIPTIVE_TEST,
            {"variables": [name for name in survey.columns if name != "ID"]},
        )

    # A worked association example with a directional interpretation avoided.
    association_id = _get_or_create_question(
        database,
        project_id,
        "DEMO_ASSOC",
        "Are reported social-media hours associated with GPA in this practice dataset?",
        "association",
    )
    for name, role in (("SM_Hours", "predictor"), ("GPA", "outcome")):
        database.set_question_variable(project_id, association_id, survey_id, name, role)
    association_hypothesis = _get_or_create_hypothesis(
        database,
        project_id,
        association_id,
        "There is no monotonic association between SM_Hours and GPA.",
        "There is a monotonic association between SM_Hours and GPA.",
    )
    if not database.get_question_analysis_runs(project_id, association_id):
        workflow.run_analysis(
            project_id,
            association_id,
            association_hypothesis,
            survey_id,
            survey,
            "correlation",
            {"first_variable": "SM_Hours", "second_variable": "GPA", "method": "spearman"},
        )

    # One-predictor regression, kept separate from the association question.
    prediction_id = _get_or_create_question(
        database,
        project_id,
        "DEMO_PRED",
        "Can SM_Hours predict GPA in the practice dataset?",
        "prediction",
    )
    for name, role in (("SM_Hours", "predictor"), ("GPA", "outcome")):
        database.set_question_variable(project_id, prediction_id, survey_id, name, role)
    prediction_hypothesis = _get_or_create_hypothesis(
        database,
        project_id,
        prediction_id,
        "SM_Hours has no linear association with GPA.",
        "SM_Hours has a linear association with GPA.",
    )
    if not database.get_question_analysis_runs(project_id, prediction_id):
        workflow.run_analysis(
            project_id,
            prediction_id,
            prediction_hypothesis,
            survey_id,
            survey,
            "linear_regression",
            {"predictor_variable": "SM_Hours", "outcome_variable": "GPA"},
        )

    # The supplied CSV has no open-text field. This transcript is explicitly
    # simulated and exists only to demonstrate the app's manual coding steps.
    if not database.get_interview_guide(project_id):
        database.save_interview_guide(
            project_id,
            "Simulated practice interview guide",
            "How do you use social media while studying?\n"
            "What makes it easier or harder to concentrate?\n"
            "Does social media ever help with your studies?",
        )
    transcript = next(
        (
            row
            for row in database.get_interview_transcripts(project_id)
            if row["source_name"] == TRANSCRIPT_SOURCE
        ),
        None,
    )
    transcript_id = transcript["id"] if transcript else database.create_interview_transcript(
        project_id,
        "DEMO-01",
        TRANSCRIPT_SOURCE,
        (ROOT / "sample_qualitative_transcript_demo.txt").read_text(encoding="utf-8"),
    )
    codes = {
        row["code"]: row["id"]
        for row in database.get_qualitative_codes(project_id)
    }
    code_specs = [
        ("unplanned_scrolling", "Attention and time management", "Unplanned extended use while studying."),
        ("notification_distraction", "Attention and time management", "Notifications interrupt study focus."),
        ("learning_support", "Learning support", "Tutorials or class discussions support understanding."),
    ]
    for code, theme, meaning in code_specs:
        if code not in codes:
            codes[code] = database.create_qualitative_code(project_id, code, theme, meaning)
    existing_codings = database.get_qualitative_codings(project_id)
    already_coded = {row["code"] for row in existing_codings if row["source_name"] == TRANSCRIPT_SOURCE}
    excerpts = [
        ("unplanned_scrolling", "sometimes I keep scrolling longer than I planned", "Simulated excerpt; code the stated time-management issue."),
        ("notification_distraction", "Notifications distract me when I am trying to finish an assignment.", "Simulated excerpt; code the stated interruption."),
        ("learning_support", "Tutorial videos and class group discussions can help me understand a topic.", "Simulated excerpt; code the stated learning support."),
    ]
    if not already_coded:
        for code, excerpt, note in excerpts:
            database.create_transcript_coding(
                project_id, transcript_id, codes[code], excerpt, note, "demo-analyst"
            )
    return project_id, survey_id, ts_id


def main():
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    database = Database()
    project_id, survey_id, ts_id = seed_practice_project(database)
    project = database.get_project(project_id)
    print(f"Practice project ready: {project['name']}", flush=True)
    for code in ("DEMO_DESC", "DEMO_ASSOC", "DEMO_PRED"):
        question = next(
            row for row in database.get_project_research_questions(project_id)
            if row["code"] == code
        )
        runs = database.get_question_analysis_runs(project_id, question["id"])
        result = json.loads(runs[0]["result_json"]) if runs else {}
        print(
            f"{code}: {result.get('test', 'not yet run')}; n={result.get('sample_size', '—')}; "
            f"statistic={result.get('statistic', '—')}; p={result.get('p_value', '—')}",
            flush=True,
        )
    print(
        f"Qualitative practice: {len(database.get_qualitative_codings(project_id))} manually coded excerpts "
        "from a simulated transcript (not from the CSV).",
        flush=True,
    )
    window = MainWindow(database)
    window.resize(1050, 760)
    window.open_project(project_id)
    window.show()
    window.pages.setCurrentWidget(window.qualitative_page)
    window.navigation.setCurrentRow(9)  # Qualitative practice example

    def open_time_series_demo():
        window.open_time_series_window()
        ts_window = window.time_series_window
        ts_window.resize(980, 760)
        ts_window.project_combo.setCurrentIndex(
            ts_window.project_combo.findData(project_id)
        )
        ts_window._refresh_project_datasets()
        ts_window._set_dataframe(pd.read_csv(ROOT / "time_series_example.csv"), ts_id)
        ts_window.date_combo.setCurrentText("Year")
        ts_window.value_combo.setCurrentText("Unemployment_Rate")
        ts_window.analysis_type_combo.setCurrentIndex(
            ts_window.analysis_type_combo.findData("univariate")
        )
        ts_window.model_combo.setCurrentText("ARIMA")
        for spin, value in zip(ts_window.arima_order_spins, (0, 1, 1)):
            spin.setValue(value)
        ts_window.horizon_spin.setValue(5)
        ts_window.test_size_spin.setValue(5)
        ts_window.provenance_inputs["data_source"].setText(
            "Included practice file: time_series_example.csv"
        )
        ts_window.provenance_inputs["indicator_name"].setText("Unemployment rate (example series)")
        ts_window.provenance_inputs["units"].setText("Percent")
        ts_window.run_analysis()
        if ts_window.last_result:
            result = ts_window.last_result
            print(
                f"Time series: {result.get('model_specification')}; "
                f"holdout RMSE={result.get('evaluation', {}).get('RMSE')}; "
                f"forecast years={result.get('forecast_index')}",
                flush=True,
            )
        if ts_window.chart_canvases.get("Original series and trend") is not None:
            ts_window.tabs.setCurrentWidget(
                ts_window.chart_canvases["Original series and trend"]
            )
        ts_window.show()
        ts_window.raise_()
        ts_window.activateWindow()

    QTimer.singleShot(700, open_time_series_demo)
    app.exec()


if __name__ == "__main__":
    main()
