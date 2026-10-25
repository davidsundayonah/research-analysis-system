from pathlib import Path
import hashlib
import re
import shutil
from uuid import uuid4

import pandas as pd
from PySide6.QtCore import QThreadPool, Signal

from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
    QMessageBox,
    QDialog,
    QComboBox,

)

from app.statistics.variable_inspector import VariableInspector
from app.ui.data_cleaning_dialog import DataCleaningDialog
from app.ui.variable_metadata_dialog import VariableMetadataDialog
from app.statistics.data_cleaner import DataCleaner
from app.ui.background import FunctionWorker
from app.ui.questionnaire_dialog import QuestionnaireDialog
from app.ui.paper_entry_dialog import PaperEntryDialog
from app.ui.import_review_dialog import ImportReviewDialog
from app.import_workflow import apply_import_mapping, validate_import


class DataPage(QWidget):
    dataset_changed = Signal(object, object)
    MAX_FILE_BYTES = 250 * 1024 * 1024
    MAX_ROWS = 2_000_000

    def __init__(self, database):
        super().__init__()

        self.database = database

        self.current_project_id = None
        self.current_dataset_id = None
        self.current_dataframe = None
        self.thread_pool = QThreadPool.globalInstance()
        self.import_worker = None

        self.setup_ui()

    # =========================================================
    # USER INTERFACE
    # =========================================================

    def setup_ui(self):
        layout = QVBoxLayout(self)

        layout.setContentsMargins(
            40,
            35,
            40,
            35,
        )

        layout.setSpacing(15)

        # -----------------------------------------------------
        # Header
        # -----------------------------------------------------

        header_layout = QHBoxLayout()

        title = QLabel("Data")
        title.setObjectName("page_title")

        header_layout.addWidget(title)
        header_layout.addStretch()

        self.dataset_selector = QComboBox()
        self.dataset_selector.setMinimumWidth(260)
        self.dataset_selector.currentIndexChanged.connect(self.select_dataset)
        header_layout.addWidget(self.dataset_selector)

        self.import_button = QPushButton(
            "+ Import Dataset"
        )

        self.import_button.setObjectName(
            "primary_button"
        )

        self.import_button.clicked.connect(
            self.import_dataset
        )

        header_layout.addWidget(
            self.import_button
        )
        self.questionnaire_button = QPushButton("Questionnaire Builder")
        self.questionnaire_button.clicked.connect(self.open_questionnaire_builder)
        header_layout.addWidget(self.questionnaire_button)
        self.paper_entry_button = QPushButton("Paper Entry")
        self.paper_entry_button.clicked.connect(self.open_paper_entry)
        header_layout.addWidget(self.paper_entry_button)
        self.clean_button = QPushButton(
             "Data Cleaning"
        )

        self.clean_button.clicked.connect(
            self.open_cleaning_dialog
        )

        header_layout.addWidget(
              self.clean_button
        )

        layout.addLayout(header_layout)

        # -----------------------------------------------------
        # Dataset information
        # -----------------------------------------------------

        self.dataset_info = QLabel(
            "No dataset imported."
        )

        self.dataset_info.setObjectName(
            "page_subtitle"
        )

        layout.addWidget(
            self.dataset_info
        )

        # -----------------------------------------------------
        # Data table
        # -----------------------------------------------------

        self.tabs = QTabWidget()

        # =========================================================
        # Data View
        # =========================================================

        self.data_table = QTableWidget()

        self.data_table.setObjectName(
            "data_table"
        )

        self.data_table.setAlternatingRowColors(
            True
        )

        self.data_table.setEditTriggers(
            QTableWidget.NoEditTriggers
        )

        self.tabs.addTab(
            self.data_table,
            "Data View"
        )

        # =========================================================
        # Variable View
        # =========================================================

        self.variable_table = QTableWidget()

        self.variable_table.setObjectName(
            "data_table"
        )

        self.variable_table.setAlternatingRowColors(
            True
        )

        self.variable_table.setEditTriggers(
            QTableWidget.NoEditTriggers
        )
        self.variable_table.cellDoubleClicked.connect(self.edit_variable_metadata)

        self.tabs.addTab(
            self.variable_table,
            "Variable View"
        )

        layout.addWidget(
            self.tabs
        )

    # =========================================================
    # SET PROJECT
    # =========================================================

    def set_project(self, project_id):
        self.current_project_id = project_id

        self.current_dataset_id = None
        self.current_dataframe = None

        self.data_table.clear()
        self.data_table.setRowCount(0)
        self.data_table.setColumnCount(0)
        self.variable_table.clear()
        self.variable_table.setRowCount(0)
        self.variable_table.setColumnCount(0)
        enabled = project_id is not None
        self.questionnaire_button.setEnabled(enabled)
        self.paper_entry_button.setEnabled(enabled)

        datasets = self.database.get_project_datasets(project_id)
        self.dataset_selector.blockSignals(True)
        self.dataset_selector.clear()
        for dataset in datasets:
            label = (
                f"{dataset['filename']} | revision {dataset['revision_number']}"
                if "revision_number" in dataset.keys()
                else dataset["filename"]
            )
            self.dataset_selector.addItem(label, dataset["id"])
        active = next((d for d in datasets if d["is_active"]), None) if datasets else None
        if active is not None:
            self.dataset_selector.setCurrentIndex(
                self.dataset_selector.findData(active["id"])
            )
        self.dataset_selector.blockSignals(False)

        if active is not None:
            dataset = active

            self.current_dataset_id = dataset["id"]

            self.load_dataset(
                dataset["file_path"]
            )
        else:
            self.dataset_info.setText(
                "No dataset imported for this project."
            )
            self.dataset_changed.emit(None, None)

    def open_questionnaire_builder(self):
        if self.current_project_id is None:
            return
        dialog = QuestionnaireDialog(self.database, self.current_project_id, self)
        dialog.exec()

    def open_paper_entry(self):
        if self.current_project_id is None:
            return
        if not self.database.get_project_questionnaire_schemas(self.current_project_id):
            QMessageBox.information(self, "Create a questionnaire first", "Use Questionnaire Builder to create and approve a questionnaire schema.")
            return
        dialog = PaperEntryDialog(self.database, self.current_project_id, self)
        dialog.exec()

    def select_dataset(self, index):
        if index < 0 or self.current_project_id is None:
            return
        dataset_id = self.dataset_selector.itemData(index)
        dataset = self.database.get_dataset(dataset_id)
        if dataset is None:
            return
        try:
            self.database.set_active_dataset(self.current_project_id, dataset_id)
            self.current_dataset_id = dataset_id
            self.load_dataset(dataset["file_path"])
        except (OSError, ValueError) as error:
            QMessageBox.critical(self, "Dataset Selection Error", str(error))

    # =========================================================
    # LOAD DATASET
    # =========================================================

    def load_dataset(self, file_path):
        try:
            dataframe = self.read_dataset(
                file_path
            )
        except Exception as error:
            self.dataset_info.setText(
                f"Could not load dataset: {error}"
            )
            QMessageBox.critical(
                self,
                "Dataset Load Error",
                f"Could not load the dataset.\n\n{error}",
            )
            self.dataset_changed.emit(self.current_dataset_id, None)
            return

        self.current_dataframe = dataframe

        self.display_dataframe(
            dataframe
        )
        self.display_variable_view(
            dataframe
        )

        self.dataset_info.setText(
            f"Dataset: {Path(file_path).name}    |    "
            f"Rows: {len(dataframe):,}    |    "
            f"Columns: {len(dataframe.columns):,}"
        )
        self.publish_dataset_state()

    # =========================================================
    # IMPORT DATASET
    # =========================================================

    def import_dataset(self):
        if self.current_project_id is None:
            QMessageBox.warning(
                self,
                "No Project Selected",
                "Please select a project before importing data.",
            )

            return

        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Dataset",
            "",
            "Data Files (*.xlsx *.xls *.csv)",
        )

        if not file_path:
            return

        self.import_button.setEnabled(False)
        self.import_worker = FunctionWorker(self.read_dataset, file_path)
        self.import_worker.signals.finished.connect(
            lambda dataframe: self._finish_import(file_path, dataframe)
        )
        self.import_worker.signals.failed.connect(self._import_failed)
        self.thread_pool.start(self.import_worker)
        return

        try:
            dataframe = self.read_dataset(
                file_path
            )

        except Exception as error:
            QMessageBox.critical(
                self,
                "Import Error",
                f"Could not import the dataset.\n\n{error}",
            )

            return

        filename = Path(file_path).name

        file_extension = (
            Path(file_path)
            .suffix
            .lower()
            .replace(".", "")
        )

        snapshot_dir = self.database.database_dir / "datasets"
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        snapshot_path = snapshot_dir / f"{uuid4().hex}{Path(file_path).suffix.lower()}"
        shutil.copy2(file_path, snapshot_path)
        dataset_id = self.database.create_dataset(
            project_id=self.current_project_id,
            filename=filename,
            file_path=str(snapshot_path),
            file_type=file_extension,
            row_count=len(dataframe),
            column_count=len(dataframe.columns),
            source_path=file_path,
            content_hash=self.file_hash(snapshot_path),
        )

        self.current_dataset_id = dataset_id
        self.current_dataframe = dataframe

        self.display_dataframe(
            dataframe
        )
        self.display_variable_view(
            dataframe
        )

        self.dataset_info.setText(
            f"Dataset: {filename}    |    "
            f"Rows: {len(dataframe):,}    |    "
            f"Columns: {len(dataframe.columns):,}"
        )
        self.publish_dataset_state()

        QMessageBox.information(
            self,
            "Import Successful",
            "The dataset was imported successfully.",
        )

        self.refresh_dataset_selector(dataset_id)

    def _import_failed(self, message):
        self.import_button.setEnabled(True)
        self.import_worker = None
        QMessageBox.critical(self, "Import Error", f"Could not import the dataset.\n\n{message}")

    def _finish_import(self, file_path, dataframe):
        try:
            schemas = self.database.get_project_questionnaire_schemas(self.current_project_id)
            if schemas:
                questions = self.database.get_questionnaire_questions(schemas[0]["id"])
                review = ImportReviewDialog(dataframe, questions, self)
                if review.exec() != QDialog.Accepted:
                    self.import_button.setEnabled(True)
                    self.import_worker = None
                    return
                mapping, keep_unmapped = review.get_mapping()
                validation = validate_import(dataframe, questions, mapping)
                if validation["errors"]:
                    answer = QMessageBox.warning(
                        self, "Validation warnings",
                        f"{validation['invalid_row_count']} rows contain invalid values. Preserve them for review?",
                        QMessageBox.Yes | QMessageBox.No,
                    )
                    if answer != QMessageBox.Yes:
                        self.import_button.setEnabled(True)
                        self.import_worker = None
                        return
                dataframe = apply_import_mapping(dataframe, questions, mapping, include_unmapped=keep_unmapped)
            filename = Path(file_path).name
            file_extension = Path(file_path).suffix.lower().replace(".", "")
            snapshot_dir = self.database.database_dir / "datasets"
            snapshot_dir.mkdir(parents=True, exist_ok=True)
            snapshot_path = snapshot_dir / f"{uuid4().hex}{Path(file_path).suffix.lower()}"
            shutil.copy2(file_path, snapshot_path)
            dataset_id = self.database.create_dataset(
                project_id=self.current_project_id,
                filename=filename,
                file_path=str(snapshot_path),
                file_type=file_extension,
                row_count=len(dataframe),
                column_count=len(dataframe.columns),
                source_path=file_path,
                content_hash=self.file_hash(snapshot_path),
            )
            self.current_dataset_id = dataset_id
            self.current_dataframe = dataframe
            self.display_dataframe(dataframe)
            self.display_variable_view(dataframe)
            self.dataset_info.setText(
                f"Dataset: {filename}    |    Rows: {len(dataframe):,}    |    Columns: {len(dataframe.columns):,}"
            )
            self.publish_dataset_state()
            self.refresh_dataset_selector(dataset_id)
            QMessageBox.information(self, "Import Successful", "The dataset was imported successfully.")
        except (OSError, ValueError) as error:
            self._import_failed(str(error))
        finally:
            self.import_button.setEnabled(True)
            self.import_worker = None

    def refresh_dataset_selector(self, selected_id=None):
        datasets = self.database.get_project_datasets(self.current_project_id)
        self.dataset_selector.blockSignals(True)
        self.dataset_selector.clear()
        for dataset in datasets:
            self.dataset_selector.addItem(
                f"{dataset['filename']} | revision {dataset['revision_number']}",
                dataset["id"],
            )
        index = self.dataset_selector.findData(selected_id or self.current_dataset_id)
        self.dataset_selector.setCurrentIndex(index if index >= 0 else 0)
        self.dataset_selector.blockSignals(False)

    @staticmethod
    def file_hash(path):
        digest = hashlib.sha256()
        with open(path, "rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    # =========================================================
    # READ DATASET
    # =========================================================

    def read_dataset(self, file_path):
        path = Path(file_path)
        if not path.is_file():
            raise FileNotFoundError(f"Dataset file does not exist: {path}")
        if path.stat().st_size > self.MAX_FILE_BYTES:
            raise ValueError(
                f"Dataset exceeds the {self.MAX_FILE_BYTES // (1024 * 1024)} MB safety limit."
            )
        extension = path.suffix.lower()

        if extension == ".csv":
            dataframe = pd.read_csv(file_path, low_memory=False)
        elif extension in [".xlsx", ".xls"]:
            dataframe = pd.read_excel(file_path)
        else:
            raise ValueError("Unsupported file type.")

        if len(dataframe) > self.MAX_ROWS:
            raise ValueError(
                f"Dataset exceeds the {self.MAX_ROWS:,}-row safety limit."
            )
        if dataframe.empty or len(dataframe.columns) == 0:
            raise ValueError("Dataset must contain at least one row and one column.")
        if dataframe.columns.duplicated().any():
            raise ValueError("Dataset contains duplicate column names.")
        if any(not str(column).strip() for column in dataframe.columns):
            raise ValueError("Dataset contains an empty column name.")
        return dataframe

    def publish_dataset_state(self):
        dataframe = self.current_dataframe
        dataset_id = self.current_dataset_id
        if dataset_id is not None and dataframe is not None:
            self.database.replace_dataset_variables(
                dataset_id,
                [
                    (str(column), str(data_type))
                    for column, data_type in dataframe.dtypes.items()
                ],
            )
        self.dataset_changed.emit(dataset_id, dataframe)

    # =========================================================
    # DISPLAY DATAFRAME
    # =========================================================

    def display_dataframe(self, dataframe):
        self.data_table.clear()

        self.data_table.setRowCount(
            len(dataframe)
        )

        self.data_table.setColumnCount(
            len(dataframe.columns)
        )

        # Column headers
        self.data_table.setHorizontalHeaderLabels(
            [
                str(column)
                for column in dataframe.columns
            ]
        )

        # Data
        for row_index in range(
            len(dataframe)
        ):
            for column_index in range(
                len(dataframe.columns)
            ):
                value = dataframe.iloc[
                    row_index,
                    column_index
                ]

                if pd.isna(value):
                    text = ""
                else:
                    text = str(value)

                item = QTableWidgetItem(
                    text
                )

                self.data_table.setItem(
                    row_index,
                    column_index,
                    item,
                )

        # Resize columns
        self.data_table.resizeColumnsToContents()

    def display_variable_view(
        self,
        dataframe
    ):

        inspector = VariableInspector(
            dataframe
        )

        variables = inspector.inspect()
        metadata_by_name = {
            row["name"]: dict(row)
            for row in self.database.get_dataset_variables(self.current_dataset_id)
        } if self.current_dataset_id is not None else {}

        columns = [
            "Name",
            "Label",
            "Type",
            "Measure",
            "Value labels",
            "Missing",
            "Unique",
            "Count",
            "Minimum",
            "Maximum",
            "Mean",
            "Std. Dev."
        ]

        self.variable_table.clear()

        self.variable_table.setRowCount(
            len(variables)
        )

        self.variable_table.setColumnCount(
            len(columns)
        )

        self.variable_table.setHorizontalHeaderLabels(
            columns
        )

        for row_index, variable in enumerate(
            variables
        ):

            values = [
                variable["name"],
                metadata_by_name.get(variable["name"], {}).get("label") or variable["label"],
                variable["type"],
                metadata_by_name.get(variable["name"], {}).get("measure") or variable["measure"],
                self.format_value_labels(
                    metadata_by_name.get(variable["name"]),
                    variable.get("value_labels"),
                ),
                variable["missing"],
                variable["unique"],
                variable["count"],
                variable["minimum"],
                variable["maximum"],
                variable["mean"],
                variable["std"],
            ]

            for column_index, value in enumerate(
                values
            ):

                if value is None:
                    text = ""
                else:
                    text = str(value)

                item = QTableWidgetItem(
                    text
                )

                self.variable_table.setItem(
                    row_index,
                    column_index,
                    item
                )

        self.variable_table.resizeColumnsToContents()

    @staticmethod
    def format_value_labels(metadata, inferred=None):
        if not metadata and not inferred:
            return ""
        try:
            import json
            values = (
                json.loads(metadata.get("value_labels_json") or "{}")
                if metadata
                else {}
            )
        except (TypeError, ValueError):
            values = {}
        if not values:
            values = inferred or {}
        return "; ".join(f"{key}={value}" for key, value in values.items())

    def edit_variable_metadata(self, row, _column):
        if self.current_dataset_id is None:
            return
        item = self.variable_table.item(row, 0)
        if item is None:
            return
        variable_name = item.text()
        stored = self.database.get_dataset_variables(self.current_dataset_id)
        metadata = next((dict(value) for value in stored if value["name"] == variable_name), {})
        try:
            import json
            metadata["value_labels"] = json.loads(metadata.get("value_labels_json") or "{}")
        except (TypeError, ValueError):
            metadata["value_labels"] = {}
        dialog = VariableMetadataDialog(variable_name, metadata, self)
        if dialog.exec() != QDialog.Accepted:
            return
        values = dialog.get_metadata()
        self.database.update_variable_metadata(
            self.current_dataset_id,
            variable_name,
            values["label"],
            values["measure"],
            values["value_labels"],
        )
        self.display_variable_view(self.current_dataframe)

    def open_cleaning_dialog(self):

        if self.current_dataframe is None:

            QMessageBox.warning(
                self,
                "No Dataset",
                "Please import a dataset first.",
            )

            return

        dialog = DataCleaningDialog(
            self.current_dataframe,
            self
        )

        if dialog.exec() != QDialog.Accepted:
            return

        data = dialog.get_operation_data()

        cleaner = DataCleaner(
            self.current_dataframe
        )

        try:

            operation = data["operation"]

            variable = data["variable"]

            new_variable = (
                data["new_variable"]
                or None
            )

            if operation == "Rename Variable":

                if not new_variable:
                    raise ValueError(
                        "Enter a new variable name."
                    )

                dataframe = cleaner.rename_variable(
                    variable,
                    new_variable
                )

            elif operation == "Recode Values":

                mapping = self.parse_mapping(
                    data["mapping"]
                )

                dataframe = cleaner.recode_values(
                    variable,
                    mapping,
                    new_variable
                )

            elif operation == "Define Missing Values":

                mapping = self.parse_mapping(
                    data["mapping"]
                )

                missing_values = list(
                    mapping.keys()
                )

                dataframe = cleaner.define_missing_values(
                    variable,
                    missing_values
                )

            elif operation == "Reverse Score":

                dataframe = cleaner.reverse_score(
                    variable,
                    data["minimum"],
                    data["maximum"],
                    new_variable
                )

            elif operation == "Create Range Groups":
                if not new_variable:
                    raise ValueError("Enter a new variable name for the range groups.")
                ranges = self.parse_ranges(data["mapping"])
                dataframe = cleaner.create_range_groups(
                    variable,
                    ranges,
                    new_variable,
                )

            else:

                raise ValueError(
                    "Unknown operation."
                )

            previous_dataset_id = self.current_dataset_id
            self.current_dataframe = dataframe

            self.display_dataframe(
                dataframe
            )

            self.display_variable_view(
                dataframe
            )
            self.publish_dataset_state()

            if previous_dataset_id is not None:
                self.save_revision(previous_dataset_id, dataframe)

            QMessageBox.information(
                self,
                "Operation Complete",
                "The data was updated successfully.",
            )

        except Exception as error:

            QMessageBox.critical(
                self,
                "Cleaning Error",
                str(error),
            )

    def save_revision(self, source_dataset_id, dataframe):
        source = self.database.get_dataset(source_dataset_id)
        if source is None:
            return
        snapshot_dir = self.database.database_dir / "datasets"
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        snapshot_path = snapshot_dir / f"{uuid4().hex}.csv"
        dataframe.to_csv(snapshot_path, index=False)
        revision_number = int(source["revision_number"] or 1) + 1
        revision_id = self.database.create_dataset(
            project_id=self.current_project_id,
            filename=f"{Path(source['filename']).stem} (revision {revision_number}).csv",
            file_path=str(snapshot_path),
            file_type="csv",
            row_count=len(dataframe),
            column_count=len(dataframe.columns),
            source_path=source["source_path"] or source["file_path"],
            content_hash=self.file_hash(snapshot_path),
            revision_number=revision_number,
            revision_of=source_dataset_id,
        )
        self.database.clone_dataset_links(source_dataset_id, revision_id)
        self.current_dataset_id = revision_id
        self.refresh_dataset_selector(revision_id)
        self.publish_dataset_state()

    def parse_mapping(self, text):

        if not text.strip():

            raise ValueError(
                "Enter a mapping."
            )

        mapping = {}

        parts = text.split(",")

        for part in parts:

            if "=" not in part:

                raise ValueError(
                    f"Invalid mapping: {part}"
                )

            old, new = part.split(
                "=",
                1
            )

            old = old.strip()
            new = new.strip()

            try:
                old_value = float(old)
            except ValueError:
                old_value = old

            try:
                new_value = float(new)
            except ValueError:
                new_value = new

            if isinstance(
                old_value,
                float
            ) and old_value.is_integer():

                old_value = int(
                    old_value
                )

            if isinstance(
                new_value,
                float
            ) and new_value.is_integer():

                new_value = int(
                    new_value
                )

            mapping[
                old_value
            ] = new_value

        return mapping

    @staticmethod
    def parse_ranges(text):
        if not text.strip():
            raise ValueError("Enter ranges such as 1-10=1,11-20=2.")
        ranges = []
        for part in text.split(","):
            if "=" not in part:
                raise ValueError(f"Invalid range: {part}")
            bounds, label = part.split("=", 1)
            match = re.fullmatch(r"\s*(-?\d+(?:\.\d+)?)\s*-\s*(-?\d+(?:\.\d+)?)\s*", bounds)
            if match is None or not label.strip():
                raise ValueError(f"Invalid range: {part}")
            ranges.append((float(match.group(1)), float(match.group(2)), label.strip()))
        return ranges

def reverse_score(
    self,
    variable,
    minimum=1,
    maximum=5,
    new_variable=None
):

    if variable not in self.dataframe.columns:
        raise ValueError(
            f"Variable '{variable}' does not exist."
        )

    target = (
        new_variable
        if new_variable
        else variable
    )

    self.dataframe[target] = (
        maximum
        + minimum
        - self.dataframe[variable]
    )

    return self.dataframe
