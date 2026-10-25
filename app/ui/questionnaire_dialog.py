from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox, QDialog, QFileDialog, QFormLayout, QGroupBox, QLabel,
    QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QSpinBox,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QHBoxLayout,
)

from app.questionnaire import generate_blank_template
from app.document_extraction import extract_questionnaire


class QuestionnaireDialog(QDialog):
    """Small manual questionnaire builder backed by the project database."""

    def __init__(self, database, project_id, parent=None):
        super().__init__(parent)
        self.database = database
        self.project_id = project_id
        self.schema_id = None
        self.setWindowTitle("Questionnaire Builder")
        self.resize(850, 650)
        self._build_ui()
        self._refresh_schemas()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.title = QLineEdit()
        self.title.setPlaceholderText("Example: Student questionnaire")
        self.expected = QSpinBox()
        self.expected.setRange(0, 2_000_000)
        self.expected.setSpecialValueText("Not specified")
        self.instructions = QPlainTextEdit()
        self.instructions.setMaximumHeight(70)
        form.addRow("Title", self.title)
        form.addRow("Expected questionnaires", self.expected)
        form.addRow("Instructions", self.instructions)
        layout.addLayout(form)
        self.create_button = QPushButton("Create new schema")
        self.create_button.clicked.connect(self.create_schema)
        layout.addWidget(self.create_button)
        self.extract_button = QPushButton("Extract questions from TXT/DOCX/PDF/image")
        self.extract_button.clicked.connect(self.extract_document)
        layout.addWidget(self.extract_button)

        question_box = QGroupBox("Add question")
        qform = QFormLayout(question_box)
        self.prompt = QLineEdit()
        self.variable = QLineEdit()
        self.question_type = QComboBox()
        self.question_type.addItems([
            "short_text", "long_text", "integer", "decimal", "yes_no",
            "single_choice", "multiple_choice", "likert", "ordinal", "nominal", "identifier",
        ])
        self.measure = QComboBox()
        self.measure.addItems(["text", "nominal", "ordinal", "scale", "identifier", "datetime"])
        self.options = QLineEdit()
        self.options.setPlaceholderText("For choices: value=label, value=label")
        self.required = QComboBox()
        self.required.addItems(["Optional", "Required"])
        self.add_button = QPushButton("Add question")
        self.add_button.clicked.connect(self.add_question)
        qform.addRow("Question wording", self.prompt)
        qform.addRow("Variable name", self.variable)
        qform.addRow("Question type", self.question_type)
        qform.addRow("Measurement level", self.measure)
        qform.addRow("Allowed choices", self.options)
        qform.addRow("Required", self.required)
        qform.addRow(self.add_button)
        layout.addWidget(question_box)
        self.questions = QTableWidget(0, 5)
        self.questions.setHorizontalHeaderLabels(["Variable", "Wording", "Type", "Measure", "Required"])
        layout.addWidget(self.questions)

        buttons = QHBoxLayout()
        self.approve_button = QPushButton("Approve schema")
        self.approve_button.clicked.connect(self.approve_schema)
        self.template_button = QPushButton("Generate blank template")
        self.template_button.clicked.connect(self.generate_template)
        buttons.addWidget(self.approve_button)
        buttons.addWidget(self.template_button)
        buttons.addStretch()
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        layout.addLayout(buttons)
        self.status = QLabel("Create a schema before adding questions.")
        layout.addWidget(self.status)

    def _refresh_schemas(self):
        schemas = self.database.get_project_questionnaire_schemas(self.project_id)
        if schemas:
            self.schema_id = schemas[0]["id"]
            self.title.setText(schemas[0]["title"])
            self.status.setText(f"Editing draft schema version {schemas[0]['version']}. Approved schemas are read-only.")
            self._refresh_questions()

    def create_schema(self):
        try:
            self.schema_id = self.database.create_questionnaire_schema(
                self.project_id, self.title.text(), self.instructions.toPlainText(), self.expected.value() or None
            )
            self._refresh_questions()
            self.status.setText("Schema created. Add questions, then approve it.")
        except ValueError as error:
            QMessageBox.warning(self, "Cannot create schema", str(error))

    @staticmethod
    def _parse_options(text):
        if not text.strip():
            return []
        values = []
        for part in text.split(","):
            if "=" in part:
                value, label = part.split("=", 1)
                values.append({"value": value.strip(), "label": label.strip()})
            else:
                values.append({"value": part.strip(), "label": part.strip()})
        return values

    def add_question(self):
        if self.schema_id is None:
            QMessageBox.warning(self, "No schema", "Create a questionnaire schema first.")
            return
        try:
            self.database.add_questionnaire_question(
                self.schema_id, self.prompt.text(), self.variable.text(), self.question_type.currentText(),
                "integer" if self.question_type.currentText() in {"integer", "likert", "ordinal"} else "text",
                self.measure.currentText(), options=self._parse_options(self.options.text()),
                required=self.required.currentText() == "Required",
            )
            self.prompt.clear(); self.variable.clear(); self.options.clear()
            self._refresh_questions()
        except ValueError as error:
            QMessageBox.warning(self, "Cannot add question", str(error))

    def extract_document(self):
        if self.schema_id is None:
            QMessageBox.warning(self, "No schema", "Create a draft schema before extracting questions.")
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Select blank questionnaire", "",
            "Questionnaires (*.txt *.docx *.pdf *.jpg *.jpeg *.png)",
        )
        if not path:
            return
        try:
            result = extract_questionnaire(path)
            existing = {row["variable_name"] for row in self.database.get_questionnaire_questions(self.schema_id)}
            added = 0
            for question in result["questions"]:
                from app.questionnaire import safe_variable_name
                variable = safe_variable_name(f"Q{question['question_number']}", existing)
                self.database.add_questionnaire_question(
                    self.schema_id, question["prompt"], variable,
                    question_type="single_choice" if question.get("options") else "short_text",
                    data_type="text", measure="nominal" if question.get("options") else "text",
                    question_number=question.get("question_number", ""), section=question.get("section", ""),
                    options=question.get("options") or [], notes=question.get("warning", ""),
                )
                existing.add(variable); added += 1
            self._refresh_questions()
            QMessageBox.information(self, "Extraction ready for review", f"Added {added} extracted question candidates from {result['source_type']}. Review and correct them before approval.")
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "Questionnaire extraction", str(error))

    def _refresh_questions(self):
        if self.schema_id is None:
            return
        rows = self.database.get_questionnaire_questions(self.schema_id)
        self.questions.setRowCount(len(rows))
        for index, row in enumerate(rows):
            for column, value in enumerate((row["variable_name"], row["prompt"], row["question_type"], row["measure"], "Yes" if row["required"] else "No")):
                self.questions.setItem(index, column, QTableWidgetItem(str(value)))
        self.questions.resizeColumnsToContents()

    def approve_schema(self):
        try:
            self.database.approve_questionnaire_schema(self.schema_id)
            self.status.setText("Schema approved and versioned. Create a new version for edits.")
            self.add_button.setEnabled(False)
            self.approve_button.setEnabled(False)
        except (TypeError, ValueError) as error:
            QMessageBox.warning(self, "Cannot approve schema", str(error))

    def generate_template(self):
        if self.schema_id is None:
            QMessageBox.warning(self, "No schema", "Create a questionnaire schema first.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save blank template", "questionnaire_template.xlsx", "Templates (*.xlsx *.csv)")
        if not path:
            return
        try:
            schema = self.database.get_questionnaire_schema(self.schema_id)
            generate_blank_template(self.database.get_questionnaire_questions(self.schema_id), Path(path), schema["expected_sample_size"])
            QMessageBox.information(self, "Template created", f"Blank template saved to {path}.")
        except (OSError, ValueError) as error:
            QMessageBox.critical(self, "Template error", str(error))
