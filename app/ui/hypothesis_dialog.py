from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QPlainTextEdit,
    QVBoxLayout,
)


class HypothesisDialog(QDialog):
    def __init__(self, hypothesis=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Hypotheses" if hypothesis else "New Hypotheses")

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.null_input = QPlainTextEdit(
            hypothesis["null_hypothesis"] if hypothesis else ""
        )
        self.null_input.setPlaceholderText("Null hypothesis (H0)")
        form.addRow("Null (H0)", self.null_input)

        self.alternative_input = QPlainTextEdit(
            hypothesis["alternative_hypothesis"] if hypothesis else ""
        )
        self.alternative_input.setPlaceholderText(
            "Alternative hypothesis (H1)"
        )
        form.addRow("Alternative (H1)", self.alternative_input)

        self.direction_input = QComboBox()
        self.direction_input.addItem("Non-directional", "non-directional")
        self.direction_input.addItem("Directional", "directional")
        if hypothesis:
            index = self.direction_input.findData(hypothesis["directionality"])
            if index >= 0:
                self.direction_input.setCurrentIndex(index)
        form.addRow("Direction", self.direction_input)

        self.warning_label = QLabel()
        self.null_input.textChanged.connect(self.update_warning)
        self.alternative_input.textChanged.connect(self.update_warning)

        layout.addLayout(form)
        layout.addWidget(self.warning_label)
        buttons = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.update_warning()

    def update_warning(self):
        if not self.null_input.toPlainText().strip() or not (
            self.alternative_input.toPlainText().strip()
        ):
            self.warning_label.setText(
                "This hypothesis is incomplete until both H0 and H1 are provided."
            )
        else:
            self.warning_label.setText("")

    def get_hypothesis_data(self):
        return {
            "null_hypothesis": self.null_input.toPlainText().strip(),
            "alternative_hypothesis": (
                self.alternative_input.toPlainText().strip()
            ),
            "directionality": self.direction_input.currentData(),
        }