from PySide6.QtWidgets import QCheckBox, QComboBox, QDialog, QDialogButtonBox, QLabel, QTableWidget, QTableWidgetItem, QVBoxLayout

from app.import_workflow import inspect_import, validate_import


class ImportReviewDialog(QDialog):
    """Review explicit spreadsheet-to-questionnaire mappings before snapshotting."""

    def __init__(self, dataframe, questions, parent=None):
        super().__init__(parent)
        self.dataframe = dataframe
        self.questions = questions
        self.setWindowTitle("Review spreadsheet import")
        self.resize(800, 550)
        layout = QVBoxLayout(self)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.table = QTableWidget(len(questions), 3)
        self.table.setHorizontalHeaderLabels(["Question variable", "Spreadsheet column", "Required"])
        self.combos = {}
        columns = [""] + [str(column) for column in dataframe.columns]
        for row, question in enumerate(questions):
            self.table.setItem(row, 0, QTableWidgetItem(question["variable_name"]))
            combo = QComboBox(); combo.addItems(columns)
            suggested = next((index for index, value in enumerate(columns) if value == question["variable_name"]), 0)
            combo.setCurrentIndex(suggested)
            self.table.setCellWidget(row, 1, combo)
            self.table.setItem(row, 2, QTableWidgetItem("Yes" if question["required"] else "No"))
            self.combos[question["variable_name"]] = combo
        layout.addWidget(self.table)
        self.keep_unmapped = QCheckBox("Retain unexpected columns for explicit review")
        self.keep_unmapped.setChecked(True)
        layout.addWidget(self.keep_unmapped)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self._accept_review)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self._refresh_summary()

    def _mapping(self):
        return {name: combo.currentText() for name, combo in self.combos.items() if combo.currentText()}

    def _refresh_summary(self):
        report = inspect_import(self.dataframe, self.questions, self._mapping())
        self.summary.setText(
            f"Rows: {report['row_count']:,} | Columns: {report['column_count']:,} | "
            f"Missing expected: {len(report['missing_expected'])} | Unexpected: {len(report['unexpected_columns'])}"
        )

    def _accept_review(self):
        report = validate_import(self.dataframe, self.questions, self._mapping())
        if report["missing_expected"]:
            self.summary.setText("Missing expected variables: " + ", ".join(report["missing_expected"]))
            return
        self.accept()

    def get_mapping(self):
        return self._mapping(), self.keep_unmapped.isChecked()
