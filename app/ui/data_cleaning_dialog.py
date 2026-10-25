from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QSpinBox,
    QVBoxLayout,
)


class DataCleaningDialog(QDialog):

    def __init__(
        self,
        dataframe,
        parent=None
    ):
        super().__init__(parent)

        self.dataframe = dataframe

        self.setWindowTitle(
            "Data Cleaning"
        )

        self.resize(
            500,
            350
        )

        self.setup_ui()

    # =========================================================
    # UI
    # =========================================================

    def setup_ui(self):

        layout = QVBoxLayout(
            self
        )

        title = QLabel(
            "Data Cleaning & Coding"
        )

        title.setStyleSheet(
            """
            font-size: 20px;
            font-weight: bold;
            """
        )

        layout.addWidget(
            title
        )

        form = QFormLayout()

        # -----------------------------------------------------
        # Variable
        # -----------------------------------------------------

        self.variable_combo = QComboBox()

        self.variable_combo.addItems(
            [
                str(column)
                for column in self.dataframe.columns
            ]
        )

        form.addRow(
            "Variable:",
            self.variable_combo
        )

        # -----------------------------------------------------
        # Operation
        # -----------------------------------------------------

        self.operation_combo = QComboBox()

        self.operation_combo.addItems(
            [
                "Rename Variable",
                "Recode Values",
                "Define Missing Values",
                "Reverse Score",
                "Create Range Groups",
            ]
        )

        form.addRow(
            "Operation:",
            self.operation_combo
        )

        # -----------------------------------------------------
        # New variable
        # -----------------------------------------------------

        self.new_variable = QLineEdit()

        self.new_variable.setPlaceholderText(
            "Optional"
        )

        form.addRow(
            "New Variable:",
            self.new_variable
        )

        # -----------------------------------------------------
        # Mapping
        # -----------------------------------------------------

        self.mapping = QLineEdit()

        self.mapping.setPlaceholderText(
            "Example: 1=5,2=4 or 1-10=1,11-20=2"
        )

        form.addRow(
            "Mapping:",
            self.mapping
        )

        # -----------------------------------------------------
        # Minimum
        # -----------------------------------------------------

        self.minimum = QSpinBox()

        self.minimum.setRange(
            -100000,
            100000
        )

        self.minimum.setValue(
            1
        )

        form.addRow(
            "Minimum:",
            self.minimum
        )

        # -----------------------------------------------------
        # Maximum
        # -----------------------------------------------------

        self.maximum = QSpinBox()

        self.maximum.setRange(
            -100000,
            100000
        )

        self.maximum.setValue(
            5
        )

        form.addRow(
            "Maximum:",
            self.maximum
        )

        layout.addLayout(
            form
        )

        # -----------------------------------------------------
        # Buttons
        # -----------------------------------------------------

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok
            | QDialogButtonBox.Cancel
        )

        buttons.accepted.connect(
            self.accept
        )

        buttons.rejected.connect(
            self.reject
        )

        layout.addWidget(
            buttons
        )

    # =========================================================
    # GET DATA
    # =========================================================

    def get_operation_data(self):

        operation = (
            self.operation_combo
            .currentText()
        )

        variable = (
            self.variable_combo
            .currentText()
        )

        new_variable = (
            self.new_variable
            .text()
            .strip()
        )

        return {
            "operation": operation,
            "variable": variable,
            "new_variable": new_variable,
            "mapping": self.mapping.text().strip(),
            "minimum": self.minimum.value(),
            "maximum": self.maximum.value(),
        }
