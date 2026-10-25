from pathlib import Path
import re
import tempfile
from PySide6.QtCore import Signal

from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from app.security import SecureExport


class ExportPage(QWidget):
    export_completed = Signal(str)

    def __init__(self, report_generator, exporter):
        super().__init__()
        self.report_generator = report_generator
        self.exporter = exporter
        self.project_id = None

        layout = QVBoxLayout(self)
        title = QLabel("Word and Excel Export")
        title.setObjectName("page_title")
        layout.addWidget(title)

        self.context_label = QLabel("Select a project to export Chapter Four.")
        self.context_label.setObjectName("page_subtitle")
        layout.addWidget(self.context_label)

        buttons = QHBoxLayout()
        self.word_button = QPushButton("Export Word (.docx)")
        self.word_button.setObjectName("primary_button")
        self.word_button.clicked.connect(self.export_word_dialog)
        buttons.addWidget(self.word_button)

        self.excel_button = QPushButton("Export Excel (.xlsx)")
        self.excel_button.setObjectName("primary_button")
        self.excel_button.clicked.connect(self.export_excel_dialog)
        buttons.addWidget(self.excel_button)
        self.protected_word_button = QPushButton("Protected Word (.raenc)")
        self.protected_word_button.clicked.connect(lambda: self._export_dialog("docx", protected=True))
        buttons.addWidget(self.protected_word_button)
        self.protected_excel_button = QPushButton("Protected Excel (.raenc)")
        self.protected_excel_button.clicked.connect(lambda: self._export_dialog("xlsx", protected=True))
        buttons.addWidget(self.protected_excel_button)
        layout.addLayout(buttons)

        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        layout.addStretch()

        self.set_project(None)

    def set_project(self, project_id):
        self.project_id = project_id
        project = (
            self.report_generator.database.get_project(project_id)
            if project_id is not None
            else None
        )
        self.context_label.setText(
            f"Project: {project['name']}" if project else "Select a project to export Chapter Four."
        )
        self.word_button.setEnabled(project is not None)
        self.excel_button.setEnabled(project is not None)
        self.protected_word_button.setEnabled(project is not None)
        self.protected_excel_button.setEnabled(project is not None)
        self.status_label.clear()

    @staticmethod
    def default_filename(project_name, extension):
        safe_name = re.sub(r"[^A-Za-z0-9_-]+", "_", project_name).strip("_") or "research_report"
        return f"{safe_name}_chapter_four.{extension}"

    def export_word_dialog(self):
        self._export_dialog("docx")

    def export_excel_dialog(self):
        self._export_dialog("xlsx")

    def _export_dialog(self, extension, protected=False):
        if self.project_id is None:
            return
        project = self.report_generator.database.get_project(self.project_id)
        filename = self.default_filename(project["name"], extension)
        if protected:
            filename += ".raenc"
        file_filter = "Encrypted research export (*.raenc)" if protected else ("Word document (*.docx)" if extension == "docx" else "Excel workbook (*.xlsx)")
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Chapter Four",
            filename,
            file_filter,
        )
        if not path:
            return
        if protected:
            self.export_protected_to(path, extension, confirm_revision=None)
        else:
            self.export_to(path, extension, confirm_revision=None)

    def _confirm_revision_alignment(self, report, confirm_revision=None):
        revision_warnings = [warning for warning in report.warnings if "revision" in warning.lower()]
        if not revision_warnings:
            return True
        if confirm_revision is False:
            raise ValueError("Export cancelled because the report combines different dataset revisions.")
        if confirm_revision is None:
            answer = QMessageBox.question(
                self,
                "Confirm dataset revisions",
                "This report combines different dataset revisions. Review the warnings before publication. Export anyway?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return False
        return True

    def export_to(self, output_path, format_name=None, confirm_revision=False):
        if self.project_id is None:
            raise ValueError("Select a project before exporting.")
        output_path = Path(output_path)
        extension = (format_name or output_path.suffix.lstrip(".")).lower()
        if extension not in {"docx", "xlsx"}:
            raise ValueError("Export format must be docx or xlsx.")
        report = self.report_generator.generate(self.project_id)
        if not self._confirm_revision_alignment(report, confirm_revision):
            return None
        try:
            if extension == "docx":
                self.exporter.export_docx(report, output_path)
            else:
                self.exporter.export_xlsx(report, output_path)
        except (OSError, ValueError, RuntimeError) as error:
            self.status_label.setText(f"Export failed: {error}")
            QMessageBox.critical(self, "Export Failed", str(error))
            return None
        self.status_label.setText(f"Exported Chapter Four to {output_path}")
        self.export_completed.emit(str(output_path))
        return output_path

    def export_protected_to(self, output_path, format_name=None, confirm_revision=False):
        """Export to DOCX/XLSX and encrypt the resulting bytes as .raenc."""
        output_path = Path(output_path)
        if output_path.suffix.lower() != ".raenc":
            raise ValueError("Protected exports must use the .raenc extension.")
        extension = (format_name or "").lower().lstrip(".")
        if extension not in {"docx", "xlsx"}:
            raise ValueError("Protected export format must be docx or xlsx.")
        with tempfile.TemporaryDirectory(prefix="research-export-") as folder:
            temporary = Path(folder) / f"report.{extension}"
            exported = self.export_to(temporary, extension, confirm_revision=confirm_revision)
            if exported is None:
                return None
            SecureExport().encrypt_file(temporary, output_path)
        self.status_label.setText(f"Encrypted Chapter Four export saved to {output_path}")
        self.export_completed.emit(str(output_path))
        return output_path
