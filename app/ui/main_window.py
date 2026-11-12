from pathlib import Path

from PySide6.QtCore import QSize, Qt, QSettings, QTimer
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from app.database.database import Database
from app.reporting import ChapterFourExporter, ChapterFourGenerator
from app.ui.analysis_page import AnalysisPage
from app.ui.chapter_four_page import ChapterFourPage
from app.ui.data_page import DataPage
from app.ui.export_page import ExportPage
from app.ui.hypotheses_page import HypothesesPage
from app.ui.projects_page import ProjectsPage
from app.ui.research_questions_page import ResearchQuestionsPage
from app.ui.results_page import ResultsPage
from app.ui.qualitative_page import QualitativePage
from app.ui.time_series_window import TimeSeriesWindow


class EvenlySpacedNavigation(QListWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.model().rowsInserted.connect(self._redistribute_items)
        self.model().rowsRemoved.connect(self._redistribute_items)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._redistribute_items()

    def _redistribute_items(self, *_args):
        count = self.count()
        available_height = self.viewport().height()
        if not count or available_height <= 0:
            return

        row_height, extra_pixels = divmod(available_height, count)
        for row in range(count):
            height = row_height + (1 if row < extra_pixels else 0)
            self.item(row).setSizeHint(QSize(0, height))


class MainWindow(QMainWindow):

    def __init__(self, database=None):
        super().__init__()

        self.setWindowTitle(
            "Research Analysis System"
        )

        self.resize(
            1300,
            800
        )

        # Database
        self.database = database or Database()
        self.settings = QSettings("ResearchAnalysis", "ResearchAnalysis")
        self.dashboard_metric_labels = {}
        self.workflow_step = -1
        self.export_done = False
        self.last_page_index = 0
        self.time_series_nav_index = 10
        self.help_nav_index = 11
        self.workflow_pages = [2, 3, 4, 3, 5, 6, 8]
        self.workflow_titles = [
            "Import your dataset",
            "Define research questions",
            "Add hypotheses",
            "Link variables",
            "Run the analysis",
            "Review results",
            "Export your report",
        ]

        # Build interface
        self.setup_ui()

    # =========================================================
    # SETUP UI
    # =========================================================

    def setup_ui(self):

        # -----------------------------------------------------
        # Main container
        # -----------------------------------------------------

        central_widget = QWidget()

        self.setCentralWidget(
            central_widget
        )

        main_layout = QHBoxLayout(
            central_widget
        )

        main_layout.setContentsMargins(
            0,
            0,
            0,
            0
        )

        main_layout.setSpacing(0)

        # -----------------------------------------------------
        # Sidebar
        # -----------------------------------------------------

        sidebar = QFrame()

        sidebar.setFixedWidth(
            230
        )

        sidebar.setObjectName(
            "sidebar"
        )

        sidebar_layout = QVBoxLayout(
            sidebar
        )

        sidebar_layout.setContentsMargins(
            15,
            20,
            15,
            20
        )
        sidebar_layout.setSpacing(0)

        # -----------------------------------------------------
        # Application title
        # -----------------------------------------------------

        title = QLabel(
            "Research\nAnalysis System"
        )

        title.setObjectName(
            "app_title"
        )

        title.setAlignment(
            Qt.AlignCenter
        )

        sidebar_layout.addWidget(
            title
        )

        # -----------------------------------------------------
        # Navigation
        # -----------------------------------------------------

        self.navigation = EvenlySpacedNavigation()

        self.navigation.setObjectName(
            "navigation"
        )

        navigation_items = [
            "Dashboard",
            "Projects",
            "Data",
            "Research Questions",
            "Hypotheses",
            "Analysis",
            "Results",
            "Chapter Four",
            "Export",
            "Qualitative",
            "Time-Series Analysis",
            "Help",
        ]

        for item_name in navigation_items:

            item = QListWidgetItem(
                item_name
            )

            self.navigation.addItem(
                item
            )

        sidebar_layout.addWidget(
            self.navigation,
            1
        )

        # -----------------------------------------------------
        # Version
        # -----------------------------------------------------

        version = QLabel(
            "Version 0.1.0"
        )

        version.setAlignment(
            Qt.AlignCenter
        )

        version.setObjectName(
            "version"
        )

        sidebar_layout.addWidget(
            version
        )

        # -----------------------------------------------------
        # Main content area
        # -----------------------------------------------------

        self.pages = QStackedWidget()

        # =====================================================
        # Dashboard
        # =====================================================

        self.create_dashboard_page()

        # =====================================================
        # Projects
        # =====================================================

        self.projects_page = ProjectsPage(
            self.database
        )

        self.pages.addWidget(
            self.projects_page
        )

        self.projects_page.project_selected.connect(
            self.open_project
        )
        self.projects_page.project_deleted.connect(
            self.handle_project_deleted
        )
        self.projects_page.projects_changed.connect(
            self.refresh_dashboard_metrics
        )

        # =====================================================
        # Data
        # =====================================================

        self.data_page = DataPage(
            self.database
        )

        self.pages.addWidget(
            self.data_page
        )

        # =====================================================
        # Research Questions
        # =====================================================

        self.research_questions_page = ResearchQuestionsPage(
            self.database
        )

        self.pages.addWidget(
            self.research_questions_page
        )

        # =====================================================
        # Hypotheses
        # =====================================================

        self.hypotheses_page = HypothesesPage(
            self.database
        )

        self.pages.addWidget(
            self.hypotheses_page
        )

        self.research_questions_page.questions_changed.connect(
            self.hypotheses_page.set_project
        )

        # =====================================================
        # Analysis
        # =====================================================

        self.analysis_page = AnalysisPage(self.database)
        self.pages.addWidget(self.analysis_page)
        self.research_questions_page.questions_changed.connect(
            self.analysis_page.refresh_project_data
        )
        self.data_page.dataset_changed.connect(
            self.update_dataset_context
        )

        # =====================================================
        # Results
        # =====================================================

        self.results_page = ResultsPage(self.database)
        self.pages.addWidget(self.results_page)
        self.research_questions_page.questions_changed.connect(
            self.results_page.refresh_project_questions
        )
        self.analysis_page.analysis_saved.connect(
            self.results_page.analysis_saved
        )
        self.analysis_page.analysis_saved.connect(
            self.refresh_dashboard_metrics
        )
        self.analysis_page.analysis_saved.connect(self._analysis_completed)
        self.research_questions_page.questions_changed.connect(
            self._questions_changed
        )

        # =====================================================
        # Chapter Four
        # =====================================================

        self.chapter_four_generator = ChapterFourGenerator(self.database)
        self.chapter_four_exporter = ChapterFourExporter()
        self.chapter_four_page = ChapterFourPage(self.chapter_four_generator)
        self.pages.addWidget(self.chapter_four_page)

        # =====================================================
        # Export
        # =====================================================

        self.export_page = ExportPage(
            self.chapter_four_generator,
            self.chapter_four_exporter,
        )
        self.export_page.export_completed.connect(self._export_completed)
        self.pages.addWidget(self.export_page)

        self.qualitative_page = QualitativePage(self.database)
        self.pages.addWidget(self.qualitative_page)

        self.help_page = QWidget()
        help_layout = QVBoxLayout(self.help_page)
        help_layout.setContentsMargins(24, 20, 24, 20)
        help_title = QLabel("Application Help")
        help_title.setObjectName("app_title")
        help_layout.addWidget(help_title)
        self.help_browser = QTextBrowser()
        self.help_browser.setOpenExternalLinks(True)
        readme_path = Path(__file__).resolve().parents[2] / "README.md"
        if readme_path.is_file():
            self.help_browser.setMarkdown(
                readme_path.read_text(encoding="utf-8")
            )
        else:
            self.help_browser.setPlainText(
                "The README user guide is missing. Restore README.md beside the application."
            )
        help_layout.addWidget(self.help_browser, 1)
        self.pages.addWidget(self.help_page)

        self.create_workflow_footer()

        # -----------------------------------------------------
        # Add widgets to main layout
        # -----------------------------------------------------

        main_layout.addWidget(
            sidebar
        )

        content_layout = QVBoxLayout()
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        content_layout.addWidget(self.pages, 1)
        content_layout.addWidget(self.workflow_footer)
        main_layout.addLayout(content_layout, 1)

        # -----------------------------------------------------
        # Navigation event
        # -----------------------------------------------------

        self.navigation.currentRowChanged.connect(
            self.change_page
        )

        # Start on Dashboard
        self.navigation.setCurrentRow(
            0
        )
        saved_project = self.settings.value("last_project_id", type=int)
        if saved_project is not None and self.database.get_project(saved_project) is not None:
            self.open_project(saved_project)
        else:
            self.update_workflow_ui()

        # -----------------------------------------------------
        # Styling
        # -----------------------------------------------------

        self.setStyleSheet("""

            QMainWindow {
                background-color: #f5f7fa;
            }

            #sidebar {
                background-color: #172033;
            }

            #app_title {
                color: white;
                font-size: 22px;
                font-weight: bold;
            }

            #navigation {
                background-color: transparent;
                border: none;
                outline: none;
                color: #cbd5e1;
                font-size: 15px;
            }

            #navigation::item {
                padding: 8px 12px;
                margin: 2px 0;
                border-radius: 6px;
            }

            #navigation::item:hover {
                background-color: #25314a;
            }

            #navigation::item:selected {
                background-color: #2563eb;
                color: white;
            }

            #version {
                color: #64748b;
                font-size: 12px;
            }

            #page_title {
                color: #172033;
                font-size: 28px;
                font-weight: bold;
            }

            #page_subtitle {
                color: #64748b;
                font-size: 15px;
            }

            #card {
                background-color: white;
                border-radius: 10px;
                padding: 20px;
            }

            #card_title {
                color: #64748b;
                font-size: 14px;
            }

            #card_value {
                color: #172033;
                font-size: 28px;
                font-weight: bold;
            }

            #primary_button {
                background-color: #2563eb;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 10px 18px;
                font-size: 14px;
                font-weight: bold;
            }

            #primary_button:hover {
                background-color: #1d4ed8;
            }

            #danger_button {
                background-color: #b91c1c;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 10px 18px;
                font-size: 14px;
                font-weight: bold;
            }

            #danger_button:hover {
                background-color: #991b1b;
            }

            #project_list {
                background-color: white;
                border: none;
                border-radius: 10px;
                padding: 10px;
                font-size: 14px;
            }

            #project_list::item {
                padding: 15px;
                border-bottom: 1px solid #e5e7eb;
            }

            #project_list::item:selected {
                background-color: #eff6ff;
                color: #172033;
            }

            #data_table {
                background-color: white;
                border: 1px solid #e5e7eb;
                gridline-color: #e5e7eb;
                font-size: 13px;
            }

        """)

    # =========================================================
    # DASHBOARD
    # =========================================================

    def create_dashboard_page(self):

        page = QWidget()

        layout = QVBoxLayout(
            page
        )

        layout.setContentsMargins(
            40,
            35,
            40,
            35
        )

        layout.setSpacing(
            20
        )

        title = QLabel(
            "Dashboard"
        )

        title.setObjectName(
            "page_title"
        )

        layout.addWidget(
            title
        )

        subtitle = QLabel(
            "Manage your research projects and statistical analysis."
        )

        subtitle.setObjectName(
            "page_subtitle"
        )

        layout.addWidget(
            subtitle
        )

        layout.addSpacing(
            15
        )

        # -----------------------------------------------------
        # Statistics cards
        # -----------------------------------------------------

        cards_layout = QHBoxLayout()

        cards_layout.setSpacing(
            20
        )

        cards_layout.addWidget(
            self.create_stat_card(
                "Projects",
                "0",
                "projects",
            )
        )

        cards_layout.addWidget(
            self.create_stat_card(
                "Analyses",
                "0",
                "analyses",
            )
        )

        cards_layout.addWidget(
            self.create_stat_card(
                "Completed",
                "0",
                "completed",
            )
        )

        layout.addLayout(
            cards_layout
        )

        layout.addStretch()

        self.pages.addWidget(
            page
        )
        self.refresh_dashboard_metrics()

    # =========================================================
    # STATISTICS CARD
    # =========================================================

    def create_stat_card(
        self,
        title,
        value,
        metric_key=None,
    ):

        card = QFrame()

        card.setObjectName(
            "card"
        )

        layout = QVBoxLayout(
            card
        )

        title_label = QLabel(
            title
        )

        title_label.setObjectName(
            "card_title"
        )

        value_label = QLabel(
            value
        )

        value_label.setObjectName(
            "card_value"
        )

        layout.addWidget(
            title_label
        )

        layout.addWidget(
            value_label
        )

        if metric_key is not None:
            self.dashboard_metric_labels[metric_key] = value_label

        return card

    def refresh_dashboard_metrics(self, *_):
        metrics = self.database.get_dashboard_metrics()
        for metric, label in self.dashboard_metric_labels.items():
            label.setText(str(metrics[metric]))

    # =========================================================
    # PLACEHOLDER PAGE
    # =========================================================

    def create_placeholder_page(
        self,
        title_text,
        description
    ):
        page = QWidget()

        layout = QVBoxLayout(
            page
        )

        layout.setContentsMargins(
            40,
            35,
            40,
            35
        )

        title = QLabel(
            title_text
        )

        title.setObjectName(
            "page_title"
        )

        subtitle = QLabel(
            description
        )

        subtitle.setObjectName(
            "page_subtitle"
        )

        layout.addWidget(
            title
        )

        layout.addWidget(
            subtitle
        )

        layout.addStretch()

        self.pages.addWidget(
            page
        )

    # =========================================================
    # NAVIGATION
    # =========================================================

    def create_workflow_footer(self):
        self.workflow_footer = QFrame()
        self.workflow_footer.setObjectName("workflow_footer")
        layout = QVBoxLayout(self.workflow_footer)
        layout.setContentsMargins(24, 12, 24, 12)
        self.workflow_heading = QLabel()
        self.workflow_heading.setStyleSheet("font-weight: bold; font-size: 15px;")
        layout.addWidget(self.workflow_heading)
        self.workflow_explanation = QLabel()
        self.workflow_explanation.setWordWrap(True)
        self.workflow_explanation.setObjectName("page_subtitle")
        layout.addWidget(self.workflow_explanation)
        self.workflow_progress = QProgressBar()
        self.workflow_progress.setTextVisible(False)
        self.workflow_progress.setRange(0, len(self.workflow_pages))
        layout.addWidget(self.workflow_progress)
        buttons = QHBoxLayout()
        self.workflow_back = QPushButton("Back")
        self.workflow_back.clicked.connect(self.workflow_back_clicked)
        buttons.addWidget(self.workflow_back)
        buttons.addStretch()
        self.workflow_save = QPushButton("Save and exit")
        self.workflow_save.clicked.connect(self.save_workflow)
        buttons.addWidget(self.workflow_save)
        self.workflow_continue = QPushButton("Continue")
        self.workflow_continue.setObjectName("primary_button")
        self.workflow_continue.clicked.connect(self.continue_workflow)
        buttons.addWidget(self.workflow_continue)
        layout.addLayout(buttons)
        # Keep the workflow controls visible even before a project is opened.
        # The disabled state explains what to do next instead of making the
        # guided workflow appear to be missing.
        self.workflow_footer.setVisible(True)

    def update_workflow_ui(self):
        active = self.workflow_step >= 0 and self.data_page.current_project_id is not None
        if not active:
            self.workflow_footer.setVisible(True)
            self.workflow_heading.setText("Guided workflow")
            self.workflow_explanation.setText("Open or create a project to begin.")
            self.workflow_progress.setValue(0)
            self.workflow_back.setEnabled(False)
            self.workflow_save.setEnabled(False)
            self.workflow_continue.setText("Continue")
            self.workflow_continue.setEnabled(False)
            return
        self.workflow_footer.setVisible(True)
        self.workflow_save.setEnabled(True)
        self.workflow_continue.setEnabled(True)
        self.workflow_heading.setText(
            f"Step {self.workflow_step + 1} of {len(self.workflow_pages)}: "
            f"{self.workflow_titles[self.workflow_step]}"
        )
        explanations = [
            "Import the file you want to analyze. A protected snapshot is created automatically.",
            "Write the question your study is trying to answer. Add at least one question.",
            "State what you expect using a null hypothesis (H0) and alternative hypothesis (H1). Descriptive questions do not need hypotheses.",
            "Tell the app which columns are outcomes, predictors, or grouping variables.",
            "Choose the recommended test and run it. The result is saved with this dataset revision.",
            "Check the table, assumptions, warnings, and plain-English interpretation.",
            "Review the report and export it when the results are ready.",
        ]
        if self.workflow_step == 2:
            questions = self.database.get_project_research_questions(
                self.data_page.current_project_id
            )
            if questions and all(question["design_type"] == "descriptive" for question in questions):
                explanations[2] = (
                    "Your questions are descriptive, so no hypotheses are required. "
                    "Continue to generate trusted summaries of the observed data."
                )
        self.workflow_explanation.setText(explanations[self.workflow_step])
        self.workflow_progress.setValue(self.workflow_step + 1)
        self.workflow_back.setEnabled(self.workflow_step > 0)
        self.workflow_continue.setText(
            "Finish" if self.workflow_step == len(self.workflow_pages) - 1 else "Continue"
        )

    def set_workflow_step(self, step):
        self.workflow_step = max(0, min(step, len(self.workflow_pages) - 1))
        self.navigation.setCurrentRow(self.workflow_pages[self.workflow_step])
        self.update_workflow_ui()

    def workflow_back_clicked(self):
        if self.workflow_step > 0:
            self.set_workflow_step(self.workflow_step - 1)

    def save_workflow(self):
        if self.data_page.current_project_id is not None:
            self.settings.setValue("workflow_step", self.workflow_step)
        self.workflow_footer.setVisible(False)
        self.navigation.setCurrentRow(1)

    def continue_workflow(self):
        valid, message = self.workflow_prerequisite()
        if not valid:
            QMessageBox.warning(self, "Complete this step first", message)
            self.workflow_explanation.setText(message)
            return
        if self.workflow_step == len(self.workflow_pages) - 1:
            self.database.connection.execute(
                "UPDATE projects SET status = 'Completed', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (self.data_page.current_project_id,),
            )
            self.database.connection.commit()
            self.refresh_dashboard_metrics()
            QMessageBox.information(self, "Workflow complete", "Your project is ready to export.")
            return
        self.set_workflow_step(self.workflow_step + 1)

    def workflow_prerequisite(self):
        project_id = self.data_page.current_project_id
        if project_id is None:
            return False, "Select or create a project before continuing."
        if self.workflow_step == len(self.workflow_pages) - 1 and not self.export_done:
            return False, "Use Export Word or Export Excel to create the report before finishing."
        if self.workflow_step == 0:
            if self.data_page.current_dataset_id is None or self.data_page.current_dataframe is None:
                return False, "Import a dataset before continuing."
        elif self.workflow_step == 1:
            if not self.database.get_project_research_questions(project_id):
                return False, "Add at least one research question before continuing."
        elif self.workflow_step == 2:
            questions = self.database.get_project_research_questions(project_id)
            if not questions or any(
                question["design_type"] != "descriptive" and not any(
                    hypothesis["null_hypothesis"].strip()
                    and hypothesis["alternative_hypothesis"].strip()
                    for hypothesis in self.database.get_research_question_hypotheses(project_id, question["id"])
                )
                for question in questions
            ):
                return False, "Add complete H0 and H1 hypotheses for every non-descriptive research question."
        elif self.workflow_step == 3:
            required = {
                "descriptive": {"outcome"},
                "comparison": {"outcome", "grouping"},
                "association": {"outcome", "predictor"},
                "prediction": {"outcome", "predictor"},
            }
            for question in self.database.get_project_research_questions(project_id):
                roles = {
                    link["role"]
                    for link in self.database.get_question_variables(project_id, question["id"])
                    if link["dataset_id"] == self.data_page.current_dataset_id and link["variable_exists"]
                }
                if not required[question["design_type"]].issubset(roles):
                    return False, f"Link all required variables for {question['code']} before continuing."
        elif self.workflow_step in {4, 5}:
            if not any(
                self.database.get_question_analysis_runs(project_id, question["id"])
                for question in self.database.get_project_research_questions(project_id)
            ):
                return False, "Run at least one analysis before continuing."
        return True, ""

    def _analysis_completed(self, project_id, _question_id):
        if project_id == self.data_page.current_project_id and self.workflow_step == 4:
            QTimer.singleShot(250, lambda: self.set_workflow_step(5))

    def _export_completed(self, _path):
        self.export_done = True

    def _questions_changed(self, project_id):
        if project_id == self.data_page.current_project_id and self.workflow_step == 1:
            QTimer.singleShot(250, lambda: self.set_workflow_step(2))

    def open_time_series_window(self):
        if not hasattr(self, "time_series_window") or self.time_series_window is None:
            self.time_series_window = TimeSeriesWindow(self.database, self)
        self.time_series_window.show()
        self.time_series_window.raise_()
        self.time_series_window.activateWindow()

    def change_page(
        self,
        index
    ):
        if index == self.time_series_nav_index:
            self.open_time_series_window()
            self.navigation.blockSignals(True)
            self.navigation.setCurrentRow(self.last_page_index)
            self.navigation.blockSignals(False)
            return
        page_index = index if index < self.time_series_nav_index else index - 1
        if 0 <= page_index < self.pages.count():
            self.last_page_index = index
            self.pages.setCurrentIndex(page_index)
        if index == 0:
            self.refresh_dashboard_metrics()

    # =========================================================
    # OPEN PROJECT
    # =========================================================

    def open_project(
        self,
        project_id
    ):
        self.settings.setValue("last_project_id", project_id)
        self.workflow_step = 0
        self.export_done = False
        self.analysis_page.set_context(
            project_id,
            None,
            None,
        )
        self.research_questions_page.set_project(
            project_id
        )

        self.hypotheses_page.set_project(
            project_id
        )

        self.results_page.set_context(
            project_id,
            None,
            None,
        )
        self.chapter_four_page.set_project(project_id)
        self.export_page.set_project(project_id)
        self.qualitative_page.set_project(project_id)

        self.data_page.set_project(
            project_id
        )

        # Data is navigation item 2
        self.navigation.setCurrentRow(
            2
        )
        self.update_workflow_ui()

    def handle_project_deleted(self, project_id):
        if self.data_page.current_project_id != project_id:
            return
        self.settings.remove("last_project_id")
        self.workflow_step = -1
        self.export_done = False
        self.data_page.set_project(None)
        self.research_questions_page.set_project(None)
        self.hypotheses_page.set_project(None)
        self.analysis_page.set_context(None, None, None)
        self.results_page.set_context(None, None, None)
        self.chapter_four_page.set_project(None)
        self.export_page.set_project(None)
        self.qualitative_page.set_project(None)
        self.navigation.setCurrentRow(1)
        self.update_workflow_ui()

    def update_dataset_context(self, dataset_id, dataframe):
        self.research_questions_page.set_dataset(
            dataset_id,
            dataframe,
        )
        self.analysis_page.set_context(
            self.data_page.current_project_id,
            dataset_id,
            dataframe,
        )
        self.results_page.set_context(
            self.data_page.current_project_id,
            dataset_id,
            dataframe,
        )
        if (
            self.workflow_step == 0
            and dataset_id is not None
            and dataframe is not None
        ):
            QTimer.singleShot(250, lambda: self.set_workflow_step(1))

    # =========================================================
    # CLOSE APPLICATION
    # =========================================================

    def closeEvent(
        self,
        event
    ):

        self.database.close()

        event.accept()
