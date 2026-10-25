from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QCheckBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.ui.project_dialog import ProjectDialog


class ProjectRowWidget(QWidget):
    """A project row with deliberately separate selection and open controls."""

    selection_changed = Signal(int, bool)
    open_requested = Signal(int)

    def __init__(self, project_id, text, parent=None):
        super().__init__(parent)
        self.project_id = project_id

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(10)

        self.selection_checkbox = QCheckBox()
        self.selection_checkbox.setAccessibleName(
            f"Select project {project_id} for deletion"
        )
        self.selection_checkbox.setToolTip("Select this project for deletion")
        self.selection_checkbox.stateChanged.connect(self._selection_changed)
        layout.addWidget(self.selection_checkbox)

        self.open_button = QPushButton(text)
        self.open_button.setObjectName("project_card")
        self.open_button.setFlat(True)
        self.open_button.setMinimumHeight(72)
        self.open_button.setSizePolicy(
            self.open_button.sizePolicy().horizontalPolicy(),
            self.open_button.sizePolicy().verticalPolicy(),
        )
        self.open_button.setStyleSheet(
            "QPushButton#project_card { text-align: left; padding: 10px; }"
            "QPushButton#project_card:hover { background: #eef4ff; }"
        )
        self.open_button.setAccessibleName(f"Open project {project_id}")
        self.open_button.clicked.connect(
            lambda: self.open_requested.emit(self.project_id)
        )
        layout.addWidget(self.open_button, 1)

    def _selection_changed(self, state):
        self.selection_changed.emit(
            self.project_id,
            state == Qt.Checked.value,
        )


