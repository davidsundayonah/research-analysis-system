from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from app.qualitative_tools import anonymize_text, import_transcript


class QualitativePage(QWidget):
    """Beginner-friendly storage and manual coding for interview material."""

    def __init__(self, database):
        super().__init__()
        self.database = database
        self.project_id = None
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        self.heading = QLabel("Interview guide and thematic analysis")
        self.heading.setObjectName("page_title")
        layout.addWidget(self.heading)
        self.status = QLabel("Select a project to begin.")
        self.status.setObjectName("page_subtitle")
        layout.addWidget(self.status)

        guide_box = QGroupBox("1. Store the interview guide")
        guide_form = QFormLayout(guide_box)
        self.guide_title = QLineEdit()
        self.guide_title.setPlaceholderText("Example: Semi-structured student interview guide")
        self.guide_content = QPlainTextEdit()
        self.guide_content.setPlaceholderText(
            "Paste any number of questions and interviewer prompts here. "
            "Use one question per line or include your full guide. There is no question limit."
        )
        self.guide_help = QLabel(
            "You can save a guide with any number of questions or prompts. "
            "Add as many participant transcripts and coded responses as needed."
        )
        self.guide_help.setWordWrap(True)
        self.save_guide_button = QPushButton("Save interview guide")
        self.save_guide_button.clicked.connect(self.save_guide)
        guide_form.addRow("Title", self.guide_title)
        guide_form.addRow(self.guide_help)
        guide_form.addRow("Questions and prompts", self.guide_content)
        guide_form.addRow(self.save_guide_button)
        layout.addWidget(guide_box)

        transcript_box = QGroupBox("2. Add an interview transcript")
        transcript_form = QFormLayout(transcript_box)
        self.participant = QLineEdit()
        self.source_name = QLineEdit()
        self.transcript_content = QPlainTextEdit()
        self.transcript_content.setPlaceholderText("Paste one participant transcript here.")
        self.add_transcript_button = QPushButton("Save transcript")
        self.add_transcript_button.clicked.connect(self.add_transcript)
        self.import_transcript_button = QPushButton("Import transcript file")
        self.import_transcript_button.clicked.connect(self.import_transcript_file)
        self.anonymize_transcript = QPushButton("Anonymise pasted transcript")
        self.anonymize_transcript.clicked.connect(self.anonymize_current_transcript)
        transcript_form.addRow("Participant ID", self.participant)
        transcript_form.addRow("Source name", self.source_name)
        transcript_form.addRow("Transcript", self.transcript_content)
        transcript_form.addRow(self.import_transcript_button, self.anonymize_transcript)
        transcript_form.addRow(self.add_transcript_button)
        layout.addWidget(transcript_box)

        code_box = QGroupBox("3. Create codes and themes")
        code_form = QFormLayout(code_box)
        self.code_input = QLineEdit()
        self.theme_input = QLineEdit()
        self.description_input = QLineEdit()
        self.add_code_button = QPushButton("Save code")
        self.add_code_button.clicked.connect(self.add_code)
        code_form.addRow("Code", self.code_input)
        code_form.addRow("Theme", self.theme_input)
        code_form.addRow("Meaning", self.description_input)
        code_form.addRow(self.add_code_button)
        layout.addWidget(code_box)

        coding_box = QGroupBox("4. Code an excerpt")
        coding_form = QFormLayout(coding_box)
        self.transcript_combo = QComboBox()
        self.code_combo = QComboBox()
        self.excerpt_input = QPlainTextEdit()
        self.note_input = QLineEdit()
        self.coder_input = QLineEdit("primary")
        self.add_coding_button = QPushButton("Save coded excerpt")
        self.add_coding_button.clicked.connect(self.add_coding)
        coding_form.addRow("Transcript", self.transcript_combo)
        coding_form.addRow("Code", self.code_combo)
        coding_form.addRow("Exact excerpt", self.excerpt_input)
        coding_form.addRow("Analyst note", self.note_input)
        coding_form.addRow("Coder ID", self.coder_input)
        coding_form.addRow(self.add_coding_button)
        layout.addWidget(coding_box)

        self.summary_table = QTableWidget(0, 4)
        self.summary_table.setHorizontalHeaderLabels(["Theme", "Code", "Meaning", "Coded excerpts"])
        layout.addWidget(QLabel("Theme summary"))
        layout.addWidget(self.summary_table, 1)
        self.set_enabled(False)

    def set_enabled(self, enabled):
        for widget in (
            self.guide_title, self.guide_content, self.save_guide_button,
            self.participant, self.source_name, self.transcript_content,
            self.add_transcript_button, self.import_transcript_button, self.anonymize_transcript,
            self.code_input, self.theme_input,
            self.description_input, self.add_code_button, self.transcript_combo,
            self.code_combo, self.excerpt_input, self.note_input,
            self.coder_input, self.add_coding_button,
        ):
            widget.setEnabled(enabled)

    def set_project(self, project_id):
        self.project_id = project_id
        self.set_enabled(project_id is not None)
        if project_id is None:
            self.status.setText("Select a project to begin.")
            return
        self.status.setText("Store the guide, add transcripts, create a codebook, and code exact excerpts. This is manual thematic analysis; no themes are invented automatically.")
        guide = self.database.get_interview_guide(project_id)
        self.guide_title.setText(guide["title"] if guide else "")
        self.guide_content.setPlainText(guide["content"] if guide else "")
        self.refresh_lists()

    def require_project(self):
        if self.project_id is None:
            QMessageBox.warning(self, "No project", "Open a project before using qualitative analysis.")
            return False
        return True

    def save_guide(self):
        if not self.require_project(): return
        try:
            self.database.save_interview_guide(self.project_id, self.guide_title.text(), self.guide_content.toPlainText())
            self.status.setText("Interview guide saved to this project.")
        except ValueError as error:
            QMessageBox.warning(self, "Guide not saved", str(error))

    def add_transcript(self):
        if not self.require_project(): return
        try:
            self.database.create_interview_transcript(self.project_id, self.participant.text(), self.source_name.text(), self.transcript_content.toPlainText())
            self.participant.clear(); self.source_name.clear(); self.transcript_content.clear()
            self.refresh_lists()
        except ValueError as error:
            QMessageBox.warning(self, "Transcript not saved", str(error))

    def import_transcript_file(self):
        if not self.require_project(): return
        path, _ = QFileDialog.getOpenFileName(self, "Import transcript", "", "Text transcript (*.txt *.md *.rtf)")
        if not path: return
        try:
            self.source_name.setText(path)
            self.transcript_content.setPlainText(import_transcript(path))
            self.status.setText("Transcript loaded for review. It has not been saved yet.")
        except (OSError, UnicodeError, ValueError) as error:
            QMessageBox.warning(self, "Transcript not loaded", str(error))

    def anonymize_current_transcript(self):
        self.transcript_content.setPlainText(anonymize_text(self.transcript_content.toPlainText()))
        self.status.setText("Common email and phone identifiers were masked. Review the text before saving.")

    def add_code(self):
        if not self.require_project(): return
        try:
            self.database.create_qualitative_code(self.project_id, self.code_input.text(), self.theme_input.text(), self.description_input.text())
            self.code_input.clear(); self.theme_input.clear(); self.description_input.clear()
            self.refresh_lists()
        except ValueError as error:
            QMessageBox.warning(self, "Code not saved", str(error))

    def add_coding(self):
        if not self.require_project(): return
        try:
            self.database.create_transcript_coding(self.project_id, self.transcript_combo.currentData(), self.code_combo.currentData(), self.excerpt_input.toPlainText(), self.note_input.text(), self.coder_input.text())
            self.excerpt_input.clear(); self.note_input.clear()
            self.refresh_lists()
        except ValueError as error:
            QMessageBox.warning(self, "Excerpt not saved", str(error))

    def refresh_lists(self):
        if self.project_id is None: return
        transcripts = self.database.get_interview_transcripts(self.project_id)
        codes = self.database.get_qualitative_codes(self.project_id)
        self.transcript_combo.clear()
        for row in transcripts:
            self.transcript_combo.addItem(f"{row['participant_id']} - {row['source_name']}", row['id'])
        self.code_combo.clear()
        for row in codes:
            self.code_combo.addItem(f"{row['theme']} / {row['code']}", row['id'])
        summary = self.database.get_qualitative_summary(self.project_id)
        self.summary_table.setRowCount(len(summary))
        for index, row in enumerate(summary):
            for column, value in enumerate((row['theme'], row['code'], row['description'], row['coded_excerpts'])):
                self.summary_table.setItem(index, column, QTableWidgetItem(str(value)))
