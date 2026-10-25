import json

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.statistics.statistical_workflow import (
    StatisticalWorkflow,
    TestRecommendationEngine,
)


class AnalysisPage(QWidget):
    analysis_saved = Signal(int, int)

    def __init__(self, database):
        super().__init__()
        self.database = database
        self.workflow = StatisticalWorkflow(database)
        self.recommender = TestRecommendationEngine()
        self.project_id = None
        self.dataset_id = None
        self.dataframe = None
        self.recommendation_by_row = {}
        self.displayed_run = None
        self.displayed_result_text = None

        layout = QVBoxLayout(self)
        title = QLabel("Analysis")
        title.setObjectName("page_title")
        layout.addWidget(title)

        self.context_label = QLabel("Select a project and dataset to begin.")
        self.context_label.setObjectName("page_subtitle")
        layout.addWidget(self.context_label)

        selectors = QHBoxLayout()
        self.question_combo = QComboBox()
        self.question_combo.currentIndexChanged.connect(self.refresh_question_context)
        selectors.addWidget(self.question_combo)
        self.sample_structure_combo = QComboBox()
        self.sample_structure_combo.addItem("Independent samples", "independent")
        self.sample_structure_combo.addItem("Paired samples", "paired")
        self.sample_structure_combo.currentIndexChanged.connect(self.refresh_recommendations)
        selectors.addWidget(self.sample_structure_combo)
        self.hypothesis_combo = QComboBox()
        selectors.addWidget(self.hypothesis_combo)
        layout.addLayout(selectors)

        self.recommendation_list = QListWidget()
        self.recommendation_list.currentRowChanged.connect(self.update_run_state)
        layout.addWidget(self.recommendation_list)

        self.run_button = QPushButton("Run Selected Analysis")
        self.run_button.setObjectName("primary_button")
        self.run_button.clicked.connect(self.run_selected_analysis)
        layout.addWidget(self.run_button)

        self.result_label = QLabel("No analysis run selected.")
        self.result_label.setWordWrap(True)
        layout.addWidget(self.result_label)

        self.refresh_project_data()

    def set_context(self, project_id, dataset_id, dataframe):
        self.project_id = project_id
        self.dataset_id = dataset_id
        self.dataframe = dataframe
        if project_id is None:
            self.context_label.setText("Select a project and dataset to begin.")
        else:
            project = self.database.get_project(project_id)
            project_name = project["name"] if project else "Unknown project"
            dataset_name = (
                self.database.get_dataset(dataset_id)["filename"]
                if dataset_id is not None and self.database.get_dataset(dataset_id)
                else "No active dataset"
            )
            self.context_label.setText(
                f"Project: {project_name} | Dataset: {dataset_name}"
            )
        if self.displayed_run is not None:
            same_dataset = dataset_id == self.displayed_run["dataset_id"]
            same_snapshot = (
                dataframe is not None
                and self.workflow.is_snapshot_current(
                    self.displayed_run,
                    dataframe,
                )
            )
            if not same_dataset or not same_snapshot:
                self.result_label.setText(
                    "Historical result: the active dataset differs from the saved analysis snapshot.\n"
                    + self.displayed_result_text
                )
            else:
                self.result_label.setText(self.displayed_result_text)
        self.refresh_project_data()

    def refresh_project_data(self, *_):
        selected_id = self.question_combo.currentData()
        self.question_combo.blockSignals(True)
        self.question_combo.clear()
        if self.project_id is not None:
            for question in self.database.get_project_research_questions(self.project_id):
                self.question_combo.addItem(
                    f"{question['code']} | {question['question']}",
                    question["id"],
                )
        index = self.question_combo.findData(selected_id)
        self.question_combo.setCurrentIndex(index if index >= 0 else 0)
        self.question_combo.blockSignals(False)
        self.refresh_question_context()

    def refresh_question_context(self, *_):
        self.hypothesis_combo.clear()
        question_id = self.question_combo.currentData()
        if self.project_id is not None and question_id is not None:
            for hypothesis in self.database.get_research_question_hypotheses(
                self.project_id,
                question_id,
            ):
                label = (
                    hypothesis["alternative_hypothesis"].strip()
                    or "Incomplete alternative hypothesis"
                )
                self.hypothesis_combo.addItem(label, hypothesis["id"])
        self.refresh_recommendations()

    def refresh_recommendations(self, *_):
        self.recommendation_list.clear()
        self.recommendation_by_row.clear()
        question_id = self.question_combo.currentData()
        if (
            self.project_id is not None
            and question_id is not None
            and self.dataframe is not None
        ):
            question = self.database.get_research_question(
                self.project_id,
                question_id,
            )
            links = self.database.get_question_variables(
                self.project_id,
                question_id,
            )
            variable_metadata = self.database.get_dataset_variables(self.dataset_id)
            recommendations = self.recommender.recommend(
                question,
                self.dataframe,
                links,
                sample_structure=self.sample_structure_combo.currentData(),
                dataset_id=self.dataset_id,
                variable_metadata=variable_metadata,
            )
        else:
            recommendations = [{
                "test": None,
                "settings": {},
                "reason": "Select a project, research question, and active dataset.",
                "warnings": [],
            }]

        question = (
            self.database.get_research_question(self.project_id, question_id)
            if self.project_id is not None and question_id is not None
            else None
        )
        if (
            question is not None
            and question["design_type"] != "descriptive"
            and self.hypothesis_combo.currentData() is None
        ):
            recommendations = [{
                "test": None,
                "settings": {},
                "reason": "Add a complete null and alternative hypothesis before selecting or running an inferential test.",
                "warnings": ["Inferential tests are intentionally blocked until H0 and H1 are saved."],
            }]

        for recommendation in recommendations:
            title = recommendation["test"] or "No inferential test recommended"
            warnings = " ".join(recommendation["warnings"])
            text = f"{title}\n{recommendation['reason']}"
            if warnings:
                text += f"\nWarnings: {warnings}"
            item = QListWidgetItem(text)
            row = self.recommendation_list.count()
            self.recommendation_by_row[row] = recommendation
            self.recommendation_list.addItem(item)
        if self.recommendation_list.count():
            self.recommendation_list.setCurrentRow(0)
        self.update_run_state()

    def update_run_state(self, *_):
        recommendation = self.recommendation_by_row.get(
            self.recommendation_list.currentRow()
        )
        self.run_button.setEnabled(
            recommendation is not None
            and recommendation["test"] is not None
            and (
                recommendation["test"] == self.workflow.DESCRIPTIVE_TEST
                or self.hypothesis_combo.currentData() is not None
            )
            and self.dataset_id is not None
        )

    def run_selected_analysis(self):
        recommendation = self.recommendation_by_row.get(
            self.recommendation_list.currentRow()
        )
        if recommendation is None or recommendation["test"] is None:
            return
        try:
            result = self.workflow.run_analysis(
                self.project_id,
                self.question_combo.currentData(),
                self.hypothesis_combo.currentData(),
                self.dataset_id,
                self.dataframe,
                recommendation["test"],
                recommendation["settings"],
            )
        except (KeyError, TypeError, ValueError) as error:
            QMessageBox.warning(self, "Analysis Error", str(error))
            return
        self.displayed_result_text = json.dumps(
            result.to_dict(),
            indent=2,
            ensure_ascii=False,
        )
        self.result_label.setText(self.displayed_result_text)
        if result.status != "ok":
            self.result_label.setText(
                f"Analysis could not be run.\n{self.result_label.text()}"
            )
            return
        runs = self.database.get_question_analysis_runs(
            self.project_id,
            self.question_combo.currentData(),
        )
        if runs:
            self.displayed_run = self.database.decode_analysis_run(runs[0])
            self.analysis_saved.emit(
                self.project_id,
                self.question_combo.currentData(),
            )