class ProjectsPage(QWidget):
    project_selected = Signal(int)
    project_deleted = Signal(int)
    projects_changed = Signal()

    def __init__(self, database):
        super().__init__()

        self.database = database
        self._updating_checks = False

        self.setup_ui()
        self.load_projects()

    def setup_ui(self):
        layout = QVBoxLayout(self)

        # Header
        header_layout = QHBoxLayout()

        title = QLabel("Projects")
        title.setObjectName("page_title")

        header_layout.addWidget(title)
        header_layout.addStretch()

        new_button = QPushButton("+ New Project")
        new_button.setObjectName("primary_button")
        new_button.clicked.connect(self.create_project)

        header_layout.addWidget(new_button)

        layout.addLayout(header_layout)

        subtitle = QLabel(
            "Create and manage your research projects."
        )
        subtitle.setObjectName("page_subtitle")

        layout.addWidget(subtitle)
        layout.addSpacing(20)

        # Project list
        self.project_list = QListWidget()
        self.project_list.setObjectName("project_list")
        self.project_list.currentRowChanged.connect(self.update_delete_button)

        layout.addWidget(self.project_list)

        self.select_all_checkbox = QCheckBox("Select all projects")
        self.select_all_checkbox.stateChanged.connect(self.toggle_select_all)
        layout.addWidget(self.select_all_checkbox)

        self.delete_button = QPushButton("Delete Selected Projects (0)")
        self.delete_button.setObjectName("danger_button")
        self.delete_button.clicked.connect(self.delete_selected_project)
        self.delete_button.setEnabled(False)
        layout.addWidget(self.delete_button)

    def handle_project_open(self, project_id):
        """Open only when the designated project-card control is activated."""
        for row in range(self.project_list.count()):
            if self.project_list.item(row).data(Qt.UserRole) == project_id:
                self.project_list.setCurrentRow(row)
                break
        self.project_selected.emit(project_id)

    # Kept for callers from older integrations; list items no longer connect
    # directly to this method, so checkbox clicks cannot open a project.
    def handle_project_click(self, item):
        project_id = item.data(Qt.UserRole)
        if project_id is not None:
            self.handle_project_open(project_id)

    def load_projects(self):
        self._updating_checks = True
        self.project_list.clear()
        self.select_all_checkbox.setCheckState(Qt.Unchecked)

        projects = self.database.get_projects()

        if not projects:
            item = QListWidgetItem(
                "No projects yet. Click '+ New Project' to create one."
            )

            item.setTextAlignment(Qt.AlignCenter)

            self.project_list.addItem(item)
            self._updating_checks = False
            self.update_delete_button()

            return

        for project in projects:
            text = (
                f"{project['name']}\n"
                f"{project['research_title'] or 'No research title'}\n"
                f"Status: {project['status']}"
            )

            item = QListWidgetItem()
            item.setData(Qt.UserRole, project["id"])
            self.project_list.addItem(item)
            row_widget = ProjectRowWidget(project["id"], text, self.project_list)
            row_widget.selection_changed.connect(
                lambda *_: self.update_delete_button()
            )
            row_widget.open_requested.connect(self.handle_project_open)
            self.project_list.setItemWidget(item, row_widget)
            item.setSizeHint(row_widget.sizeHint())
        self._updating_checks = False
        self.update_delete_button()

    def update_delete_button(self, *_):
        if self._updating_checks:
            return
        checked = self.checked_project_ids()
        self.delete_button.setText(
            f"Delete Selected Projects ({len(checked)})"
        )
        self.delete_button.setEnabled(bool(checked))
        project_items = [
            self.project_list.item(row)
            for row in range(self.project_list.count())
            if self.project_list.item(row).data(Qt.UserRole) is not None
        ]
        self.select_all_checkbox.blockSignals(True)
        if project_items and len(checked) == len(project_items):
            self.select_all_checkbox.setCheckState(Qt.Checked)
        elif checked:
            self.select_all_checkbox.setCheckState(Qt.PartiallyChecked)
        else:
            self.select_all_checkbox.setCheckState(Qt.Unchecked)
        self.select_all_checkbox.blockSignals(False)

    def checked_project_ids(self):
        return [
            self.project_list.item(row).data(Qt.UserRole)
            for row in range(self.project_list.count())
            if self.project_list.item(row).data(Qt.UserRole) is not None
            and self.project_list.itemWidget(
                self.project_list.item(row)
            ).selection_checkbox.isChecked()
        ]

    def toggle_select_all(self, state):
        state_value = state.value if hasattr(state, "value") else int(state)
        partial_value = Qt.PartiallyChecked.value
        checked_value = Qt.Checked.value
        if self._updating_checks or state_value == partial_value:
            return
        checked = state_value == checked_value
        self._updating_checks = True
        for row in range(self.project_list.count()):
            item = self.project_list.item(row)
            if item.data(Qt.UserRole) is not None:
                row_widget = self.project_list.itemWidget(item)
                if row_widget is not None:
                    row_widget.selection_checkbox.setChecked(checked)
        self._updating_checks = False
        self.update_delete_button()

    def delete_selected_project(self):
        """Backward-compatible single-action entry point for the batch delete."""
        self.delete_selected_projects()

    def delete_selected_projects(self):
        project_ids = self.checked_project_ids()
        if not project_ids:
            return
        projects = [
            self.database.get_project(project_id)
            for project_id in project_ids
        ]
        projects = [project for project in projects if project is not None]
        if not projects:
            self.load_projects()
            return
        names = "\n".join(f"• {project['name']}" for project in projects)
        answer = QMessageBox.question(
            self,
            "Delete Projects",
            (
                f"Delete these {len(projects)} project(s) permanently?\n\n"
                f"{names}\n\n"
                "This removes its questions, hypotheses, dataset revisions, "
                "saved analyses, and report history. This cannot be undone."
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        managed_dir = (self.database.database_dir / "datasets").resolve()
        for project_id in project_ids:
            datasets = self.database.delete_project(project_id)
            for dataset in datasets:
                snapshot = Path(dataset["file_path"]).resolve()
                try:
                    if snapshot.is_file() and snapshot.parent == managed_dir:
                        snapshot.unlink()
                except OSError:
                    # Database deletion remains successful even if a stale snapshot
                    # cannot be removed; the source file is never touched.
                    pass
        self.load_projects()
        self.projects_changed.emit()
        for project_id in project_ids:
            self.project_deleted.emit(project_id)
        QMessageBox.information(
            self,
            "Projects Deleted",
            f"{len(project_ids)} project(s) were deleted successfully.",
        )

    def create_project(self):
        dialog = ProjectDialog(self)

        if dialog.exec():
            data = dialog.get_project_data()

            project_id = self.database.create_project(**data)

            self.load_projects()
            self.projects_changed.emit()

            QMessageBox.information(
                self,
                "Project Created",
                "The research project was created successfully.",
            )
            self.project_selected.emit(project_id)
