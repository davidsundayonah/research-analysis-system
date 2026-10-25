from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QVBoxLayout,
)


class VariableMetadataDialog(QDialog):
    MEASURES = ["", "nominal", "ordinal", "scale"]

    def __init__(self, variable_name, metadata=None, parent=None):
        super().__init__(parent)
        metadata = metadata or {}
        self.setWindowTitle(f"Variable Coding: {variable_name}")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "Use this like SPSS Variable View: keep the stored codes in the data, "
            "and attach readable labels for people and reports."
        ))
        form = QFormLayout()
        self.label_input = QLineEdit(metadata.get("label") or variable_name)
        form.addRow("Variable label", self.label_input)
        self.measure_input = QComboBox()
        self.measure_input.addItems(self.MEASURES)
        self.measure_input.setCurrentText(metadata.get("measure") or "")
        form.addRow("Measure", self.measure_input)
        self.value_labels_input = QPlainTextEdit()
        self.value_labels_input.setPlaceholderText(
            'One mapping per line, for example:\n1 = Strongly disagree\n2 = Disagree\n5 = Strongly agree'
        )
        current = metadata.get("value_labels") or {}
        self.value_labels_input.setPlainText(
            "\n".join(f"{key} = {value}" for key, value in current.items())
        )
        form.addRow("Value labels", self.value_labels_input)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept_metadata)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.error_label = QLabel()
        self.error_label.setStyleSheet("color: #b91c1c;")
        layout.addWidget(self.error_label)

    def accept_metadata(self):
        labels = {}
        for line in self.value_labels_input.toPlainText().splitlines():
            if not line.strip():
                continue
            if "=" not in line:
                self.error_label.setText("Each value label must use: code = label")
                return
            key, value = line.split("=", 1)
            if not key.strip() or not value.strip():
                self.error_label.setText("Codes and labels cannot be empty.")
                return
            labels[key.strip()] = value.strip()
        self._metadata = {
            "label": self.label_input.text().strip(),
            "measure": self.measure_input.currentText(),
            "value_labels": labels,
        }
        self.accept()

    def get_metadata(self):
        return self._metadata
