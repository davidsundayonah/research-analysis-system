import json

from PySide6.QtWidgets import QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QScrollArea, QVBoxLayout, QWidget


class PaperEntryDialog(QDialog):
    """One-respondent-at-a-time entry view using the shared schema validator."""

    def __init__(self, database, project_id, parent=None):
        super().__init__(parent)
        self.database = database
        self.project_id = project_id
        self.fields = {}
        self.loaded_record_id = None
        self.setWindowTitle("Paper Questionnaire Data Entry")
        self.resize(650, 700)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        self.schema_label = QLabel()
        self.schema_combo = QComboBox()
        self.schema_combo.currentIndexChanged.connect(self._load_schema)
        form = QFormLayout()
        form.addRow("Questionnaire", self.schema_combo)
        self.respondent = QLineEdit()
        self.respondent.setPlaceholderText("Example: R001")
        form.addRow("Respondent ID", self.respondent)
        self.respondent_search = QComboBox()
        self.respondent_search.setEditable(True)
        self.respondent_search.setPlaceholderText("Search or select a saved respondent")
        self.respondent_search.currentIndexChanged.connect(self.load_selected_record)
        form.addRow("Resume respondent", self.respondent_search)
        layout.addLayout(form)
        self.scroll = QScrollArea(); self.scroll.setWidgetResizable(True)
        self.form_widget = QWidget(); self.form_layout = QFormLayout(self.form_widget)
        self.scroll.setWidget(self.form_widget); layout.addWidget(self.scroll)
        self.progress = QLabel()
        layout.addWidget(self.progress)
        buttons = QHBoxLayout()
        save = QPushButton("Save response")
        save.clicked.connect(self.save)
        close = QPushButton("Close"); close.clicked.connect(self.accept)
        buttons.addWidget(save); buttons.addStretch(); buttons.addWidget(close)
        layout.addLayout(buttons)
        self._refresh_schemas()

    def _refresh_schemas(self):
        self.schema_combo.clear()
        for schema in self.database.get_project_questionnaire_schemas(self.project_id):
            self.schema_combo.addItem(f"{schema['title']} (v{schema['version']}, {schema['status']})", schema["id"])
        self._load_schema()

    def _load_schema(self):
        while self.form_layout.count():
            item = self.form_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        self.fields = {}
        self.loaded_record_id = None
        self.respondent_search.clear()
        schema_id = self.schema_combo.currentData()
        if schema_id is None:
            self.progress.setText("Create a questionnaire schema first.")
            return
        for question in self.database.get_questionnaire_questions(schema_id):
            field = QLineEdit()
            field.setPlaceholderText("Required" if question["required"] else "Optional")
            self.fields[question["variable_name"]] = field
            self.form_layout.addRow(question["prompt"], field)
        for record in self.database.get_paper_entry_records(schema_id):
            self.respondent_search.addItem(
                f"{record['respondent_id']} ({record['status']})", record["id"]
            )
        self._update_progress(schema_id)

    def load_selected_record(self, index):
        record_id = self.respondent_search.itemData(index)
        if record_id is None:
            return
        record = next((row for row in self.database.get_paper_entry_records(self.schema_combo.currentData()) if row["id"] == record_id), None)
        if record is None:
            return
        self.loaded_record_id = record_id
        self.respondent.setText(record["respondent_id"])
        responses = json.loads(record["responses_json"] or "{}")
        for name, field in self.fields.items():
            value = responses.get(name)
            field.setText("" if value is None else str(value))

    def _update_progress(self, schema_id):
        progress = self.database.get_paper_entry_progress(schema_id)
        self.progress.setText(
            f"Expected: {progress['expected'] or 'not specified'} | Entered: {progress['entered']} | "
            f"Complete: {progress['complete']} | Incomplete: {progress['incomplete']} | Invalid: {progress['invalid']}"
        )

    def save(self):
        schema_id = self.schema_combo.currentData()
        if schema_id is None:
            return
        try:
            record_id = self.loaded_record_id
            if record_id is None:
                record_id = self.database.create_paper_entry_record(self.project_id, schema_id, self.respondent.text())
            else:
                record = next((row for row in self.database.get_paper_entry_records(schema_id) if row["id"] == record_id), None)
                if record is None:
                    raise ValueError("The selected respondent record no longer exists.")
            responses = {name: field.text() for name, field in self.fields.items()}
            result = self.database.save_paper_entry_record(record_id, responses)
            self.loaded_record_id = record_id
            self._update_progress(schema_id)
            if result["valid"]:
                QMessageBox.information(self, "Saved", f"Respondent saved as {result['status']}.")
            else:
                QMessageBox.warning(self, "Saved with validation warnings", "The record was preserved for review:\n" + "\n".join(result["errors"]))
        except ValueError as error:
            QMessageBox.warning(self, "Cannot save response", str(error))
