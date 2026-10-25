from PySide6.QtCore import Qt, Signal
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

from app.ui.research_question_dialog import ResearchQuestionDialog


class ResearchQuestionsPage(QWidget):
    questions_changed = Signal(int)

    def __init__(self, database):
        super().__init__()

        self.database = database
        self.current_project_id = None
        self.current_dataset_id = None
        self.current_dataframe = None

        layout = QVBoxLayout(self)
        header = QHBoxLayout()

        title = QLabel("Research Questions")
        title.setObjectName("page_title")
        header.addWidget(title)
        header.addStretch()

        self.add_button = QPushButton("+ Add Question")
        self.add_button.setObjectName("primary_button")
        self.add_button.clicked.connect(self.add_question)
        header.addWidget(self.add_button)

        self.edit_button = QPushButton("Edit")
        self.edit_button.clicked.connect(self.edit_question)
        header.addWidget(self.edit_button)

        self.delete_button = QPushButton("Delete")
        self.delete_button.clicked.connect(self.delete_question)
        header.addWidget(self.delete_button)

        self.move_up_button = QPushButton("Move Up")
        self.move_up_button.clicked.connect(lambda: self.move_question(-1))
        header.addWidget(self.move_up_button)

        self.move_down_button = QPushButton("Move Down")
        self.move_down_button.clicked.connect(lambda: self.move_question(1))
        header.addWidget(self.move_down_button)

        layout.addLayout(header)

        self.project_label = QLabel("Select a project first.")
        self.project_label.setObjectName("page_subtitle")
        layout.addWidget(self.project_label)

        self.question_list = QListWidget()
        self.question_list.itemSelectionChanged.connect(
            self.update_selected_question
        )
        layout.addWidget(self.question_list)

        self.question_details = QLabel()
        self.question_details.setWordWrap(True)
        layout.addWidget(self.question_details)

        variable_controls = QHBoxLayout()
        self.variable_combo = QComboBox()
        variable_controls.addWidget(self.variable_combo)

        self.role_combo = QComboBox()
        self.role_combo.addItems(["outcome", "predictor", "grouping"])
        variable_controls.addWidget(self.role_combo)

        self.link_variable_button = QPushButton("Link Variable")
        self.link_variable_button.clicked.connect(self.link_variable)
        variable_controls.addWidget(self.link_variable_button)
        layout.addLayout(variable_controls)

        self.variable_links = QListWidget()
        self.variable_links.itemSelectionChanged.connect(
            self.update_action_state
        )
        layout.addWidget(self.variable_links)

        self.remove_variable_button = QPushButton("Remove Variable Link")
        self.remove_variable_button.clicked.connect(self.remove_variable_link)
        layout.addWidget(self.remove_variable_button)

        self.validation_warnings = QLabel()
        self.validation_warnings.setWordWrap(True)
        layout.addWidget(self.validation_warnings)

        self.set_project(None)

    def set_project(self, project_id):
        self.current_project_id = project_id
        if project_id is None:
            self.project_label.setText("Select a project first.")
        else:
            project = self.database.get_project(project_id)
            project_name = project["name"] if project else "Unknown project"
            self.project_label.setText(f"Project: {project_name}")
        self.refresh_questions()

    def set_dataset(self, dataset_id, dataframe):
        self.current_dataset_id = dataset_id
        self.current_dataframe = dataframe
        self.variable_combo.clear()
        if dataframe is not None:
            self.variable_combo.addItems(
                [str(column) for column in dataframe.columns]
            )
        self.update_selected_question()

    def refresh_questions(self, selected_id=None):
        self.question_list.clear()
        if self.current_project_id is not None:
            questions = self.database.get_project_research_questions(
                self.current_project_id
            )
            for question in questions:
                item = QListWidgetItem(
                    f"{question['code']}  |  {question['question']}"
                )
                item.setData(Qt.UserRole, question["id"])
                self.question_list.addItem(item)

            selected_row = next(
                (
                    row
                    for row in range(self.question_list.count())
                    if self.question_list.item(row).data(Qt.UserRole) == selected_id
                ),
                0 if self.question_list.count() else -1,
            )
            if selected_row >= 0:
                self.question_list.setCurrentRow(selected_row)

        self.update_selected_question()

    def selected_question(self):
        item = self.question_list.currentItem()
        if item is None or self.current_project_id is None:
            return None
        return self.database.get_research_question(
            self.current_project_id,
            item.data(Qt.UserRole),
        )

    def update_action_state(self):
        has_project = self.current_project_id is not None
        has_selection = self.selected_question() is not None
        self.add_button.setEnabled(has_project)
        self.edit_button.setEnabled(has_project and has_selection)
        self.delete_button.setEnabled(has_project and has_selection)
        question = self.selected_question()
        order = [
            row["id"]
            for row in self.database.get_project_research_questions(
                self.current_project_id
            )
        ] if has_project else []
        current_position = order.index(question["id"]) if question else -1
        self.move_up_button.setEnabled(current_position > 0)
        self.move_down_button.setEnabled(
            current_position >= 0 and current_position < len(order) - 1
        )
        self.link_variable_button.setEnabled(
            has_selection
            and self.current_dataset_id is not None
            and self.variable_combo.count() > 0
        )
        self.remove_variable_button.setEnabled(
            self.variable_links.currentItem() is not None
        )

    def add_question(self):
        if self.current_project_id is None:
            return

        position = len(
            self.database.get_project_research_questions(self.current_project_id)
        ) + 1
        dialog = ResearchQuestionDialog(position=position, parent=self)
        if dialog.exec() != ResearchQuestionDialog.Accepted:
            return
        data = dialog.get_question_data()
        try:
            question_id = self.database.create_research_question(
                self.current_project_id,
                **data,
            )
        except (TypeError, ValueError) as error:
            QMessageBox.warning(self, "Invalid Research Question", str(error))
            return
        self.refresh_questions(question_id)
        self.questions_changed.emit(self.current_project_id)

    def edit_question(self):
        question = self.selected_question()
        if question is None:
            return

        count = len(
            self.database.get_project_research_questions(self.current_project_id)
        )
        dialog = ResearchQuestionDialog(question, count, self)
        if dialog.exec() != ResearchQuestionDialog.Accepted:
            return

        try:
            self.database.update_research_question(
                self.current_project_id,
                question["id"],
                **dialog.get_question_data(),
            )
        except (TypeError, ValueError) as error:
            QMessageBox.warning(self, "Invalid Research Question", str(error))
            return
        self.refresh_questions(question["id"])
        self.questions_changed.emit(self.current_project_id)

    def move_question(self, offset):
        question = self.selected_question()
        if question is None:
            return

        ordered_ids = [
            row["id"]
            for row in self.database.get_project_research_questions(
                self.current_project_id
            )
        ]
        current = ordered_ids.index(question["id"])
        target = current + offset
        if target < 0 or target >= len(ordered_ids):
            return
        ordered_ids[current], ordered_ids[target] = (
            ordered_ids[target],
            ordered_ids[current],
        )
        self.database.reorder_project_research_questions(
            self.current_project_id,
            ordered_ids,
        )
        self.refresh_questions(question["id"])
        self.questions_changed.emit(self.current_project_id)

    def delete_question(self):
        question = self.selected_question()
        if question is None:
            return

        answer = QMessageBox.question(
            self,
            "Delete Research Question",
            "Delete this question and its linked hypotheses and variables?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer == QMessageBox.Yes:
            self.database.delete_research_question(
                self.current_project_id,
                question["id"],
            )
            self.refresh_questions()
            self.questions_changed.emit(self.current_project_id)

    def update_selected_question(self):
        question = self.selected_question()
        self.variable_links.clear()

        if question is None:
            self.question_details.setText("")
            self.validation_warnings.setText("")
            self.update_action_state()
            return

        self.question_details.setText(
            f"{question['code']} | Order {question['position']} | "
            f"{question['design_type'].title()} | "
            f"Proposed test: {question['proposed_test'] or 'Not specified'}"
        )

        links = self.database.get_question_variables(
            self.current_project_id,
            question["id"],
        )
        valid_roles = set()
        warnings = []
        for link in links:
            if self.current_dataset_id != link["dataset_id"]:
                validity = f"stale: dataset changed from {link['filename']}"
            elif (
                not link["variable_exists"]
                or self.current_dataframe is None
                or link["variable_name"] not in {
                    str(column) for column in self.current_dataframe.columns
                }
            ):
                validity = "missing or renamed in active dataset"
            else:
                validity = "active"
                valid_roles.add(link["role"])

            item = QListWidgetItem(
                f"{link['variable_name']}  |  {link['role']}  |  {validity}"
            )
            item.setData(Qt.UserRole, link["id"])
            self.variable_links.addItem(item)
            if validity != "active":
                warnings.append(
                    f"Variable link '{link['variable_name']}' is {validity}."
                )

        required_roles = {
            "descriptive": {"outcome"},
            "comparison": {"outcome", "grouping"},
            "association": {"outcome", "predictor"},
            "prediction": {"outcome", "predictor"},
        }[question["design_type"]]

        if self.current_dataset_id is None:
            warnings.append("No active dataset is selected.")
        else:
            missing_roles = required_roles - valid_roles
            if missing_roles:
                warnings.append(
                    "Missing variable roles: "
                    + ", ".join(sorted(missing_roles))
                    + "."
                )

        hypotheses = self.database.get_research_question_hypotheses(
            self.current_project_id,
            question["id"],
        )
        if not hypotheses:
            warnings.append("No hypotheses have been entered for this question.")
        elif any(
            not hypothesis["null_hypothesis"].strip()
            or not hypothesis["alternative_hypothesis"].strip()
            for hypothesis in hypotheses
        ):
            warnings.append("At least one hypothesis is missing H0 or H1.")

        self.validation_warnings.setText(
            "Warnings: " + " ".join(warnings) if warnings else "Design checks passed."
        )
        self.update_action_state()

    def link_variable(self):
        question = self.selected_question()
        if question is None or self.current_dataset_id is None:
            return

        try:
            self.database.set_question_variable(
                self.current_project_id,
                question["id"],
                self.current_dataset_id,
                self.variable_combo.currentText(),
                self.role_combo.currentText(),
            )
        except ValueError as error:
            QMessageBox.warning(self, "Invalid Variable Link", str(error))
            return
        self.update_selected_question()

    def remove_variable_link(self):
        question = self.selected_question()
        item = self.variable_links.currentItem()
        if question is None or item is None:
            return
        self.database.delete_question_variable(
            self.current_project_id,
            question["id"],
            item.data(Qt.UserRole),
        )
        self.update_selected_question()