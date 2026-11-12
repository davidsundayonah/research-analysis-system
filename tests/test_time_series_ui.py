import os
from io import BytesIO
from zipfile import ZipFile
from xml.etree import ElementTree as ET

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pandas as pd
import pytest
from openpyxl import load_workbook
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtWidgets import QFileDialog

from pypdf import PdfReader
from docx import Document

from app.database.database import Database
from app.ui.main_window import MainWindow
from app.word_charts import time_series_chart_specs


@pytest.fixture(scope="session")
def qt_app():
    return QApplication.instance() or QApplication([])


def test_time_series_back_navigation_and_main_app_return(qt_app, tmp_path):
    database = Database(tmp_path / "time-series-navigation.db")
    database.create_project("Navigation study")
    main_window = MainWindow(database)
    main_window.show()
    main_window.open_time_series_window()
    window = main_window.time_series_window
    qt_app.processEvents()

    assert window.back_button.isVisible()
    assert window.main_app_button.isVisible()
    assert not window.back_button.isEnabled()

    window.tabs.setCurrentWidget(window.forecast_table)
    window.tabs.setCurrentWidget(window.results)
    window.back_button.click()
    assert window.tabs.currentWidget() is window.forecast_table
    window.back_button.click()
    assert window.tabs.currentWidget() is window.preview_table
    assert not window.back_button.isEnabled()

    window.tabs.setCurrentWidget(window.model_comparison_table)
    window._set_dataframe(
        pd.DataFrame(
            {
                "Date": pd.date_range("2020-01-01", periods=12, freq="MS"),
                "Value": np.arange(12, dtype=float),
            }
        )
    )
    assert window.tabs.currentWidget() is window.preview_table
    assert window.results.toPlainText() == ""
    assert window.forecast_table.rowCount() == 0
    assert window.model_comparison_table.rowCount() == 0
    assert not window.back_button.isEnabled()

    window.main_app_button.click()
    qt_app.processEvents()
    assert not window.isVisible()
    assert main_window.isVisible()

    main_window.close()
    database.close()


