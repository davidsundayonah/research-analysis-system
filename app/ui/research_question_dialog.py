from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QSpinBox,
    QVBoxLayout,
)


class ResearchQuestionDialog(QDialog):
    DESIGN_TYPES = [
        "descriptive",
        "comparison",
        "association",
        "prediction",
    ]

    def __init__(self, question=None, position=1, parent=None):
        super().__init__(parent)
        self.setWindowTitle(
            "Edit Research Question" if question else "New Research Question"
        )

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.code_input = QLineEdit(
            question["code"] if question else ""
        )
        self.code_input.setPlaceholderText("Auto-assigned when blank")
        form.addRow("Question code", self.code_input)

        self.position_input = QSpinBox()
        self.position_input.setRange(1, 10000)
        self.position_input.setValue(
            int(question["position"]) if question else position
        )
        form.addRow("Order", self.position_input)

        self.question_input = QPlainTextEdit(
            question["question"] if question else ""
        )
        self.question_input.setPlaceholderText("Enter the research question")
        form.addRow("Question", self.question_input)

        self.design_input = QComboBox()
        self.design_input.addItems(self.DESIGN_TYPES)
        if question:
            self.design_input.setCurrentText(question["design_type"])
        form.addRow("Design", self.design_input)

        self.proposed_test_input = QLineEdit(
            question["proposed_test"] if question else ""
        )
        self.proposed_test_input.setPlaceholderText(
            "Optional planned statistical test"
        )
        form.addRow("Proposed test", self.proposed_test_input)

        self.validation_label = QLabel("Question text is required.")
        self.question_input.textChanged.connect(self.update_validation)

        layout.addLayout(form)
        layout.addWidget(self.validation_label)
        buttons = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.update_validation()

    def update_validation(self):
        self.validation_label.setText(
            "" if self.question_input.toPlainText().strip()
            else "Question text is required."
        )

    def validate_and_accept(self):
        if not self.question_input.toPlainText().strip():
            self.update_validation()
            self.question_input.setFocus()
            return
        self.accept()

    def get_question_data(self):
        return {
            "question": self.question_input.toPlainText().strip(),
            "code": self.code_input.text().strip() or None,
            "position": self.position_input.value(),
            "design_type": self.design_input.currentText(),
            "proposed_test": self.proposed_test_input.text().strip(),
        }