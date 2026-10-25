from PySide6.QtWidgets import (
    QLabel,
    QPushButton,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)


class ChapterFourPage(QWidget):
    def __init__(self, report_generator):
        super().__init__()
        self.report_generator = report_generator
        self.project_id = None
        self.report = None

        layout = QVBoxLayout(self)
        title = QLabel("Chapter Four")
        title.setObjectName("page_title")
        layout.addWidget(title)

        self.context_label = QLabel("Select a project to generate Chapter Four.")
        self.context_label.setObjectName("page_subtitle")
        layout.addWidget(self.context_label)

        self.generate_button = QPushButton("Generate Chapter Four Preview")
        self.generate_button.setObjectName("primary_button")
        self.generate_button.clicked.connect(self.generate_preview)
        layout.addWidget(self.generate_button)

        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setPlaceholderText(
            "The report preview will use saved statistical results and current descriptive summaries."
        )
        layout.addWidget(self.preview, 1)

        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

    def set_project(self, project_id):
        self.project_id = project_id
        project = (
            self.report_generator.database.get_project(project_id)
            if project_id is not None
            else None
        )
        self.context_label.setText(
            f"Project: {project['name']}" if project else "Select a project to generate Chapter Four."
        )
        self.generate_button.setEnabled(project is not None)
        self.report = None
        self.preview.clear()
        self.status_label.clear()

    def generate_preview(self):
        if self.project_id is None:
            self.status_label.setText("Select a project first.")
            return None
        try:
            self.report = self.report_generator.generate(self.project_id)
        except (OSError, ValueError, RuntimeError) as error:
            self.status_label.setText(f"Report generation failed: {error}")
            return None

        self.preview.setPlainText(self.report.preview_text())
        self.status_label.setText(
            f"Generated {len(self.report.sections)} sections and "
            f"{len(self.report.source_analysis_ids)} saved analysis table(s)."
        )
        return self.report
