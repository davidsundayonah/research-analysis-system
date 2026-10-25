from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.ui.hypothesis_dialog import HypothesisDialog


class HypothesesPage(QWidget):
    def __init__(self, database):
        super().__init__()

        self.database = database
        self.current_project_id = None

        layout = QVBoxLayout(self)
        header = QHBoxLayout()

        title = QLabel("Hypotheses")
        title.setObjectName("page_title")
        header.addWidget(title)
        header.addStretch()

        self.add_button = QPushButton("+ Add Hypothesis")
        self.add_button.setObjectName("primary_button")
        self.add_button.clicked.connect(self.add_hypothesis)
        header.addWidget(self.add_button)

        self.edit_button = QPushButton("Edit")
        self.edit_button.clicked.connect(self.edit_hypothesis)
        header.addWidget(self.edit_button)

        self.delete_button = QPushButton("Delete")
        self.delete_button.clicked.connect(self.delete_hypothesis)
        header.addWidget(self.delete_button)

        layout.addLayout(header)

        self.project_label = QLabel("Select a project first.")
        self.project_label.setObjectName("page_subtitle")
        layout.addWidget(self.project_label)

        self.question_combo = QComboBox()
        self.question_combo.currentIndexChanged.connect(
            self.load_hypotheses
        )
        layout.addWidget(self.question_combo)

        self.hypothesis_list = QListWidget()
        self.hypothesis_list.itemSelectionChanged.connect(
            self.update_action_state
        )
        layout.addWidget(self.hypothesis_list)

        self.validation_warning = QLabel()
        self.validation_warning.setWordWrap(True)
        layout.addWidget(self.validation_warning)

        self.set_project(None)

    def set_project(self, project_id):
        self.current_project_id = project_id
        self.hypothesis_list.clear()
        self.question_combo.blockSignals(True)
        self.question_combo.clear()

        if project_id is None:
            self.project_label.setText("Select a project first.")
        else:
            project = self.database.get_project(project_id)
            project_name = project["name"] if project else "Unknown project"
            self.project_label.setText(f"Project: {project_name}")

            for question in self.database.get_project_research_questions(
                project_id
            ):
                self.question_combo.addItem(
                    question["question"],
                    question["id"],
                )

        self.question_combo.blockSignals(False)
        self.load_hypotheses()
        self.update_action_state()

    def load_hypotheses(self, *_):
        self.hypothesis_list.clear()
        question_id = self.question_combo.currentData()

        if self.current_project_id is not None and question_id is not None:
            hypotheses = self.database.get_research_question_hypotheses(
                self.current_project_id,
                question_id,
            )
            for hypothesis in hypotheses:
                item = QListWidgetItem(
                    f"H0: {hypothesis['null_hypothesis'] or '(incomplete)'}\n"
                    f"H1: {hypothesis['alternative_hypothesis'] or '(incomplete)'}\n"
                    f"{hypothesis['directionality'].title()}"
                )
                item.setData(Qt.UserRole, hypothesis["id"])
                self.hypothesis_list.addItem(item)

            if not hypotheses:
                self.validation_warning.setText(
                    "No hypotheses entered. Add both H0 and H1 to complete the design."
                )
            elif any(
                not hypothesis["null_hypothesis"].strip()
                or not hypothesis["alternative_hypothesis"].strip()
                for hypothesis in hypotheses
            ):
                self.validation_warning.setText(
                    "At least one hypothesis is incomplete: both H0 and H1 are required."
                )
            else:
                self.validation_warning.setText("Hypotheses are complete.")
        else:
            self.validation_warning.setText(
                "Select a project and research question to manage hypotheses."
            )

        self.update_action_state()

    def update_action_state(self):
        can_add = (
            self.current_project_id is not None
            and self.question_combo.currentData() is not None
        )
        has_selection = self.hypothesis_list.currentItem() is not None
        self.add_button.setEnabled(can_add)
        self.edit_button.setEnabled(can_add and has_selection)
        self.delete_button.setEnabled(can_add and has_selection)

    def add_hypothesis(self):
        question_id = self.question_combo.currentData()
        if self.current_project_id is None or question_id is None:
            return

        dialog = HypothesisDialog(parent=self)
        if dialog.exec() != HypothesisDialog.Accepted:
            return
        try:
            self.database.create_hypothesis(
                self.current_project_id,
                question_id,
                **dialog.get_hypothesis_data(),
            )
        except ValueError as error:
            QMessageBox.warning(self, "Invalid Hypothesis", str(error))
            return
        self.load_hypotheses()

    def edit_hypothesis(self):
        item = self.hypothesis_list.currentItem()
        question_id = self.question_combo.currentData()
        if item is None or self.current_project_id is None or question_id is None:
            return

        hypothesis = self.database.get_hypothesis(
            self.current_project_id,
            question_id,
            item.data(Qt.UserRole),
        )
        if hypothesis is None:
            return

        dialog = HypothesisDialog(hypothesis, self)
        if dialog.exec() != HypothesisDialog.Accepted:
            return
        try:
            self.database.update_hypothesis(
                self.current_project_id,
                question_id,
                item.data(Qt.UserRole),
                **dialog.get_hypothesis_data(),
            )
        except ValueError as error:
            QMessageBox.warning(self, "Invalid Hypothesis", str(error))
            return
        self.load_hypotheses()

    def delete_hypothesis(self):
        item = self.hypothesis_list.currentItem()
        question_id = self.question_combo.currentData()
        if item is None or self.current_project_id is None or question_id is None:
            return

        answer = QMessageBox.question(
            self,
            "Delete Hypothesis",
            "Delete the selected hypothesis?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer == QMessageBox.Yes:
            self.database.delete_hypothesis(
                self.current_project_id,
                question_id,
                item.data(Qt.UserRole),
            )
            self.load_hypotheses()