def test_time_series_navigation_opens_independent_window_and_runs_analysis(
    qt_app, tmp_path, monkeypatch
):
    database = Database(tmp_path / "time-series-ui.db")
    database.create_project("Time series study")
    main_window = MainWindow(database)
    main_window.navigation.setCurrentRow(main_window.time_series_nav_index)
    qt_app.processEvents()

    assert main_window.time_series_window.isVisible()
    assert main_window.navigation.currentRow() != main_window.time_series_nav_index

    dates = pd.date_range("2020-01-01", periods=36, freq="MS")
    frame = pd.DataFrame(
        {"Date": dates, "Indicator": 20 + np.arange(36) + np.sin(np.arange(36))}
    )
    main_window.time_series_window._set_dataframe(frame)
    main_window.time_series_window.provenance_inputs["data_source"].setText(
        "Synthetic regression fixture"
    )
    main_window.time_series_window.test_size_spin.setValue(5)
    main_window.time_series_window.run_analysis()
    qt_app.processEvents()

    assert main_window.time_series_window.tabs.currentWidget() is (
        main_window.time_series_window.results
    )
    main_window.time_series_window.back_button.click()
    assert main_window.time_series_window.tabs.currentWidget() is (
        main_window.time_series_window.preview_table
    )

    assert "ADF" in main_window.time_series_window.results.toPlainText()
    assert main_window.time_series_window.forecast_table.rowCount() == 6
    assert main_window.time_series_window.holdout_table.rowCount() == 5
    assert main_window.time_series_window.model_comparison_table.rowCount() >= 6
    assert main_window.time_series_window.last_figure is not None
    assert len(main_window.time_series_window.last_figures) == 7
    saved_results = database.get_project_time_series_analyses(
        main_window.time_series_window.project_combo.currentData()
    )
    assert saved_results[-1]["data_source"] == "Synthetic regression fixture"
    assert "first_difference" in saved_results[-1]["result"]["academic_interpretations"]
    assert saved_results[-1]["result"]["model_evaluation_design"]["final_model_refit_on_full_series"]

    paths = iter(
        tmp_path / name
        for name in (
            "working.csv",
            "chart.png",
            "results.xlsx",
            "report.pdf",
            "report.docx",
        )
    )
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        lambda *_args, **_kwargs: (str(next(paths)), ""),
    )
    window = main_window.time_series_window
    window._export_csv()
    window.tabs.setCurrentWidget(window.chart_canvases["Rolling statistics"])
    window._export_chart()
    window._export_excel()
    window._export_pdf()
    window._export_report()
    workbook = load_workbook(tmp_path / "results.xlsx", read_only=True)
    assert "Holdout comparison" in workbook.sheetnames
    assert workbook["Holdout comparison"].max_row == 6
    assert "Data provenance" in workbook.sheetnames
    assert workbook["Forecast"]["B2"].number_format == "0.000"
    workbook.close()
    with ZipFile(tmp_path / "report.docx") as archive:
        names = archive.namelist()
        chart_parts = [
            name for name in names if name.startswith("word/charts/chart") and name.endswith(".xml")
        ]
        workbook_parts = [
            name for name in names if name.startswith("word/embeddings/") and name.endswith(".xlsx")
        ]
        assert len(chart_parts) == len(time_series_chart_specs(window.last_result))
        assert len(workbook_parts) == len(chart_parts)
        assert len([name for name in names if name.startswith("word/media/")]) == 1
        chart_namespace = {"c": "http://schemas.openxmlformats.org/drawingml/2006/chart"}
        relationship_namespace = {
            "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
            "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
        }
        for chart_part in chart_parts:
            root = ET.fromstring(archive.read(chart_part))
            series = root.find(".//c:ser", chart_namespace)
            assert series is not None
            assert series.find("c:tx/c:strRef/c:f", chart_namespace) is not None
            assert series.find("c:cat/c:strRef/c:f", chart_namespace) is not None
            assert series.find("c:val/c:numRef/c:f", chart_namespace) is not None
            external_data = root.find("c:externalData", chart_namespace)
            assert external_data is not None
            relationship_id = external_data.attrib[
                "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
            ]
            relationships_part = (
                chart_part.replace(
                    "word/charts/", "word/charts/_rels/", 1
                )
                + ".rels"
            )
            relationships = ET.fromstring(archive.read(relationships_part))
            workbook_relationship = next(
                relationship
                for relationship in relationships.findall(
                    "rel:Relationship", relationship_namespace
                )
                if relationship.attrib["Id"] == relationship_id
            )
            assert workbook_relationship.attrib["Type"].endswith("/package")
            assert workbook_relationship.attrib["Target"].startswith("../embeddings/")
        embedded_workbook = load_workbook(
            BytesIO(archive.read(workbook_parts[0])), read_only=True
        )
        assert embedded_workbook.active["A1"].value == "Period"
        assert embedded_workbook.active["B1"].value
        embedded_workbook.close()
    Document(tmp_path / "report.docx")
    pdf = PdfReader(tmp_path / "report.pdf")
    assert sum(len(page.images) for page in pdf.pages) >= 6
    assert all(
        (tmp_path / name).is_file()
        for name in ("working.csv", "chart.png", "results.xlsx", "report.pdf", "report.docx")
    )

    main_window.close()
    qt_app.processEvents()
    database.close()


