from __future__ import annotations

from pathlib import Path
from html import escape

import numpy as np
import pandas as pd
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from PySide6.QtCore import Qt
from PySide6.QtGui import QTextDocument
from PySide6.QtPrintSupport import QPrinter
from PySide6.QtWidgets import (
    QComboBox,
    QCheckBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QInputDialog,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.statistics.time_series_analysis import (
    analyze_time_series,
    analyze_exogenous_time_series,
    analyze_multivariate_time_series,
    create_time_series_charts,
    detect_time_series,
    inspect_time_series_dataset,
    parse_pasted_data,
    parse_time_values,
    preprocess_time_series_dataframe,
    recommend_time_series_methods,
    read_time_series_file,
    stationarity_p_value_display,
    transform_time_series,
)
from app.word_charts import (
    add_editable_chart,
    append_editable_charts_xlsx,
    time_series_chart_specs,
)


class TimeSeriesWindow(QDialog):
    """Dedicated, non-modal time-series workspace over existing project data."""

    def __init__(self, database, parent=None):
        super().__init__(parent)
        self.database = database
        self.dataframe = pd.DataFrame()
        self.original_dataframe = pd.DataFrame()
        self.preprocessing_log = []
        self._recommendation_cache = {}
        self.source_dataset_id = None
        self.last_result = None
        self.last_figure = None
        self.last_figures = {}
        self.chart_canvases = {}
        self.last_provenance = {}
        self.setWindowTitle("Time-Series Analysis")
        self.resize(1100, 760)
        self.setModal(False)
        self.setWindowModality(Qt.NonModal)

        self.project_combo = QComboBox()
        self.project_combo.currentIndexChanged.connect(self._refresh_project_datasets)
        self.dataset_combo = QComboBox()
        self.dataset_combo.currentIndexChanged.connect(self._load_selected_dataset)
        self.open_button = QPushButton("Open CSV / Excel / PDF")
        self.open_button.clicked.connect(self._open_file)
        self.paste_button = QPushButton("Paste table")
        self.paste_button.clicked.connect(self._paste_data)
        self.add_row_button = QPushButton("Add observation")
        self.add_row_button.clicked.connect(self._add_observation)
        self.delete_row_button = QPushButton("Delete selected row")
        self.delete_row_button.clicked.connect(self._delete_observation)
        self.sort_button = QPushButton("Sort by time")
        self.sort_button.clicked.connect(self._sort_by_time)
        self.save_revision_button = QPushButton("Save working data as project revision")
        self.save_revision_button.clicked.connect(self._save_working_revision)

        self.date_combo = QComboBox()
        self.date_combo.currentIndexChanged.connect(self._update_recommendations)
        self.value_combo = QComboBox()
        self.value_combo.currentIndexChanged.connect(self._update_recommendations)
        self.analysis_type_combo = QComboBox()
        self.analysis_type_combo.addItem("Univariate", "univariate")
        self.analysis_type_combo.addItem("Exogenous predictors", "exogenous")
        self.analysis_type_combo.addItem("Multivariate endogenous", "multivariate")
        self.analysis_type_combo.currentIndexChanged.connect(self._refresh_analysis_controls)
        self.exogenous_list = QListWidget()
        self.exogenous_list.itemChanged.connect(self._update_recommendations)
        self.endogenous_list = QListWidget()
        self.endogenous_list.itemChanged.connect(self._update_recommendations)
        self.future_predictor_input = QPlainTextEdit()
        self.future_predictor_input.setPlaceholderText(
            "Optional date-aligned CSV/TSV table. Required: date and selected predictors. Add a Scenario column for named paths."
        )
        self.auto_forecast_exog_checkbox = QCheckBox(
            "Optionally forecast predictor values independently when none are entered"
        )
        self.import_future_predictors_button = QPushButton("Import future predictors")
        self.import_future_predictors_button.clicked.connect(self._import_future_predictors)
        self.recommendation_label = QLabel(
            "Recommendations appear after loading and selecting variable roles."
        )
        self.recommendation_label.setWordWrap(True)
        self.model_combo = QComboBox()
        self.model_combo.addItems(
            [
                "Exponential smoothing",
                "Naive",
                "Seasonal naive",
                "Historical mean",
                "Linear trend",
                "AR(1)",
                "MA(1)",
                "ARMA(1,1)",
                "ARIMA",
                "SARIMA",
                "Simple exponential smoothing",
                "Holt",
                "Holt-Winters",
            ]
        )
        self.arima_order_spins = [QSpinBox() for _ in range(3)]
        for spin, value in zip(self.arima_order_spins, (1, 1, 1)):
            spin.setRange(0, 5)
            spin.setValue(value)
        self.seasonal_order_spins = [QSpinBox() for _ in range(3)]
        for spin, value in zip(self.seasonal_order_spins, (1, 1, 1)):
            spin.setRange(0, 2)
            spin.setValue(value)
        self.maxlags_spin = QSpinBox()
        self.maxlags_spin.setRange(0, 24)
        self.maxlags_spin.setSpecialValueText("Automatic")
        self.vecm_rank_spin = QSpinBox()
        self.vecm_rank_spin.setRange(0, 10)
        self.vecm_rank_spin.setSpecialValueText("Automatic")
        self.vector_deterministic_combo = QComboBox()
        self.vector_deterministic_combo.addItem("No deterministic terms", "n")
        self.vector_deterministic_combo.addItem("Constant", "c")
        self.vector_deterministic_combo.addItem("Constant and trend", "ct")
        self.horizon_spin = QSpinBox()
        self.horizon_spin.setRange(1, 120)
        self.horizon_spin.setValue(6)
        self.test_size_spin = QSpinBox()
        self.test_size_spin.setRange(0, 120)
        self.test_size_spin.setValue(0)
        self.train_fraction_spin = QSpinBox()
        self.train_fraction_spin.setRange(50, 95)
        self.train_fraction_spin.setValue(80)
        self.validation_combo = QComboBox()
        self.validation_combo.addItem("Single chronological holdout", "holdout")
        self.validation_combo.addItem("Rolling-window validation", "rolling-window")
        self.validation_combo.addItem("Expanding-window validation", "expanding-window")
        self.disable_evaluation_checkbox = QCheckBox(
            "Disable out-of-sample evaluation"
        )
        self.alpha_combo = QComboBox()
        self.alpha_combo.addItems(["0.01", "0.05", "0.10"])
        self.alpha_combo.setCurrentText("0.05")
        self.deterministic_combo = QComboBox()
        self.deterministic_combo.addItems(
            ["Constant", "Constant and trend", "No constant or trend"]
        )
        self.difference_deterministic_combo = QComboBox()
        self.difference_deterministic_combo.addItems(
            ["Constant", "Constant and trend", "No constant or trend"]
        )
        self.second_difference_checkbox = QCheckBox(
            "Include second-difference stationarity tests and plot"
        )
        self.provenance_inputs = {
            "data_source": QLineEdit(),
            "indicator_name": QLineEdit(),
            "methodology": QLineEdit(),
            "source_url": QLineEdit(),
            "units": QLineEdit(),
            "downloaded_date": QLineEdit(),
        }
        self.provenance_inputs["downloaded_date"].setPlaceholderText("YYYY-MM-DD")
        provenance_group = QGroupBox("Data provenance for Chapter Four")
        provenance_form = QFormLayout(provenance_group)
        provenance_labels = {
            "data_source": "Data source",
            "indicator_name": "Indicator name",
            "methodology": "Measurement methodology",
            "source_url": "Source URL",
            "units": "Units",
            "downloaded_date": "Date downloaded",
        }
        for field, label in provenance_labels.items():
            provenance_form.addRow(label, self.provenance_inputs[field])
        self.provenance_group = provenance_group
        self.run_button = QPushButton("Analyze and forecast")
        self.run_button.clicked.connect(self.run_analysis)
        self.transform_combo = QComboBox()
        self.transform_combo.addItem("First difference", "first_difference")
        self.transform_combo.addItem("Second difference", "second_difference")
        self.transform_combo.addItem("Log", "log")
        self.transform_combo.addItem("Percentage change", "percentage_change")
        self.transform_combo.addItem("Seasonal difference", "seasonal_difference")
        self.transform_combo.addItem("Moving average", "moving_average")
        self.transform_combo.addItem("Rolling standard deviation", "rolling_standard_deviation")
        self.transform_button = QPushButton("Create transformed copy")
        self.transform_button.clicked.connect(self._create_transformed_copy)

        self.quality_label = QLabel("Load or paste observations to begin.")
        self.quality_label.setWordWrap(True)
        self.preview_table = QTableWidget()
        self.preview_table.setAlternatingRowColors(True)
        self.preview_table.setEditTriggers(
            QTableWidget.EditTrigger.DoubleClicked
            | QTableWidget.EditTrigger.EditKeyPressed
            | QTableWidget.EditTrigger.AnyKeyPressed
        )
        self.results = QTextEdit()
        self.results.setReadOnly(True)
        self.results.setPlaceholderText(
            "Descriptive statistics, stationarity tests, diagnostics, and forecast results will appear here."
        )
        self.forecast_table = QTableWidget(0, 4)
        self.forecast_table.setHorizontalHeaderLabels(
            ["Period", "Forecast", "Lower interval", "Upper interval"]
        )
        self.holdout_table = QTableWidget(0, 3)
        self.holdout_table.setHorizontalHeaderLabels(
            ["Period", "Actual", "Predicted"]
        )
        self.model_comparison_table = QTableWidget(0, 7)
        self.model_comparison_table.setHorizontalHeaderLabels(
            ["Model", "MSE", "RMSE", "MAE", "MAPE (%)", "AIC", "BIC"]
        )
        self.chart_canvas = None
        self.tabs = QTabWidget()
        self._tab_history = []
        self._active_tab_id = None
        self._restoring_tab = False
        self.back_button = QPushButton("Back")
        self.back_button.setToolTip("Return to the previously viewed time-series tab.")
        self.back_button.clicked.connect(self._go_back)
        self.main_app_button = QPushButton("Return to main app")
        self.main_app_button.clicked.connect(self._return_to_main_app)
        self._build_layout()
        self._active_tab_id = id(self.tabs.currentWidget())
        self.tabs.currentChanged.connect(self._record_tab_navigation)
        self._update_back_button()
        self.model_combo.currentIndexChanged.connect(self._refresh_model_settings)
        self._load_projects()

    def _build_layout(self):
        outer = QVBoxLayout(self)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        content = QWidget()
        root = QVBoxLayout(content)
        project_row = QHBoxLayout()
        project_row.addWidget(QLabel("Project"))
        project_row.addWidget(self.project_combo, 1)
        project_row.addWidget(QLabel("Managed dataset"))
        project_row.addWidget(self.dataset_combo, 1)
        project_row.addWidget(self.open_button)
        project_row.addWidget(self.paste_button)
        root.addLayout(project_row)

        editor_actions = QHBoxLayout()
        editor_actions.addWidget(self.add_row_button)
        editor_actions.addWidget(self.delete_row_button)
        editor_actions.addWidget(self.sort_button)
        editor_actions.addWidget(self.save_revision_button)
        editor_actions.addStretch()
        root.addLayout(editor_actions)
        root.addWidget(self.quality_label)

        navigation_row = QHBoxLayout()
        navigation_row.addWidget(self.back_button)
        navigation_row.addStretch()
        navigation_row.addWidget(self.main_app_button)
        root.addLayout(navigation_row)

        self.tabs.addTab(self.preview_table, "Data preview and editor")
        self.tabs.addTab(self.results, "Results")
        self.tabs.addTab(self.forecast_table, "Forecast table")
        self.tabs.addTab(self.holdout_table, "Holdout comparison")
        self.tabs.addTab(self.model_comparison_table, "Model comparison")
        self.tabs.setMinimumHeight(220)
        self.tabs.setMaximumHeight(320)
        self.tabs.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        root.addWidget(self.tabs)

        form = QFormLayout()
        self.analysis_form = form
        form.addRow("Analysis structure", self.analysis_type_combo)
        form.addRow("Time/date variable", self.date_combo)
        form.addRow("Observation variable", self.value_combo)
        form.addRow("Exogenous predictors (optional)", self.exogenous_list)
        form.addRow("Endogenous variables for VAR/VECM", self.endogenous_list)
        form.addRow("Future exogenous values / scenario input", self.future_predictor_input)
        form.addRow(self.import_future_predictors_button)
        form.addRow(self.auto_forecast_exog_checkbox)
        form.addRow(self.recommendation_label)
        form.addRow("Forecast model", self.model_combo)
        arima_order_row = QHBoxLayout()
        for label, spin in zip(("p", "d", "q"), self.arima_order_spins):
            arima_order_row.addWidget(QLabel(label))
            arima_order_row.addWidget(spin)
        self.arima_order_label = QLabel("ARIMA order")
        self.arima_order_row = arima_order_row
        form.addRow(self.arima_order_label, arima_order_row)
        seasonal_order_row = QHBoxLayout()
        for label, spin in zip(("P", "D", "Q"), self.seasonal_order_spins):
            seasonal_order_row.addWidget(QLabel(label))
            seasonal_order_row.addWidget(spin)
        self.seasonal_order_label = QLabel("SARIMA seasonal order (period is detected)")
        self.seasonal_order_row = seasonal_order_row
        form.addRow(self.seasonal_order_label, seasonal_order_row)
        self.vector_settings_label = QLabel("Vector-model lag order")
        self.vector_settings_row = QHBoxLayout()
        self.vector_settings_row.addWidget(QLabel("Maximum lag"))
        self.vector_settings_row.addWidget(self.maxlags_spin)
        self.vector_settings_row.addWidget(QLabel("VECM rank"))
        self.vector_settings_row.addWidget(self.vecm_rank_spin)
        self.vector_settings_row.addWidget(QLabel("Deterministic terms"))
        self.vector_settings_row.addWidget(self.vector_deterministic_combo)
        form.addRow(self.vector_settings_label, self.vector_settings_row)
        form.addRow("Forecast horizon (periods)", self.horizon_spin)
        form.addRow("Training percentage (automatic split)", self.train_fraction_spin)
        form.addRow("Holdout observations (0 = automatic 20%)", self.test_size_spin)
        form.addRow("Validation strategy", self.validation_combo)
        form.addRow(self.disable_evaluation_checkbox)
        form.addRow("Significance level", self.alpha_combo)
        form.addRow("Unit-root test deterministic terms", self.deterministic_combo)
        form.addRow(
            "Differenced-series deterministic terms",
            self.difference_deterministic_combo,
        )
        form.addRow("Optional transformed series", self.second_difference_checkbox)
        transform_row = QHBoxLayout()
        transform_row.addWidget(self.transform_combo)
        transform_row.addWidget(self.transform_button)
        form.addRow("Transformation", transform_row)
        root.addLayout(form)
        root.addWidget(self.provenance_group)

        bottom = QHBoxLayout()
        bottom.addWidget(self.run_button)
        self.export_csv_button = QPushButton("Export working data CSV")
        self.export_csv_button.clicked.connect(self._export_csv)
        bottom.addWidget(self.export_csv_button)
        self.export_chart_button = QPushButton("Export editable charts XLSX")
        self.export_chart_button.clicked.connect(self._export_chart)
        bottom.addWidget(self.export_chart_button)
        self.export_excel_button = QPushButton("Export results XLSX")
        self.export_excel_button.clicked.connect(self._export_excel)
        bottom.addWidget(self.export_excel_button)
        self.export_pdf_button = QPushButton("Export report PDF")
        self.export_pdf_button.clicked.connect(self._export_pdf)
        bottom.addWidget(self.export_pdf_button)
        self.export_report_button = QPushButton("Export report DOCX")
        self.export_report_button.clicked.connect(self._export_report)
        bottom.addWidget(self.export_report_button)
        root.addLayout(bottom)
        root.addStretch(1)
        scroll.setWidget(content)
        outer.addWidget(scroll)
        self.content_scroll_area = scroll
        self._refresh_analysis_controls()

    def _record_tab_navigation(self, index):
        widget = self.tabs.widget(index)
        if widget is None:
            return
        widget_id = id(widget)
        if (
            not self._restoring_tab
            and self._active_tab_id is not None
            and self._active_tab_id != widget_id
        ):
            self._tab_history.append(self._active_tab_id)
        self._active_tab_id = widget_id
        self._update_back_button()

    def _select_tab(self, widget):
        index = self.tabs.indexOf(widget)
        if index < 0:
            return
        self._restoring_tab = True
        try:
            self.tabs.setCurrentIndex(index)
        finally:
            self._restoring_tab = False
        current_widget = self.tabs.currentWidget()
        self._active_tab_id = id(current_widget) if current_widget is not None else None
        self._update_back_button()

    def _update_back_button(self):
        current_widget = self.tabs.currentWidget()
        current_id = id(current_widget) if current_widget is not None else None
        has_previous_tab = any(
            id(self.tabs.widget(index)) == widget_id and widget_id != current_id
            for widget_id in self._tab_history
            for index in range(self.tabs.count())
        )
        self.back_button.setEnabled(
            has_previous_tab or current_widget is not self.preview_table
        )

    def _go_back(self):
        while self._tab_history:
            previous_id = self._tab_history.pop()
            previous_tab = next(
                (
                    self.tabs.widget(index)
                    for index in range(self.tabs.count())
                    if id(self.tabs.widget(index)) == previous_id
                ),
                None,
            )
            if previous_tab is not None and previous_tab is not self.tabs.currentWidget():
                self._select_tab(previous_tab)
                return
        self._select_tab(self.preview_table)

    def _return_to_main_app(self):
        main_window = self.parentWidget()
        self.close()
        if main_window is not None:
            main_window.showNormal()
            main_window.raise_()
            main_window.activateWindow()

    def _clear_analysis_views(self):
        for canvas in self.chart_canvases.values():
            index = self.tabs.indexOf(canvas)
            if index >= 0:
                self.tabs.removeTab(index)
            canvas.deleteLater()
        self.chart_canvases = {}
        self.last_figures = {}
        self.last_figure = None
        self.chart_canvas = None
        self.results.clear()
        self.forecast_table.setRowCount(0)
        self.holdout_table.setRowCount(0)
        self.model_comparison_table.setRowCount(0)
        self._tab_history.clear()
        self._select_tab(self.preview_table)
        self._tab_history.clear()
        self._update_back_button()

    def _load_projects(self):
        self.project_combo.blockSignals(True)
        self.project_combo.clear()
        for project in self.database.get_projects():
            self.project_combo.addItem(project["name"], project["id"])
        self.project_combo.blockSignals(False)
        if self.project_combo.count():
            main_window = self.parentWidget()
            active_project_id = getattr(
                getattr(main_window, "data_page", None),
                "current_project_id",
                None,
            )
            active_index = self.project_combo.findData(active_project_id)
            self.project_combo.setCurrentIndex(active_index if active_index >= 0 else 0)
        else:
            self._set_dataframe(pd.DataFrame())
            self.quality_label.setText(
                "No projects are available. Create a project in the main application, or open a data file."
            )

    def _refresh_project_datasets(self, *_):
        project_id = self.project_combo.currentData()
        self.dataset_combo.blockSignals(True)
        self.dataset_combo.clear()
        if project_id is not None:
            for dataset in self.database.get_project_datasets(project_id):
                self.dataset_combo.addItem(
                    dataset["filename"],
                    dataset["id"],
                )
        self.dataset_combo.blockSignals(False)
        if self.dataset_combo.count():
            self.dataset_combo.setCurrentIndex(0)
        elif self.dataframe.empty:
            self._set_dataframe(pd.DataFrame())

    def _load_selected_dataset(self, *_):
        dataset_id = self.dataset_combo.currentData()
        if dataset_id is None:
            return
        dataset = self.database.get_dataset(dataset_id)
        if dataset is None:
            self.quality_label.setText("The selected dataset record no longer exists.")
            return
        try:
            frame = read_time_series_file(dataset["file_path"])
        except (OSError, ValueError, ImportError) as error:
            QMessageBox.warning(self, "Dataset could not be loaded", str(error))
            return
        self._set_dataframe(frame, dataset_id)

    def _open_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open time-series data",
            str(Path.cwd()),
            "Supported files (*.csv *.xlsx *.xls *.pdf)",
        )
        if not path:
            return
        try:
            frame = read_time_series_file(path)
        except (OSError, ValueError, ImportError) as error:
            QMessageBox.warning(self, "Import failed", str(error))
            return
        self._set_dataframe(frame)
        self.quality_label.setText(f"Loaded {Path(path).name}. Review mappings and data quality before analysis.")

    def _paste_data(self):
        from PySide6.QtWidgets import QApplication

        try:
            frame = parse_pasted_data(QApplication.clipboard().text())
        except ValueError as error:
            QMessageBox.warning(self, "Paste failed", str(error))
            return
        self._set_dataframe(frame)
        self.quality_label.setText("Pasted data loaded. Review the detected columns and rows before analysis.")

    def _set_dataframe(self, dataframe: pd.DataFrame, source_dataset_id=None):
        self.dataframe = dataframe.copy()
        self.original_dataframe = dataframe.copy(deep=True)
        self.preprocessing_log = []
        self.source_dataset_id = source_dataset_id
        self.last_result = None
        self._clear_analysis_views()
        self._populate_preview()
        self._populate_mappings()

    def _populate_preview(self):
        self.preview_table.clear()
        self.preview_table.setRowCount(len(self.dataframe))
        self.preview_table.setColumnCount(len(self.dataframe.columns))
        self.preview_table.setHorizontalHeaderLabels([str(column) for column in self.dataframe.columns])
        for row_index, row in enumerate(self.dataframe.itertuples(index=False, name=None)):
            for column_index, value in enumerate(row):
                text = "" if pd.isna(value) else str(value)
                self.preview_table.setItem(
                    row_index,
                    column_index,
                    QTableWidgetItem(text),
                )
        self.preview_table.resizeColumnsToContents()

    def _populate_mappings(self):
        self.date_combo.blockSignals(True)
        self.value_combo.blockSignals(True)
        self.date_combo.clear()
        self.value_combo.clear()
        self.exogenous_list.clear()
        self.endogenous_list.clear()
        if not self.dataframe.empty:
            self.date_combo.addItems([str(column) for column in self.dataframe.columns])
            self.value_combo.addItems([str(column) for column in self.dataframe.columns])
            detection = detect_time_series(self.dataframe)
            if detection["date_column"]:
                self.date_combo.setCurrentText(detection["date_column"])
            if detection["numeric_columns"]:
                candidate = next(
                    (
                        column
                        for column in detection["numeric_columns"]
                        if column != detection["date_column"]
                    ),
                    None,
                )
                if candidate:
                    self.value_combo.setCurrentText(candidate)
            for column in detection["numeric_columns"]:
                exogenous_item = QListWidgetItem(column)
                exogenous_item.setFlags(
                    exogenous_item.flags() | Qt.ItemFlag.ItemIsUserCheckable
                )
                exogenous_item.setCheckState(Qt.CheckState.Unchecked)
                self.exogenous_list.addItem(exogenous_item)
                endogenous_item = QListWidgetItem(column)
                endogenous_item.setFlags(
                    endogenous_item.flags() | Qt.ItemFlag.ItemIsUserCheckable
                )
                endogenous_item.setCheckState(Qt.CheckState.Unchecked)
                self.endogenous_list.addItem(endogenous_item)
            self.quality_label.setText(
                f"Detected frequency: {detection['frequency_label']}. "
                f"Potential numeric variables: {len(detection['numeric_columns'])}. "
                f"Missing/invalid dates: {detection['missing_date_count']}; "
                f"duplicate dates: {detection['duplicate_date_count']}. "
                "Automatic mapping is a suggestion—confirm it before analysis."
            )
            self._update_recommendations()
        self.date_combo.blockSignals(False)
        self.value_combo.blockSignals(False)
        self._refresh_analysis_controls()

    def _selected_list_items(self, widget):
        return [
            widget.item(index).text()
            for index in range(widget.count())
            if widget.item(index).checkState() == Qt.CheckState.Checked
        ]

    def _update_recommendations(self):
        if self.dataframe.empty or not self.date_combo.currentText():
            return
        analysis_type = self.analysis_type_combo.currentData()
        value = self.value_combo.currentText()
        exogenous = self._selected_list_items(self.exogenous_list)
        endogenous = self._selected_list_items(self.endogenous_list)
        frame = (
            self._working_frame_from_table()
            if self.preview_table.columnCount()
            else self.dataframe
        )
        try:
            if analysis_type == "univariate":
                recommendation = self._recommend(
                    frame,
                    self.date_combo.currentText(),
                    dependent_variables=[value] if value else [],
                )
            elif analysis_type == "exogenous":
                recommendation = self._recommend(
                    frame,
                    self.date_combo.currentText(),
                    dependent_variables=[value] if value else [],
                    exogenous_variables=exogenous,
                )
            else:
                recommendation = self._recommend(
                    frame,
                    self.date_combo.currentText(),
                    endogenous_variables=endogenous,
                )
        except (TypeError, ValueError) as error:
            self.recommendation_label.setText(f"Recommendations unavailable: {error}")
            return
        recommended = ", ".join(
            item["method"] for item in recommendation["recommended"]
        ) or "None"
        conditional = "; ".join(
            f"{item['method']}: {item['reason']}"
            for item in recommendation["conditional"]
        ) or "None"
        unsuitable = "; ".join(
            f"{item['method']}: {item['reason']}"
            for item in recommendation["unsuitable"]
        ) or "None"
        self.recommendation_label.setText(
            f"Recommended: {recommended}\n"
            f"Conditional: {conditional}\n"
            f"Not suitable: {unsuitable}"
        )

    def _recommend(self, frame, date_column, **roles):
        digest = pd.util.hash_pandas_object(frame, index=True).values.tobytes()
        role_key = tuple(
            (name, tuple(value) if isinstance(value, (list, tuple)) else value)
            for name, value in sorted(roles.items())
        )
        key = (tuple(map(str, frame.columns)), hash(digest), date_column, role_key)
        if key not in self._recommendation_cache:
            self._recommendation_cache[key] = recommend_time_series_methods(
                frame, date_column, **roles
            )
            if len(self._recommendation_cache) > 32:
                self._recommendation_cache.pop(next(iter(self._recommendation_cache)))
        return self._recommendation_cache[key]

    def _refresh_analysis_controls(self, *_):
        mode = self.analysis_type_combo.currentData()
        self.exogenous_list.setVisible(mode == "exogenous")
        self.endogenous_list.setVisible(mode == "multivariate")
        self.future_predictor_input.setVisible(mode == "exogenous")
        self.import_future_predictors_button.setVisible(mode == "exogenous")
        self.auto_forecast_exog_checkbox.setVisible(mode == "exogenous")
        self.arima_order_label.setVisible(mode != "multivariate")
        self.seasonal_order_label.setVisible(mode in {"univariate", "exogenous"})
        self.vector_settings_label.setVisible(mode == "multivariate")
        for widget in (
            self.maxlags_spin,
            self.vecm_rank_spin,
            self.vector_deterministic_combo,
        ):
            widget.setVisible(mode == "multivariate")
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        if mode == "univariate":
            self.model_combo.addItems(
                [
                    "Exponential smoothing", "Naive", "Seasonal naive",
                    "Historical mean", "Linear trend", "AR(1)", "MA(1)",
                    "ARMA(1,1)", "ARIMA", "SARIMA",
                    "Simple exponential smoothing", "Holt", "Holt-Winters",
                ]
            )
        elif mode == "exogenous":
            self.model_combo.addItems(["ARIMAX", "SARIMAX", "Regression"])
        else:
            self.model_combo.addItems(["VAR", "VECM", "Johansen cointegration"])
        self.model_combo.blockSignals(False)
        self._refresh_model_settings()
        self._update_recommendations()

    def _import_future_predictors(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Import future predictor values",
            str(Path.cwd()),
            "CSV and Excel files (*.csv *.xlsx *.xls)",
        )
        if not path:
            return
        try:
            future = read_time_series_file(path)
        except (OSError, ValueError, ImportError) as error:
            QMessageBox.warning(self, "Future predictor import failed", str(error))
            return
        date_column = self.date_combo.currentText()
        if date_column not in future.columns:
            if future.empty or not len(future.columns):
                QMessageBox.warning(self, "Missing date column", "The imported file is empty.")
                return
            first_column = future.columns[0]
            if parse_time_values(future[first_column]).notna().mean() < 0.7:
                QMessageBox.warning(
                    self,
                    "Missing date column",
                    f"Select a date column named '{date_column}' in the imported file, "
                    "or make the first column recognizable as dates.",
                )
                return
            future = future.rename(columns={first_column: date_column})
        self.future_predictor_input.setPlainText(future.to_csv(index=False))

    def _refresh_model_settings(self, *_):
        selected_model = self.model_combo.currentText()
        show_arima = selected_model in {"ARIMA", "SARIMA", "ARIMAX", "SARIMAX"}
        show_seasonal = selected_model in {"SARIMA", "SARIMAX"}
        self.arima_order_label.setVisible(show_arima)
        self.seasonal_order_label.setVisible(show_seasonal)
        for spin in self.arima_order_spins:
            spin.setVisible(show_arima)
        for spin in self.seasonal_order_spins:
            spin.setVisible(show_seasonal)
        univariate = self.analysis_type_combo.currentData() == "univariate"
        for widget in (
            self.deterministic_combo,
            self.difference_deterministic_combo,
            self.second_difference_checkbox,
            self.transform_combo,
            self.transform_button,
        ):
            widget.setVisible(univariate)

    def _review_preprocessing(self, frame):
        try:
            assessment = inspect_time_series_dataset(
                frame, self.date_combo.currentText()
            )
        except (TypeError, ValueError) as error:
            QMessageBox.warning(self, "Data inspection failed", str(error))
            return None
        if not assessment["issues"]:
            return frame
        if "date/time value(s) are invalid or missing." in " ".join(
            assessment["issues"]
        ):
            QMessageBox.warning(
                self,
                "Invalid timestamps",
                "Correct invalid or missing timestamps in the data preview before analysis. "
                "No rows were deleted or changed.",
            )
            return None
        answer = QMessageBox.question(
            self,
            "Review time-series data issues",
            "Issues detected:\n- "
            + "\n- ".join(assessment["issues"])
            + "\n\nReview and explicitly approve one preprocessing operation for the working copy?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return None
        numeric_columns = [
            column for column in assessment["numeric_columns"]
            if column != self.date_combo.currentText()
        ]
        if not numeric_columns and assessment["duplicate_timestamps"] == 0:
            QMessageBox.warning(
                self,
                "Preprocessing unavailable",
                "No supported numeric-column operation is available. The source data is unchanged.",
            )
            return None
        choices = []
        if assessment["duplicate_timestamps"]:
            choices.extend(
                [
                    ("Aggregate duplicate timestamps by mean", {"action": "aggregate_mean"}),
                    ("Keep first row for each timestamp", {"action": "keep_first"}),
                    ("Keep last row for each timestamp", {"action": "keep_last"}),
                ]
            )
        if assessment["missing_periods"] and assessment["frequency"]:
            choices.append(
                (
                    f"Align to {assessment['frequency']} frequency using mean",
                    {
                        "action": "resample",
                        "frequency": assessment["frequency"],
                        "aggregation": "mean",
                    },
                )
            )
        if numeric_columns:
            column, accepted = QInputDialog.getItem(
                self, "Select variable", "Variable to clean:", numeric_columns, 0, False
            )
            if not accepted:
                return None
            choices.extend(
                [
                    (f"Drop rows missing {column}", {"action": "drop_missing_rows", "column": column}),
                    (f"Interpolate interior missing values in {column}", {"action": "interpolate", "column": column}),
                    (f"Forward fill missing values in {column}", {"action": "forward_fill", "column": column}),
                ]
            )
        labels = [choice[0] for choice in choices]
        selected, accepted = QInputDialog.getItem(
            self, "Approve preprocessing", "Choose one operation:", labels, 0, False
        )
        if not accepted:
            return None
        operation = choices[labels.index(selected)][1]
        try:
            cleaned, operations = preprocess_time_series_dataframe(
                frame, self.date_combo.currentText(), [operation]
            )
            remaining = inspect_time_series_dataset(
                cleaned, self.date_combo.currentText()
            )
        except (TypeError, ValueError) as error:
            QMessageBox.warning(self, "Preprocessing was not applied", str(error))
            return None
        detail = operations[-1]
        remaining_issues = remaining["issues"]
        confirmation = QMessageBox.question(
            self,
            "Confirm working-copy operation",
            f"{detail['implication']}\nRows before: {detail['rows_before']}; "
            f"rows after: {detail['rows_after']}.\n"
            + (
                "Remaining issues: " + "; ".join(remaining_issues) + "\n"
                if remaining_issues
                else ""
            )
            + "\nApply to the working copy? "
            "The original imported dataset remains unchanged.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirmation != QMessageBox.StandardButton.Yes:
            return None
        selected_date = self.date_combo.currentText()
        selected_value = self.value_combo.currentText()
        selected_exogenous = self._selected_list_items(self.exogenous_list)
        selected_endogenous = self._selected_list_items(self.endogenous_list)
        self.dataframe = cleaned.copy(deep=True)
        self.preprocessing_log.extend(operations)
        self._populate_preview()
        self._populate_mappings()
        self.date_combo.setCurrentText(selected_date)
        self.value_combo.setCurrentText(selected_value)
        for widget, selected in (
            (self.exogenous_list, selected_exogenous),
            (self.endogenous_list, selected_endogenous),
        ):
            for index in range(widget.count()):
                item = widget.item(index)
                item.setCheckState(
                    Qt.CheckState.Checked
                    if item.text() in selected
                    else Qt.CheckState.Unchecked
                )
        self._update_recommendations()
        return cleaned

    def _working_frame_from_table(self) -> pd.DataFrame:
        columns = [self.preview_table.horizontalHeaderItem(i).text() for i in range(self.preview_table.columnCount())]
        rows = []
        for row_index in range(self.preview_table.rowCount()):
            rows.append(
                [
                    self.preview_table.item(row_index, column_index).text()
                    if self.preview_table.item(row_index, column_index)
                    else None
                    for column_index in range(self.preview_table.columnCount())
                ]
            )
        return pd.DataFrame(rows, columns=columns)

    def _add_observation(self):
        if self.preview_table.columnCount() == 0:
            self._set_dataframe(pd.DataFrame(columns=["Date", "Value"]))
        row = self.preview_table.rowCount()
        self.preview_table.insertRow(row)
        for column in range(self.preview_table.columnCount()):
            self.preview_table.setItem(row, column, QTableWidgetItem(""))
        self.quality_label.setText("Added a blank observation row; enter its date and value. No value was fabricated.")

    def _delete_observation(self):
        row = self.preview_table.currentRow()
        if row < 0:
            QMessageBox.information(self, "Select a row", "Select an observation row before deleting it.")
            return
        answer = QMessageBox.question(
            self,
            "Delete observation",
            "Delete the selected observation from this working copy?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.preview_table.removeRow(row)

    def _sort_by_time(self):
        if self.date_combo.currentIndex() < 0:
            return
        frame = self._working_frame_from_table()
        date_column = self.date_combo.currentText()
        frame["__sort_date"] = pd.to_datetime(frame[date_column], errors="coerce")
        frame = frame.sort_values("__sort_date", kind="stable", na_position="last").drop(columns="__sort_date")
        self.dataframe = frame
        self._populate_preview()

    def _save_working_revision(self):
        frame = self._working_frame_from_table()
        if frame.empty:
            QMessageBox.warning(self, "No data", "There is no working dataset to save.")
            return
        project_id = self.project_combo.currentData()
        if project_id is None:
            QMessageBox.warning(self, "Select a project", "Select a project before saving a managed dataset.")
            return
        try:
            if self.source_dataset_id is not None:
                source = self.database.get_dataset(self.source_dataset_id)
                if source is None or source["project_id"] != project_id:
                    raise ValueError("The selected source dataset does not belong to this project.")
                revision_id = self.database.create_dataset_revision(
                    self.source_dataset_id,
                    frame,
                    label="Time-series data",
                )
            else:
                revision_id = self.database.create_dataset_from_frame(
                    project_id,
                    "Time-series data.csv",
                    frame,
                )
        except (OSError, TypeError, ValueError) as error:
            QMessageBox.critical(self, "Could not save dataset", str(error))
            return

        self.source_dataset_id = revision_id
        main_window = self.parentWidget()
        data_page = getattr(main_window, "data_page", None)
        if data_page is not None and data_page.current_project_id == project_id:
            data_page.current_dataset_id = revision_id
            data_page.current_dataframe = frame.copy()
            data_page.display_dataframe(frame)
            data_page.refresh_dataset_selector(revision_id)
            data_page.publish_dataset_state()
        self.dataset_combo.blockSignals(True)
        self.dataset_combo.clear()
        for dataset in self.database.get_project_datasets(project_id):
            self.dataset_combo.addItem(dataset["filename"], dataset["id"])
        self.dataset_combo.setCurrentIndex(self.dataset_combo.findData(revision_id))
        self.dataset_combo.blockSignals(False)
        self.dataframe = frame.copy()
        self.original_dataframe = frame.copy(deep=True)
        QMessageBox.information(
            self,
            "Dataset revision saved",
            "The original dataset is preserved. The edited or transformed data is saved as a new managed revision.",
        )

    def run_analysis(self):
        if self.preview_table.columnCount() == 0:
            QMessageBox.warning(self, "No data", "Open, paste, or manually enter observations first.")
            return
        date_column = self.date_combo.currentText()
        value_column = self.value_combo.currentText()
        frame = self._working_frame_from_table()
        reviewed_frame = self._review_preprocessing(frame)
        if reviewed_frame is None:
            return
        frame = reviewed_frame
        mode = self.analysis_type_combo.currentData()
        recommendation = None
        try:
            order = tuple(spin.value() for spin in self.arima_order_spins)
            seasonal_order = tuple(spin.value() for spin in self.seasonal_order_spins)
            alpha = float(self.alpha_combo.currentText())
            horizon = self.horizon_spin.value()
            test_size = self.test_size_spin.value() or None
            if self.disable_evaluation_checkbox.isChecked():
                test_size = 0
            if mode == "univariate":
                recommendation = self._recommend(
                    frame,
                    date_column,
                    dependent_variables=[value_column],
                )
                selected_model = self.model_combo.currentText()
                if selected_model not in {
                    item["method"] for item in recommendation["recommended"]
                } | {
                    item["method"] for item in recommendation["conditional"]
                }:
                    raise ValueError(
                        f"{selected_model} is not recommended for the inspected data: "
                        + " ".join(
                            item["reason"] for item in recommendation["unsuitable"]
                        )
                    )
                result = analyze_time_series(
                    frame,
                    date_column,
                    value_column,
                    forecast_horizon=horizon,
                    significance_level=alpha,
                    model_name=selected_model,
                    deterministic_specification=self.deterministic_combo.currentText(),
                    difference_deterministic_specification=self.difference_deterministic_combo.currentText(),
                    arima_order=order,
                    seasonal_order=seasonal_order,
                    include_second_difference=self.second_difference_checkbox.isChecked(),
                    test_size=test_size,
                    train_fraction=self.train_fraction_spin.value() / 100,
                    validation_strategy=self.validation_combo.currentData(),
                )
            elif mode == "exogenous":
                predictors = self._selected_list_items(self.exogenous_list)
                recommendation = self._recommend(
                    frame,
                    date_column,
                    dependent_variables=[value_column],
                    exogenous_variables=predictors,
                )
                recommendation_name = (
                    "Regression-based forecasting"
                    if self.model_combo.currentText() == "Regression"
                    else self.model_combo.currentText()
                )
                available_methods = {
                    item["method"] for item in recommendation["recommended"]
                } | {
                    item["method"] for item in recommendation["conditional"]
                }
                if recommendation_name not in available_methods:
                    reasons = [
                        item["reason"] for item in recommendation["unsuitable"]
                    ]
                    raise ValueError(
                        f"{self.model_combo.currentText()} is not recommended for the inspected data. "
                        + " ".join(reasons)
                    )
                future_text = self.future_predictor_input.toPlainText().strip()
                future_exog = None
                scenarios = None
                if future_text:
                    future_frame = parse_pasted_data(future_text)
                    if "Scenario" in future_frame.columns:
                        scenarios = {
                            str(name): group.drop(columns=["Scenario"]).reset_index(drop=True)
                            for name, group in future_frame.groupby("Scenario", sort=False)
                        }
                    else:
                        future_exog = future_frame
                result = analyze_exogenous_time_series(
                    frame,
                    date_column,
                    value_column,
                    predictors,
                    forecast_horizon=horizon,
                    model_name=self.model_combo.currentText(),
                    order=order,
                    seasonal_order=seasonal_order,
                    future_exog=future_exog,
                    scenarios=scenarios,
                    auto_forecast_exog=self.auto_forecast_exog_checkbox.isChecked(),
                    test_size=test_size,
                    significance_level=alpha,
                )
            else:
                endogenous = self._selected_list_items(self.endogenous_list)
                recommendation = self._recommend(
                    frame,
                    date_column,
                    endogenous_variables=endogenous,
                )
                selected_model = self.model_combo.currentText()
                available_methods = {
                    item["method"] for item in recommendation["recommended"]
                } | {
                    item["method"] for item in recommendation["conditional"]
                }
                if selected_model not in available_methods:
                    reasons = [
                        item["reason"]
                        for item in recommendation["unsuitable"]
                    ]
                    raise ValueError(
                        f"{selected_model} is not recommended for the inspected data. "
                        + " ".join(reasons)
                    )
                result = analyze_multivariate_time_series(
                    frame,
                    date_column,
                    endogenous,
                    model_name=self.model_combo.currentText(),
                    forecast_horizon=horizon,
                    maxlags=self.maxlags_spin.value() or None,
                    deterministic=self.vector_deterministic_combo.currentData(),
                    significance_level=alpha,
                    test_size=test_size,
                    cointegration_rank=self.vecm_rank_spin.value() or None,
                )
        except (ValueError, TypeError, np.linalg.LinAlgError) as error:
            QMessageBox.warning(self, "Analysis could not be completed", str(error))
            return

        self.dataframe = frame
        result["analysis_type"] = mode
        result["roles"] = (
            recommendation["roles"] if recommendation is not None else {}
        )
        result["recommendations"] = (
            {
                key: recommendation[key]
                for key in ("recommended", "conditional", "unsuitable")
            }
            if recommendation is not None
            else {}
        )
        result["preprocessing_operations"] = list(self.preprocessing_log)
        self.last_result = result
        self.last_provenance = {
            field: widget.text().strip()
            for field, widget in self.provenance_inputs.items()
        }
        result["measurement_units"] = self.last_provenance.get("units") or ""
        project_id = self.project_combo.currentData()
        if project_id is not None:
            try:
                self.database.save_time_series_analysis(
                    project_id,
                    self.source_dataset_id,
                    self.last_provenance,
                    result,
                )
            except (TypeError, ValueError, OSError) as error:
                QMessageBox.warning(
                    self,
                    "Analysis could not be saved",
                    f"The analysis ran, but its results and provenance could not be saved to the project: {error}",
                )
        if result.get("model_name") == "Johansen cointegration":
            self.results.setPlainText(self._format_extended_result(result, self.last_provenance))
            for canvas in self.chart_canvases.values():
                index = self.tabs.indexOf(canvas)
                if index >= 0:
                    self.tabs.removeTab(index)
                canvas.deleteLater()
            self.chart_canvases = {}
            self.last_figures = {}
            self.last_figure = None
            self.forecast_table.setRowCount(0)
            self.holdout_table.setRowCount(0)
            self.model_comparison_table.setRowCount(0)
        elif result.get("analysis_type") in {"exogenous", "multivariate"}:
            self.results.setPlainText(self._format_extended_result(result, self.last_provenance))
            self._show_extended_chart(frame, result)
            self._show_extended_forecasts(result)
            self.model_comparison_table.setRowCount(0)
        else:
            self.results.setPlainText(self._format_result(result, self.last_provenance))
            self._show_chart(frame, result)
            self._show_forecast(result)
            self._show_model_comparison(result)
        self.tabs.setCurrentIndex(1)

    @staticmethod
    def _format_extended_result(result, provenance=None):
        lines = [
            f"{result['model_specification']} analysis",
            f"Selected variables: {result.get('dependent_variable', result.get('endogenous_variables', result.get('variables')))}",
            f"Frequency: {result.get('frequency')}",
            f"Observations: {result['rows']}",
            f"Chronological holdout: {result.get('model_evaluation_design')}",
            f"Forecast limitation: {result.get('forecast_limitation') or 'None'}",
            f"Future predictor source: {result.get('future_predictor_source') or 'Not supplied'}",
            f"Forecast interval assumption: {result.get('forecast_interval_assumption', 'Not applicable')}",
            f"Statistical warnings: {result.get('statistical_warnings', [])}",
            f"Information criteria: AIC={result.get('aic')}; BIC={result.get('bic')}",
            f"Diagnostics: {result.get('diagnostics')}",
            f"Preprocessing operations: {result.get('preprocessing_operations', [])}",
        ]
        if result.get("model_name") == "Johansen cointegration":
            lines.extend(
                [
                    f"Selected cointegration rank: {result['rank']}",
                    f"Trace statistics: {result['trace_statistics']}",
                    f"Critical values: {result['critical_values']}",
                    f"Integration-order screening: {result.get('integration_profiles')}",
                    f"Interpretation limitation: {result['interpretation_note']}",
                ]
            )
        recommendations = result.get("recommendations", {})
        for category in ("recommended", "conditional", "unsuitable"):
            items = recommendations.get(category, [])
            if items:
                lines.append(
                    f"{category.title()} methods: "
                    + "; ".join(
                        f"{item['method']} - {item['reason']}" for item in items
                    )
                )
        if result.get("evaluation"):
            lines.extend(["", "Out-of-sample accuracy:", str(result["evaluation"])])
        if result.get("parameter_inference"):
            lines.extend(["", "Model parameter estimates and p-values:"])
            lines.extend(
                f"  {name}: estimate={values['estimate']}, p={values['p_value']}"
                for name, values in result["parameter_inference"].items()
            )
        if result.get("cointegration"):
            lines.extend(["", f"Johansen cointegration: {result['cointegration']}"])
        if result.get("granger_causality"):
            lines.extend(["", f"Granger causality: {result['granger_causality']}"])
        if result.get("stability") is not None:
            lines.append(f"VAR stable: {result['stability']}")
        if result.get("impulse_responses"):
            lines.append("Impulse responses are available in the IRF visualization.")
        if result.get("fevd"):
            lines.append(f"Forecast-error variance decomposition: {result['fevd']}")
        if provenance:
            lines.extend(["", "Data provenance:"])
            lines.extend(f"  {name}: {value or 'Not provided'}" for name, value in provenance.items())
        return "\n".join(lines)

    def _show_extended_forecasts(self, result):
        if result["analysis_type"] == "exogenous":
            dates = result["forecast_index"]
            values = result["forecast_values"]
            lower = result["forecast_lower"]
            upper = result["forecast_upper"]
            self.forecast_table.setRowCount(len(values))
            for row, fields in enumerate(zip(dates, values, lower, upper)):
                for column, value in enumerate(fields):
                    self.forecast_table.setItem(
                        row,
                        column,
                        QTableWidgetItem(str(value) if column == 0 else f"{value:.3f}"),
                    )
            holdout = result["holdout"]
            self.holdout_table.setRowCount(len(holdout["periods"]))
            for row, fields in enumerate(
                zip(holdout["periods"], holdout["actual"], holdout["predicted"])
            ):
                for column, value in enumerate(fields):
                    self.holdout_table.setItem(
                        row, column,
                        QTableWidgetItem(str(value) if column == 0 else f"{value:.3f}"),
                    )
            return
        forecast = result["forecast"]
        rows = [
            (period, name, value, lower, upper)
            for name, values in forecast["values"].items()
            for index, (period, value) in enumerate(zip(forecast["periods"], values))
            for lower, upper in [
                (
                    forecast["lower"][name][index]
                    if forecast.get("lower") is not None
                    else None,
                    forecast["upper"][name][index]
                    if forecast.get("upper") is not None
                    else None,
                )
            ]
        ]
        self.forecast_table.setRowCount(len(rows))
        for row, (period, name, value, lower, upper) in enumerate(rows):
            self.forecast_table.setItem(row, 0, QTableWidgetItem(f"{period} | {name}"))
            self.forecast_table.setItem(row, 1, QTableWidgetItem(f"{value:.3f}"))
            self.forecast_table.setItem(
                row, 2, QTableWidgetItem(f"{lower:.3f}" if lower is not None else "Unavailable")
            )
            self.forecast_table.setItem(
                row, 3, QTableWidgetItem(f"{upper:.3f}" if upper is not None else "Unavailable")
            )
        holdout = result["holdout"]
        rows = [
            (period, name, actual, predicted)
            for name, actual_values in holdout["actual"].items()
            for period, actual, predicted in zip(
                holdout["periods"], actual_values, holdout["predicted"][name]
            )
        ]
        self.holdout_table.setRowCount(len(rows))
        for row, fields in enumerate(rows):
            for column, value in enumerate(fields):
                self.holdout_table.setItem(
                    row, column,
                    QTableWidgetItem(str(value) if column == 0 else f"{value:.3f}"),
                )

    def _show_extended_chart(self, frame, result):
        import matplotlib.pyplot as plt
        from matplotlib.ticker import PercentFormatter
        from app.statistics.time_series_charts import _finish, _unit_for

        for canvas in self.chart_canvases.values():
            index = self.tabs.indexOf(canvas)
            if index >= 0:
                self.tabs.removeTab(index)
            canvas.deleteLater()
        figures = {}
        if result["analysis_type"] == "exogenous":
            forecast_fig, axes = plt.subplots(2, 1, figsize=(10, 7.2), dpi=120)
            date_column = result["date_column"]
            dependent = result["dependent_variable"]
            variable = dependent.replace("_", " ")
            unit = _unit_for(variable)
            dates = parse_time_values(frame[date_column])
            axes[0].plot(dates, pd.to_numeric(frame[dependent]), color="#2457A7", linewidth=1.9, label="Observed series")
            holdout = result["holdout"]
            axes[0].plot(
                pd.to_datetime(holdout["periods"]),
                holdout["predicted"],
                color="#B8423C", linestyle="--", marker="x", linewidth=1.6,
                label="Chronological holdout prediction",
            )
            axes[0].set_title(f"{variable}: Observed Series and Holdout Predictions")
            axes[0].set_xlabel("Year")
            axes[0].set_ylabel(f"{variable} ({unit})")
            axes[0].legend(loc="best", frameon=False)
            if result["forecast_values"]:
                future_dates = pd.to_datetime(result["forecast_index"])
                axes[1].plot(future_dates, result["forecast_values"], color="#32845B", marker="o", linestyle="--", linewidth=1.9, label="Forecast")
                forecast_intervals = result.get("forecast_intervals", {})
                if "95%" in forecast_intervals:
                    axes[1].fill_between(future_dates, forecast_intervals["95%"]["lower"], forecast_intervals["95%"]["upper"], color="#32845B", alpha=0.11, label="95% prediction interval")
                if "80%" in forecast_intervals:
                    axes[1].fill_between(future_dates, forecast_intervals["80%"]["lower"], forecast_intervals["80%"]["upper"], color="#32845B", alpha=0.24, label="80% prediction interval")
                if not forecast_intervals:
                    interval_level = float(result.get("prediction_interval", {}).get("confidence_level", 0.95))
                    axes[1].fill_between(future_dates, result["forecast_lower"], result["forecast_upper"], color="#32845B", alpha=0.17, label=f"{interval_level:.0%} prediction interval")
                axes[1].axvline(future_dates[0], color="#687386", linestyle=":", linewidth=1.2, label="Forecast begins")
                axes[1].legend(loc="best", frameon=False)
            else:
                axes[1].text(0.5, 0.5, result["forecast_limitation"] or "No forecast", ha="center", va="center", transform=axes[1].transAxes)
            axes[1].set_title(
                f"{variable}: Future Forecast" + (
                    f" ({result['future_predictor_source']})" if result["future_predictor_source"] else ""
                )
            )
            axes[1].set_xlabel("Year")
            axes[1].set_ylabel(f"{variable} ({unit})")
            _finish(forecast_fig, list(axes), list(axes))
            figures["Forecasts"] = forecast_fig
        else:
            variables = result["endogenous_variables"]
            response_values = np.asarray(result["impulse_responses"]["values"], dtype=float)
            periods = result["impulse_responses"]["periods"]
            figure, axes = plt.subplots(
                len(variables), len(variables),
                figsize=(max(8, 3 * len(variables)), max(5, 2.5 * len(variables))),
                squeeze=False,
            )
            for response_index, response in enumerate(variables):
                for shock_index, shock in enumerate(variables):
                    axes[response_index, shock_index].plot(
                        periods, response_values[:, response_index, shock_index],
                        color="#2457A7", linewidth=1.8,
                    )
                    axes[response_index, shock_index].axhline(0, color="#687386", linewidth=0.8)
                    axes[response_index, shock_index].set_title(
                        f"{response.replace('_', ' ')} response to {shock.replace('_', ' ')} shock",
                        fontsize=10,
                    )
                    axes[response_index, shock_index].set_xlabel("Horizon (years)")
                    axes[response_index, shock_index].set_ylabel(
                        f"Response ({_unit_for(response.replace('_', ' '))})"
                    )
            _finish(figure, list(axes.flat))
            figures["Impulse responses"] = figure
            if isinstance(result["fevd"], dict) and "values" in result["fevd"]:
                fevd = np.asarray(result["fevd"]["values"], dtype=float)
                fevd_fig, fevd_axes = plt.subplots(
                    1, len(variables),
                    figsize=(max(7, 4 * len(variables)), 4),
                    squeeze=False,
                )
                for index, name in enumerate(variables):
                    fevd_axes[0, index].stackplot(
                        result["fevd"]["periods"],
                        fevd[:, index, :].T,
                        labels=variables,
                    )
                    fevd_axes[0, index].set_title(f"{name.replace('_', ' ')}: Forecast Error Variance Shares", fontsize=10)
                    fevd_axes[0, index].set_xlabel("Horizon (years)")
                    fevd_axes[0, index].set_ylabel("Variance share (%)")
                    fevd_axes[0, index].yaxis.set_major_formatter(PercentFormatter(xmax=1.0))
                    fevd_axes[0, index].legend(fontsize=8, loc="best", frameon=False, title="Shock")
                _finish(fevd_fig, list(fevd_axes.flat))
                figures["FEVD"] = fevd_fig
        self.last_figures = figures
        self.last_figure = next(iter(figures.values()))
        self.chart_canvases = {}
        for name, figure in figures.items():
            canvas = FigureCanvasQTAgg(figure)
            self.chart_canvases[name] = canvas
            tab_name = "Model comparison chart" if name == "Model comparison" else name
            self.tabs.addTab(canvas, tab_name)
        self.chart_canvas = self.last_figure

    @staticmethod
    def _format_result(result, provenance=None):
        if result.get("model_name") == "Johansen cointegration":
            return TimeSeriesWindow._format_extended_result(result, provenance)
        if (
            result.get("analysis_type") in {"exogenous", "multivariate"}
            and result.get("model_name") != "Johansen cointegration"
        ):
            return TimeSeriesWindow._format_extended_result(result, provenance)

        def display_number(value):
            return f"{value:.3f}" if isinstance(value, (int, float)) else str(value)

        def display_metric(value):
            return f"{value:.3f}" if value is not None else "not defined"

        lines = [result["summary"], "", "Descriptive statistics:"]
        lines.extend(
            f"  {name.replace('_', ' ').title()}: {display_number(value)}"
            if value is not None and pd.notna(value)
            else f"  {name.replace('_', ' ').title()}: unavailable"
            for name, value in result["descriptive_statistics"].items()
        )
        lines.extend(
            [
                "",
                f"Stationarity results ({result['stationarity_scope']} stationarity; "
                f"alpha={result['significance_level']:.3f}):",
            ]
        )
        for level, tests in result["stationarity_assessment"].items():
            lines.append(f"  {level.replace('_', ' ').title()}:")
            for name, test in tests.items():
                if "error" in test:
                    lines.append(f"    {name}: unavailable ({test['error']})")
                else:
                    critical_values = ", ".join(
                        f"{key}={value:.3f}" for key, value in test["critical_values"].items()
                    )
                    adf_details = (
                        f" Lag selection={test['autolag']}; lags used={test['used_lags']}; "
                        f"effective observations={test['observations']}."
                        if name == "ADF" and "used_lags" in test
                        else ""
                    )
                    lines.append(
                        f"    {name}: statistic={test['statistic']:.3f}, "
                        f"{stationarity_p_value_display(test)}; {test['conclusion']} "
                        f"Critical values: {critical_values}.{adf_details}"
                    )
            lines.append(
                f"    Combined interpretation: {result['stationarity_interpretations'][level]}"
            )
        lines.extend(["", "Academic interpretations:"])
        lines.extend(
            f"  {name.replace('_', ' ').title()}: {interpretation}"
            for name, interpretation in result["academic_interpretations"].items()
        )
        design = result["model_evaluation_design"]
        lines.extend(
            [
                "",
                "Forecast workflow:",
                f"  Training observations: {design['training_observations']}"
                + (f" through {design['training_end']}" if design["training_end"] else ""),
                f"  Holdout observations: {design['holdout_observations']}"
                + (f" starting {design['holdout_start']}" if design["holdout_start"] else ""),
                f"  Final model estimation observations: {design['final_estimation_observations']}",
                f"  Final model refit on the full series: {design['final_model_refit_on_full_series']}",
            ]
        )
        if result["model_comparison"]:
            lines.extend(["", "Chronological model comparison (not selected by AIC/BIC alone):"])
            lines.extend(
                f"  {name}: MSE={metrics['MSE']:.3f}, RMSE={metrics['RMSE']:.3f}, "
                f"MAE={metrics['MAE']:.3f}, "
                f"MAPE={metrics['MAPE']:.3f}%, "
                f"AIC={display_metric(metrics['AIC'])}, BIC={display_metric(metrics['BIC'])}"
                if metrics["MAPE"] is not None
                else f"  {name}: MSE={metrics['MSE']:.3f}, RMSE={metrics['RMSE']:.3f}, "
                f"MAE={metrics['MAE']:.3f}, "
                f"MAPE unavailable (zero actual values), AIC={display_metric(metrics['AIC'])}, "
                f"BIC={display_metric(metrics['BIC'])}"
                for name, metrics in result["model_comparison"].items()
            )
        if result["aic"] is not None and result["bic"] is not None:
            lines.extend(
                [
                    "",
                    f"Fitted model {result['model_specification']}: "
                    f"AIC={result['aic']:.3f}, "
                    f"BIC={result['bic']:.3f}; these are not used alone to select a forecast model.",
                ]
            )
        if result["diagnostics"]:
            lines.extend(["", "Residual diagnostics:", *[
                f"  {key}: {value:.3f}" if value is not None else f"  {key}: unavailable"
                for key, value in result["diagnostics"].items()
            ]])
        lines.append(f"  Model convergence: {result['convergence_status']}")
        if result["diagnostic_warnings"]:
            lines.extend(
                ["  Diagnostic warnings:", *[f"    - {warning}" for warning in result["diagnostic_warnings"]]]
            )
        lines.extend(
            [
                "",
                f"Prediction intervals: {result['prediction_interval']['method']} "
                f"({result['prediction_interval']['confidence_level']:.3f} confidence). "
                f"{result['prediction_interval']['assumptions']}",
            ]
        )
        if result["seasonal_components"]:
            lines.extend(
                [
                    "",
                    "Seasonal decomposition (month/quarter: seasonal component):",
                    *[
                        f"  {period}: {value:.3f}" if value is not None else f"  {period}: unavailable"
                        for period, value in result["seasonal_components"].items()
                    ],
                ]
            )
        if result["correlogram"]["acf"]:
            lines.extend(
                [
                    "",
                    "ACF / PACF (lags 0-10):",
                    f"  ACF: {[round(value, 3) if value is not None else None for value in result['correlogram']['acf'][:11]]}",
                    f"  PACF: {[round(value, 3) if value is not None else None for value in result['correlogram']['pacf'][:11]]}",
                ]
            )
        recommendations = result.get("recommendations", {})
        for category in ("recommended", "conditional", "unsuitable"):
            items = recommendations.get(category, [])
            if items:
                lines.append(
                    f"{category.title()} methods: "
                    + "; ".join(
                        f"{item['method']} - {item['reason']}" for item in items
                    )
                )
        if provenance:
            lines.extend(["", "Data provenance:"])
            for field, label in (
                ("data_source", "Data source"),
                ("indicator_name", "Indicator"),
                ("methodology", "Measurement methodology"),
                ("source_url", "Source URL"),
                ("units", "Units"),
                ("downloaded_date", "Date downloaded"),
            ):
                lines.append(f"  {label}: {provenance.get(field) or 'Not provided'}")
        lines.append(
            "Method note: candidates are fit using training observations only and evaluated on the "
            "chronological holdout; the final selected model is refit on the full series before future "
            "forecasts. ADF/Phillips-Perron and KPSS have different null hypotheses."
        )
        return "\n".join(lines)

    def _show_chart(self, frame, result):
        try:
            figures = create_time_series_charts(frame, result)
        except (ValueError, TypeError) as error:
            QMessageBox.warning(self, "Chart unavailable", str(error))
            return
        for canvas in self.chart_canvases.values():
            index = self.tabs.indexOf(canvas)
            if index >= 0:
                self.tabs.removeTab(index)
            canvas.deleteLater()
        self.last_figures = figures
        self.last_figure = figures["Forecasts"]
        self.chart_canvases = {}
        for name, figure in figures.items():
            canvas = FigureCanvasQTAgg(figure)
            self.chart_canvases[name] = canvas
            tab_name = "Model comparison chart" if name == "Model comparison" else name
            self.tabs.addTab(canvas, tab_name)
        self.chart_canvas = self.chart_canvases["Original series and trend"]

    def _show_forecast(self, result):
        self.forecast_table.setRowCount(len(result["forecast_values"]))
        for row, values in enumerate(
            zip(
                result["forecast_index"],
                result["forecast_values"],
                result["forecast_lower"],
                result["forecast_upper"],
            )
        ):
            for column, value in enumerate(values):
                text = str(value) if column == 0 else f"{value:.3f}"
                self.forecast_table.setItem(row, column, QTableWidgetItem(text))
        holdout = result["holdout"]
        self.holdout_table.setRowCount(len(holdout["periods"]))
        for row, values in enumerate(
            zip(holdout["periods"], holdout["actual"], holdout["predicted"])
        ):
            for column, value in enumerate(values):
                text = str(value) if column == 0 else f"{value:.3f}"
                self.holdout_table.setItem(row, column, QTableWidgetItem(text))

    def _show_model_comparison(self, result):
        comparison = result["model_comparison"]
        self.model_comparison_table.setRowCount(len(comparison))
        for row, (name, metrics) in enumerate(comparison.items()):
            values = (
                name,
                metrics["MSE"],
                metrics["RMSE"],
                metrics["MAE"],
                metrics["MAPE"],
                metrics.get("AIC"),
                metrics.get("BIC"),
            )
            for column, value in enumerate(values):
                text = str(value) if column == 0 else (
                    f"{value:.3f}" if value is not None else "Unavailable"
                )
                self.model_comparison_table.setItem(
                    row, column, QTableWidgetItem(text)
                )

    def _create_transformed_copy(self):
        if self.preview_table.columnCount() == 0:
            QMessageBox.warning(self, "No data", "Load data before creating a transformation.")
            return
        try:
            transformed = transform_time_series(
                self._working_frame_from_table(),
                self.date_combo.currentText(),
                self.value_combo.currentText(),
                self.transform_combo.currentData(),
            )
        except (ValueError, TypeError) as error:
            QMessageBox.warning(self, "Transformation unavailable", str(error))
            return
        frame = self._working_frame_from_table()
        date_column = self.date_combo.currentText()
        transformed_column = transformed.columns[1]
        transformed_keys = parse_time_values(transformed[date_column])
        values_by_date = pd.Series(
            transformed[transformed_column].to_numpy(),
            index=transformed_keys,
        )
        frame[transformed_column] = parse_time_values(frame[date_column]).map(values_by_date)
        self.dataframe = frame.copy()
        self._set_dataframe(frame, self.source_dataset_id)
        self.quality_label.setText(
            f"Created {transformed_column} as a new variable. The original observation column remains unchanged; save as a revision to retain it in the project."
        )
        if self.project_combo.currentData() is not None:
            self._save_working_revision()

    def _export_csv(self):
        frame = self._working_frame_from_table()
        if frame.empty:
            QMessageBox.warning(self, "No data", "There is no working dataset to export.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export working data", "time_series_working.csv", "CSV files (*.csv)")
        if path:
            frame.to_csv(path, index=False)

    def _export_chart(self):
        if self.last_result is None:
            QMessageBox.warning(self, "No charts", "Run an analysis before exporting charts.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export editable charts", "time_series_editable_charts.xlsx", "Excel files (*.xlsx)"
        )
        if path:
            try:
                frame = self._working_frame_from_table()
                frame.to_excel(path, index=False, sheet_name="Data")
                specs = time_series_chart_specs(self.last_result)
                append_editable_charts_xlsx(path, specs)
            except (ValueError, OSError, KeyError) as error:
                QMessageBox.warning(self, "Chart export failed", str(error))

    def _export_excel(self):
        if self.last_result is None:
            QMessageBox.warning(self, "No results", "Run an analysis before exporting results.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export time-series workbook", "time_series_results.xlsx", "Excel files (*.xlsx)"
        )
        if not path:
            return
        result = self.last_result
        if (
            result.get("analysis_type") in {"exogenous", "multivariate"}
            and result.get("model_name") != "Johansen cointegration"
        ):
            with pd.ExcelWriter(path) as writer:
                self._working_frame_from_table().to_excel(writer, sheet_name="Data", index=False)
                pd.DataFrame(
                    [{"Result": name, "Value": str(value)} for name, value in result.items()],
                ).to_excel(writer, sheet_name="Analysis results", index=False)
                pd.DataFrame(
                    [
                        {"Variable": name, **metrics}
                        for name, metrics in result.get("evaluation", {}).items()
                        if isinstance(metrics, dict)
                    ]
                ).to_excel(writer, sheet_name="Forecast accuracy", index=False)
                pd.DataFrame(
                    list(result.get("diagnostics", {}).items()),
                    columns=["Diagnostic", "Value"],
                ).to_excel(writer, sheet_name="Diagnostics", index=False)
                pd.DataFrame(
                    result.get("preprocessing_operations", [])
                ).to_excel(writer, sheet_name="Preprocessing audit", index=False)
            append_editable_charts_xlsx(path, time_series_chart_specs(result))
            return
        if result.get("model_name") == "Johansen cointegration":
            with pd.ExcelWriter(path) as writer:
                pd.DataFrame(
                    [{"Result": name, "Value": str(value)} for name, value in result.items()],
                ).to_excel(writer, sheet_name="Johansen test", index=False)
                pd.DataFrame(
                    result.get("integration_profiles", {})
                ).T.to_excel(writer, sheet_name="Integration screening")
            return
        forecast = pd.DataFrame(
            {
                "Period": result["forecast_index"],
                "Forecast": result["forecast_values"],
                "Lower 95%": result["forecast_lower"],
                "Upper 95%": result["forecast_upper"],
            }
        )
        statistics = pd.DataFrame(
            list(result["descriptive_statistics"].items()),
            columns=["Statistic", "Value"],
        )
        tests = pd.DataFrame(
            [
                {
                    "Test": name,
                    "Statistic": item["statistic"],
                    "P-value": item["p_value"],
                    "P-value display": stationarity_p_value_display(item),
                    "Lag selection": item.get("autolag"),
                    "Lags used": item.get("used_lags"),
                    "Effective observations": item.get("observations"),
                    "Null": item["null"],
                    "Alternative": item["alternative"],
                    "Critical values": str(item["critical_values"]),
                }
                for name, item in result["stationarity_tests"].items()
            ]
        )
        holdout = pd.DataFrame(
            {
                "Period": result["holdout"]["periods"],
                "Actual": result["holdout"]["actual"],
                "Predicted": result["holdout"]["predicted"],
            }
        )
        diagnostics = pd.DataFrame(
            list(result["diagnostics"].items()),
            columns=["Diagnostic", "Value"],
        )
        comparisons = pd.DataFrame(
            [
                {"Model": name, **metrics}
                for name, metrics in result["model_comparison"].items()
            ]
        )
        stationarity = pd.DataFrame(
            [
                {
                    "Series": level.replace("_", " "),
                    "Test": name,
                    "Statistic": test.get("statistic"),
                    "P-value": test.get("p_value"),
                    "P-value display": stationarity_p_value_display(test)
                    if "p_value" in test
                    else "Unavailable",
                    "Lag selection": test.get("autolag"),
                    "Lags used": test.get("used_lags"),
                    "Effective observations": test.get("observations"),
                    "Conclusion": test.get("conclusion", test.get("error", "")),
                }
                for level, tests in result["stationarity_assessment"].items()
                for name, test in tests.items()
            ]
        )
        provenance = pd.DataFrame(
            list(self.last_provenance.items()),
            columns=["Field", "Value"],
        )
        with pd.ExcelWriter(path) as writer:
            self._working_frame_from_table().to_excel(writer, sheet_name="Data", index=False)
            statistics.to_excel(writer, sheet_name="Descriptive statistics", index=False)
            tests.to_excel(writer, sheet_name="Stationarity tests", index=False)
            stationarity.to_excel(writer, sheet_name="Transformed stationarity", index=False)
            forecast.to_excel(writer, sheet_name="Forecast", index=False)
            holdout.to_excel(writer, sheet_name="Holdout comparison", index=False)
            diagnostics.to_excel(writer, sheet_name="Residual diagnostics", index=False)
            comparisons.to_excel(writer, sheet_name="Model comparison", index=False)
            provenance.to_excel(writer, sheet_name="Data provenance", index=False)
            for worksheet in writer.sheets.values():
                for row in worksheet.iter_rows():
                    for cell in row:
                        if isinstance(cell.value, (int, float)):
                            cell.number_format = "0.000"
        append_editable_charts_xlsx(path, time_series_chart_specs(result))

    def _export_pdf(self):
        if self.last_result is None:
            QMessageBox.warning(self, "No results", "Run an analysis before exporting a PDF.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export time-series report", "time_series_report.pdf", "PDF files (*.pdf)"
        )
        if not path:
            return
        result = self.last_result
        rows = "".join(
            f"<tr><td>{escape(name)}</td><td>{item['statistic']:.3f}</td>"
            f"<td>{escape(str(item.get('autolag') or '—'))}</td>"
            f"<td>{escape(str(item.get('used_lags') if item.get('used_lags') is not None else '—'))}</td>"
            f"<td>{escape(str(item.get('observations') if item.get('observations') is not None else '—'))}</td>"
            f"<td>{stationarity_p_value_display(item)}</td>"
            f"<td>{escape(item['conclusion'])}</td></tr>"
            for name, item in result.get("stationarity_tests", {}).items()
            if "p_value" in item
        )
        html = (
                "<h1>Time-Series Analysis Report</h1>"
                f"<p>{escape(str(result.get('value_column', result.get('dependent_variable', result.get('endogenous_variables')))))}; "
                f"{escape(str(result.get('start_date', result.get('rows'))))} to "
                f"{escape(str(result.get('end_date', result.get('frequency'))))}; "
                f"{escape(str(result.get('frequency_label', result.get('frequency'))))}</p>"
                f"<pre>{escape(self._format_result(result))}</pre>"
                "<h2>Unit-root and stationarity tests</h2>"
                "<table border='1' cellspacing='0' cellpadding='4'><tr><th>Test</th>"
                f"<th>Statistic</th><th>Lag selection</th><th>Lags used</th>"
                f"<th>Effective observations</th><th>p-value</th>"
                f"<th>Conclusion</th></tr>{rows}</table>"
                "<p>Charts are omitted from this fixed-layout PDF. Export to Word or Excel to edit chart data.</p>"
            )
        document = QTextDocument()
        document.setHtml(html)
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
        printer.setOutputFileName(path)
        document.print_(printer)

    def _export_report(self):
        if self.last_result is None:
            QMessageBox.warning(self, "No results", "Run an analysis before exporting a report.")
            return
        from docx import Document
        path, _ = QFileDialog.getSaveFileName(self, "Export time-series report", "time_series_report.docx", "Word files (*.docx)")
        if not path:
            return
        document = Document()
        document.add_heading("Time-Series Analysis Report", level=1)
        document.add_paragraph(self._format_result(self.last_result))

        def add_native_charts():
            for index, chart_spec in enumerate(
                time_series_chart_specs(self.last_result), start=1
            ):
                if index > 1:
                    document.add_page_break()
                document.add_heading(chart_spec["title"], level=2)
                add_editable_chart(
                    document,
                    document.add_paragraph(),
                    chart_spec["title"],
                    chart_spec["categories"],
                    chart_spec["series"],
                    chart_type=chart_spec.get("chart_type", "line"),
                    x_axis_title=chart_spec["x_axis_title"],
                    y_axis_title=chart_spec["y_axis_title"],
                    width=6.4,
                )
                caption = document.add_paragraph(
                    f"Figure {index}. Editable Microsoft Office chart; use Chart Design > Edit Data to modify its embedded workbook."
                )
                caption.style = "Caption"
        if (
            self.last_result.get("analysis_type") == "multivariate"
            and self.last_result.get("model_name") == "Johansen cointegration"
        ):
            result = self.last_result
            document.add_heading("Johansen cointegration rank test", level=2)
            document.add_paragraph(str(result))
            document.save(path)
            return
        if self.last_result.get("analysis_type") in {"exogenous", "multivariate"}:
            result = self.last_result
            document.add_heading("Model and evaluation details", level=2)
            for key in (
                "model_specification", "evaluation", "model_evaluation_design",
                "diagnostics", "parameter_inference", "cointegration",
                "granger_causality", "stability", "future_predictor_source",
                "forecast_limitation", "forecast_interval_assumption",
                "future_predictor_values", "preprocessing_operations",
            ):
                if key in result:
                    document.add_paragraph(f"{key.replace('_', ' ').title()}: {result[key]}")
            forecast_data = (
                result.get("scenario_forecasts")
                if result.get("analysis_type") == "exogenous"
                else {"Forecast": result.get("forecast", {})}
            )
            if forecast_data:
                document.add_heading("Forecasts", level=2)
                for scenario, forecast in forecast_data.items():
                    if not isinstance(forecast, dict):
                        continue
                    document.add_paragraph(f"Scenario: {scenario}")
                    if "forecast_values" in forecast:
                        for date, value in zip(
                            forecast["forecast_index"], forecast["forecast_values"]
                        ):
                            document.add_paragraph(f"{date}: {value:.3f}")
                    elif "values" in forecast:
                        for variable, values in forecast["values"].items():
                            document.add_paragraph(
                                f"{variable}: " + ", ".join(f"{value:.3f}" for value in values)
                            )
            add_native_charts()
            document.save(path)
            return
        document.add_heading("Descriptive statistics", level=2)
        descriptive_table = document.add_table(rows=1, cols=2)
        descriptive_table.rows[0].cells[0].text = "Statistic"
        descriptive_table.rows[0].cells[1].text = "Value"
        for key, value in self.last_result["descriptive_statistics"].items():
            cells = descriptive_table.add_row().cells
            cells[0].text = key.replace("_", " ").title()
            cells[1].text = f"{value:.3f}" if isinstance(value, (int, float)) else str(value)
        document.add_heading("Forecast", level=2)
        forecast_table = document.add_table(rows=1, cols=4)
        for cell, label in zip(
            forecast_table.rows[0].cells,
            ("Period", "Forecast", "Lower interval", "Upper interval"),
        ):
            cell.text = label
        for values in zip(
            self.last_result["forecast_index"],
            self.last_result["forecast_values"],
            self.last_result["forecast_lower"],
            self.last_result["forecast_upper"],
        ):
            for cell, value in zip(forecast_table.add_row().cells, values):
                cell.text = str(value) if isinstance(value, str) else f"{value:.3f}"
        if self.last_result["holdout"]["periods"]:
            document.add_heading("Chronological holdout comparison", level=2)
            holdout_table = document.add_table(rows=1, cols=3)
            for cell, label in zip(
                holdout_table.rows[0].cells,
                ("Period", "Actual", "Predicted"),
            ):
                cell.text = label
            for values in zip(
                self.last_result["holdout"]["periods"],
                self.last_result["holdout"]["actual"],
                self.last_result["holdout"]["predicted"],
            ):
                for cell, value in zip(holdout_table.add_row().cells, values):
                    cell.text = str(value) if isinstance(value, str) else f"{value:.3f}"
        add_native_charts()
        document.save(path)
