import json

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.statistics.statistical_workflow import StatisticalWorkflow
from app.statistics.table_generator import TableGenerator, TableNumberingContext
from app.statistics.interpretation_engine import InterpretationEngine


class ResultsPage(QWidget):
    TEST_LABELS = {
        "descriptive_analysis": "Descriptive analysis",
        "independent_t_test": "Independent t-test",
        "paired_t_test": "Paired t-test",
        "one_way_anova": "One-way ANOVA",
        "chi_square_test": "Chi-square test",
        "pearson_correlation": "Pearson correlation",
        "spearman_correlation": "Spearman correlation",
        "linear_regression": "Linear regression",
    }

    def __init__(self, database):
        super().__init__()
        self.database = database
        self.workflow = StatisticalWorkflow(database)
        self.table_generator = TableGenerator()
        self.interpretation_engine = InterpretationEngine()
        self.numbering_context = None
        self.generated_table = None
        self.project_id = None
        self.dataset_id = None
        self.dataframe = None
        self.runs_by_row = {}

        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        title = QLabel("Results")
        title.setObjectName("page_title")
        header.addWidget(title)
        header.addStretch()
        self.question_combo = QComboBox()
        self.question_combo.currentIndexChanged.connect(self.refresh_runs)
        header.addWidget(self.question_combo)
        layout.addLayout(header)

        self.context_label = QLabel("Select a project to view saved analyses.")
        self.context_label.setObjectName("page_subtitle")
        layout.addWidget(self.context_label)

        content = QHBoxLayout()
        self.history_list = QListWidget()
        self.history_list.setMinimumWidth(330)
        self.history_list.currentRowChanged.connect(self.show_selected_run)
        content.addWidget(self.history_list, 1)

        details_layout = QVBoxLayout()
        self.table_title = QLabel()
        self.table_title.setWordWrap(True)
        self.table_title.setStyleSheet("font-weight: bold;")
        details_layout.addWidget(self.table_title)

        self.historical_warning = QLabel()
        self.historical_warning.setWordWrap(True)
        self.historical_warning.setStyleSheet("color: #9a3412; font-weight: bold;")
        details_layout.addWidget(self.historical_warning)

        self.summary_table = QTableWidget(0, 0)
        self.summary_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.summary_table.setAlternatingRowColors(True)
        details_layout.addWidget(self.summary_table)

        self.full_details = QPlainTextEdit()
        self.full_details.setReadOnly(True)
        self.full_details.setPlaceholderText("Select a saved analysis to inspect its full result.")
        details_layout.addWidget(self.full_details, 1)
        self.table_footnotes = QPlainTextEdit()
        self.table_footnotes.setReadOnly(True)
        self.table_footnotes.setMaximumHeight(110)
        details_layout.addWidget(self.table_footnotes)

        self.interpretation_heading = QLabel("Interpretation")
        self.interpretation_heading.setStyleSheet("font-weight: bold;")
        details_layout.addWidget(self.interpretation_heading)
        self.interpretation_finding = QLabel()
        self.interpretation_finding.setWordWrap(True)
        details_layout.addWidget(self.interpretation_finding)
        self.research_conclusion = QLabel()
        self.research_conclusion.setWordWrap(True)
        details_layout.addWidget(self.research_conclusion)
        self.interpretation_caveats = QLabel()
        self.interpretation_caveats.setWordWrap(True)
        details_layout.addWidget(self.interpretation_caveats)

        content.addLayout(details_layout, 2)
        layout.addLayout(content, 1)

    def set_context(self, project_id, dataset_id=None, dataframe=None):
        self.project_id = project_id
        self.dataset_id = dataset_id
        self.dataframe = dataframe
        project = self.database.get_project(project_id) if project_id is not None else None
        self.context_label.setText(
            f"Project: {project['name']}" if project else "Select a project to view saved analyses."
        )

        selected_id = self.question_combo.currentData()
        self.question_combo.blockSignals(True)
        self.question_combo.clear()
        if project_id is not None:
            for question in self.database.get_project_research_questions(project_id):
                self.question_combo.addItem(
                    f"{question['code']} | {question['question']}",
                    question["id"],
                )
        selected_index = self.question_combo.findData(selected_id)
        self.question_combo.setCurrentIndex(
            selected_index if selected_index >= 0 else 0
        )
        self.question_combo.blockSignals(False)
        self.refresh_runs()

    def refresh_project_questions(self, *_):
        self.set_context(self.project_id, self.dataset_id, self.dataframe)

    def set_numbering_context(self, numbering_context):
        if numbering_context is not None and not isinstance(
            numbering_context,
            TableNumberingContext,
        ):
            raise TypeError("numbering_context must be a TableNumberingContext or None.")
        self.numbering_context = numbering_context
        self.refresh_runs()

    def analysis_saved(self, project_id, question_id):
        if project_id != self.project_id:
            return
        question_index = self.question_combo.findData(question_id)
        if question_index >= 0:
            self.question_combo.setCurrentIndex(question_index)
        self.refresh_runs()

    def refresh_runs(self, *_):
        self.history_list.clear()
        self.runs_by_row.clear()
        question_id = self.question_combo.currentData()
        if self.project_id is None or question_id is None:
            self.clear_selected_run()
            return

        runs = self.database.get_question_analysis_runs(
            self.project_id,
            question_id,
        )
        for run_row in runs:
            run = self.database.decode_analysis_run(run_row)
            warning = self.historical_status(run)
            label = self.TEST_LABELS.get(run["actual_test"], run["actual_test"])
            decision = self.format_decision(run["hypothesis_decision"])
            status = "Historical" if warning else "Current snapshot"
            item = QListWidgetItem(
                f"{label} | {run['created_at']}\n{decision} | {status}"
            )
            item.setData(Qt.UserRole, run["id"])
            self.history_list.addItem(item)
            self.runs_by_row[self.history_list.count() - 1] = run

        if self.history_list.count():
            self.history_list.setCurrentRow(0)
        else:
            self.clear_selected_run()

    def historical_status(self, run):
        if self.dataset_id is None or self.dataframe is None:
            return "Active dataset is not loaded; snapshot freshness cannot be verified."
        if self.dataset_id != run["dataset_id"]:
            return "The active dataset is different from the dataset used for this saved analysis."
        if not self.workflow.is_snapshot_current(run, self.dataframe):
            return "The active dataset content differs from the saved analysis snapshot."
        return None

    def show_selected_run(self, row):
        run = self.runs_by_row.get(row)
        if run is None:
            self.clear_selected_run()
            return

        warning = self.historical_status(run)
        self.historical_warning.setText(warning or "")
        result = run["result"]
        self.generated_table = self.table_generator.from_saved_run(
            run,
            numbering=self.numbering_context,
        )
        table = self.generated_table
        self.table_title.setText(table.display_title)
        self.summary_table.clear()
        self.summary_table.setRowCount(len(table.rows))
        self.summary_table.setColumnCount(len(table.columns))
        self.summary_table.setHorizontalHeaderLabels(table.columns)
        for row_index, row in enumerate(table.rows):
            for column_index, value in enumerate(row):
                self.summary_table.setItem(
                    row_index,
                    column_index,
                    QTableWidgetItem(str(value)),
                )
        self.summary_table.resizeColumnsToContents()
        self.table_footnotes.setPlainText("\n".join(table.footnotes))
        self.full_details.setPlainText(
            json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True)
        )
        hypothesis_text = self._linked_hypothesis_text(run)
        interpretation = self.interpretation_engine.interpret(
            run,
            hypothesis_text=hypothesis_text,
        )
        self.interpretation_finding.setText(interpretation.finding)
        self.research_conclusion.setText(interpretation.conclusion)
        caveat_lines = list(interpretation.caveats)
        if interpretation.unavailable_fields:
            caveat_lines.append(
                "Unavailable in saved result: "
                + ", ".join(interpretation.unavailable_fields)
                + "."
            )
        self.interpretation_caveats.setText(
            "Caveats: " + " ".join(caveat_lines)
            if caveat_lines
            else ""
        )

    def _linked_hypothesis_text(self, run):
        hypothesis_id = run.get("hypothesis_id")
        if hypothesis_id is None:
            return None
        hypothesis = self.database.get_hypothesis(
            run["project_id"],
            run["research_question_id"],
            hypothesis_id,
        )
        if hypothesis is None:
            return None
        null_hypothesis = hypothesis["null_hypothesis"].strip()
        alternative = hypothesis["alternative_hypothesis"].strip()
        if not null_hypothesis and not alternative:
            return None
        return f"H0: {null_hypothesis or 'unavailable'}; H1: {alternative or 'unavailable'}"

    def clear_selected_run(self):
        self.generated_table = None
        self.table_title.clear()
        self.historical_warning.clear()
        self.summary_table.setRowCount(0)
        self.summary_table.setColumnCount(0)
        self.table_footnotes.clear()
        self.interpretation_finding.clear()
        self.research_conclusion.clear()
        self.interpretation_caveats.clear()
        self.full_details.clear()

    @classmethod
    def format_result(cls, test_name, result):
        table = TableGenerator().from_result(result, test_name)
        return list(zip(table.columns, table.rows[0] if table.rows else []))

    @staticmethod
    def format_decision(decision):
        return {
            "reject_null": "Reject null hypothesis",
            "fail_to_reject_null": "Fail to reject null hypothesis",
        }.get(decision, "No decision recorded")