def test_time_series_ui_supports_manual_future_predictor_values(
    qt_app, tmp_path, monkeypatch
):
    database = Database(tmp_path / "time-series-exogenous.db")
    database.create_project("Exogenous time series")
    main_window = MainWindow(database)
    main_window.open_time_series_window()
    window = main_window.time_series_window
    rng = np.random.default_rng(42)
    count = 48
    dates = pd.date_range("2020-01-01", periods=count, freq="MS")
    predictor = np.zeros(count)
    outcome = np.zeros(count)
    for index in range(1, count):
        predictor[index] = 0.45 * predictor[index - 1] + rng.normal()
        outcome[index] = 0.5 * outcome[index - 1] + predictor[index] + rng.normal()
    frame = pd.DataFrame(
        {"Date": dates, "Outcome": outcome, "Predictor": predictor}
    )
    window._set_dataframe(frame)
    window.analysis_type_combo.setCurrentIndex(
        window.analysis_type_combo.findData("exogenous")
    )
    predictor_item = next(
        window.exogenous_list.item(index)
        for index in range(window.exogenous_list.count())
        if window.exogenous_list.item(index).text() == "Predictor"
    )
    predictor_item.setCheckState(Qt.CheckState.Checked)
    window.model_combo.setCurrentText("ARIMAX")
    window.horizon_spin.setValue(2)
    window.arima_order_spins[1].setValue(0)
    window.arima_order_spins[2].setValue(0)
    future_dates = pd.date_range("2024-01-01", periods=2, freq="MS")
    window.future_predictor_input.setPlainText(
        pd.DataFrame(
            {"Date": future_dates, "Predictor": [1.0, 2.0]}
        ).to_csv(index=False)
    )
    warning_messages = []
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda _parent, title, text: warning_messages.append((title, text)),
    )
    window.run_analysis()
    assert not warning_messages
    assert window.last_result["analysis_type"] == "exogenous"
    assert window.last_result["future_predictor_source"] == "researcher-supplied scenario values"
    assert len(window.last_result["forecast_values"]) == 2
    assert "ARIMAX" in window.results.toPlainText()
    saved = database.get_project_time_series_analyses(window.project_combo.currentData())
    assert saved[-1]["result"]["roles"]["exogenous_variables"] == ["Predictor"]

    exports = {
        "xlsx": tmp_path / "exogenous.xlsx",
        "pdf": tmp_path / "exogenous.pdf",
        "docx": tmp_path / "exogenous.docx",
    }

    def select_export(_parent, _title, _name, file_filter):
        extension = next(
            (extension for extension in exports if extension in file_filter.lower()),
            None,
        )
        return (str(exports[extension]), "") if extension else ("", "")

    monkeypatch.setattr(QFileDialog, "getSaveFileName", select_export)
    window._export_excel()
    window._export_pdf()
    window._export_report()
    assert all(path.is_file() for path in exports.values())
    assert load_workbook(exports["xlsx"]).sheetnames
    assert len(PdfReader(exports["pdf"]).pages) > 0
    assert Document(exports["docx"]).paragraphs
    main_window.close()
    database.close()


def test_sidebar_distributes_all_items_without_scrolling(qt_app, tmp_path):
    database = Database(tmp_path / "navigation-layout.db")
    window = MainWindow(database)
    window.resize(1300, 800)
    window.show()
    qt_app.processEvents()

    navigation = window.navigation
    last_item = navigation.visualItemRect(
        navigation.item(navigation.count() - 1)
    )
    assert navigation.item(10).text() == "Time-Series Analysis"
    assert navigation.item(navigation.count() - 1).text() == "Help"
    assert navigation.verticalScrollBar().maximum() == 0
    assert 0 <= last_item.top() <= last_item.bottom() < navigation.viewport().height()

    for index in range(8):
        navigation.addItem(f"Future menu item {index + 1}")
    qt_app.processEvents()

    def assert_items_fill_navigation():
        item_rects = [
            navigation.visualItemRect(navigation.item(index))
            for index in range(navigation.count())
        ]
        assert navigation.verticalScrollBar().maximum() == 0
        assert all(
            0 <= rect.top() <= rect.bottom() < navigation.viewport().height()
            for rect in item_rects
        )
        heights = [rect.height() for rect in item_rects]
        assert max(heights) - min(heights) <= 1

    assert_items_fill_navigation()
    window.resize(1300, 620)
    qt_app.processEvents()
    assert_items_fill_navigation()

    navigation.setCurrentRow(window.help_nav_index)
    qt_app.processEvents()
    assert window.pages.currentWidget() is window.help_page
    assert "A. Type paper questionnaires" in window.help_browser.toPlainText()
    assert "2.4 Time-series analysis" in window.help_browser.toPlainText()

    window.close()
    qt_app.processEvents()
    database.close()
