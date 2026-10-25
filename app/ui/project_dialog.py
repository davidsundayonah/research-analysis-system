from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QComboBox,
    QFormLayout,
    QLineEdit,
    QVBoxLayout,
)


class ProjectDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.setWindowTitle("Create New Project")
        self.resize(500, 350)

        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)

        form = QFormLayout()

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText(
            "e.g. Social Media and Academic Performance"
        )

        self.title_input = QLineEdit()
        self.title_input.setPlaceholderText(
            "Full research title"
        )

        self.researcher_input = QLineEdit()
        self.researcher_input.setPlaceholderText(
            "Researcher's name"
        )

        self.institution_input = QLineEdit()
        self.institution_input.setPlaceholderText(
            "University / Institution"
        )

        self.department_input = QLineEdit()
        self.department_input.setPlaceholderText(
            "Department"
        )

        self.significance_input = QDoubleSpinBox()
        self.significance_input.setRange(0.001, 0.999)
        self.significance_input.setSingleStep(0.01)
        self.significance_input.setValue(0.05)
        self.significance_input.setDecimals(3)

        self.multiplicity_input = QComboBox()
        self.multiplicity_input.addItem("Holm (recommended)", "holm")
        self.multiplicity_input.addItem("Bonferroni", "bonferroni")
        self.multiplicity_input.addItem("Benjamini-Hochberg (FDR)", "fdr_bh")
        self.multiplicity_input.addItem("None (not recommended)", "none")

        form.addRow("Project Name *", self.name_input)
        form.addRow("Research Title", self.title_input)
        form.addRow("Researcher", self.researcher_input)
        form.addRow("Institution", self.institution_input)
        form.addRow("Department", self.department_input)
        form.addRow(
            "Significance Level",
            self.significance_input,
        )
        form.addRow("Multiple-testing correction", self.multiplicity_input)

        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Save |
            QDialogButtonBox.Cancel
        )

        buttons.accepted.connect(self.validate_and_accept)
        buttons.rejected.connect(self.reject)

        layout.addWidget(buttons)

    def validate_and_accept(self):
        if not self.name_input.text().strip():
            self.name_input.setFocus()
            return

        self.accept()

    def get_project_data(self):
        return {
            "name": self.name_input.text().strip(),
            "research_title": self.title_input.text().strip(),
            "researcher": self.researcher_input.text().strip(),
            "institution": self.institution_input.text().strip(),
            "department": self.department_input.text().strip(),
            "significance_level": self.significance_input.value(),
            "multiplicity_method": self.multiplicity_input.currentData(),
        }
