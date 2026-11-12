from __future__ import annotations

from io import BytesIO
from xml.sax.saxutils import escape
from typing import Sequence
from xml.etree import ElementTree as ET

import numpy as np
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls
from docx.opc.constants import CONTENT_TYPE, RELATIONSHIP_TYPE
from docx.opc.packuri import PackURI
from docx.opc.part import Part
from docx.shared import Inches
from openpyxl import Workbook
from openpyxl import load_workbook
from openpyxl.chart import BarChart, LineChart, ScatterChart, Reference, Series


_CHART_NS = "http://schemas.openxmlformats.org/drawingml/2006/chart"
_DRAWING_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_WP_NS = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
_PIC_NS = "http://schemas.openxmlformats.org/drawingml/2006/picture"
_NS = {"c": _CHART_NS, "a": _DRAWING_NS, "r": _REL_NS, "wp": _WP_NS}


def _element(parent, namespace: str, name: str, attributes=None):
    return ET.SubElement(
        parent,
        f"{{{namespace}}}{name}",
        {key: str(value) for key, value in (attributes or {}).items()},
    )


def _chart_title(chart, title: str) -> None:
    title_node = _element(chart, _CHART_NS, "title")
    text = _element(title_node, _CHART_NS, "tx")
    rich = _element(text, _CHART_NS, "rich")
    _element(rich, _DRAWING_NS, "bodyPr")
    _element(rich, _DRAWING_NS, "lstStyle")
    paragraph = _element(rich, _DRAWING_NS, "p")
    run = _element(paragraph, _DRAWING_NS, "r")
    properties = _element(run, _DRAWING_NS, "rPr", {"lang": "en-US"})
    _element(properties, _DRAWING_NS, "b")
    _element(run, _DRAWING_NS, "t").text = title
    _element(paragraph, _DRAWING_NS, "endParaRPr", {"lang": "en-US"})
    _element(title_node, _CHART_NS, "overlay", {"val": "0"})


def _write_cache(parent, namespace: str, values: Sequence, is_string: bool) -> None:
    cache_name = "strCache" if is_string else "numCache"
    cache = _element(parent, _CHART_NS, cache_name)
    if not is_string:
        _element(cache, _CHART_NS, "formatCode").text = "0.000"
    _element(cache, _CHART_NS, "ptCount", {"val": len(values)})
    for index, value in enumerate(values):
        if value is None:
            continue
        point = _element(cache, _CHART_NS, "pt", {"idx": index})
        _element(point, _CHART_NS, "v").text = str(value)


def _add_reference(parent, formula, values, is_string=False) -> None:
    reference = _element(
        parent, _CHART_NS, "strRef" if is_string else "numRef"
    )
    _element(reference, _CHART_NS, "f").text = formula
    _write_cache(reference, _CHART_NS, values, is_string)


def _axis_title(axis, title: str) -> None:
    title_node = _element(axis, _CHART_NS, "title")
    text = _element(title_node, _CHART_NS, "tx")
    rich = _element(text, _CHART_NS, "rich")
    _element(rich, _DRAWING_NS, "bodyPr")
    _element(rich, _DRAWING_NS, "lstStyle")
    paragraph = _element(rich, _DRAWING_NS, "p")
    run = _element(paragraph, _DRAWING_NS, "r")
    _element(run, _DRAWING_NS, "rPr", {"lang": "en-US"})
    _element(run, _DRAWING_NS, "t").text = title
    _element(paragraph, _DRAWING_NS, "endParaRPr", {"lang": "en-US"})
    _element(title_node, _CHART_NS, "overlay", {"val": "0"})


def _measurement_axis(name: str) -> str:
    """Use an explicit, conservative display label for measurement columns."""
    display = str(name).replace("_", " ").strip()
    normalized = display.casefold()
    if any(token in normalized for token in ("unemployment", "inflation", "growth", "policy rate", "interest rate")):
        return f"{display} (%)"
    if "wage index" in normalized or normalized.endswith("index"):
        return f"{display} (index points)"
    return display


def _build_chart_xml(
    title: str,
    categories: Sequence[str],
    series_data: Sequence[tuple[str, Sequence[float | None]]],
    chart_type: str,
    x_axis_title: str,
    y_axis_title: str,
    workbook_relationship_id: str,
) -> bytes:
    ET.register_namespace("c", _CHART_NS)
    ET.register_namespace("a", _DRAWING_NS)
    ET.register_namespace("r", _REL_NS)
    root = ET.Element(f"{{{_CHART_NS}}}chartSpace")
    _element(root, _CHART_NS, "date1904", {"val": "0"})
    _element(root, _CHART_NS, "lang", {"val": "en-US"})
    chart = _element(root, _CHART_NS, "chart")
    _chart_title(chart, title)
    _element(chart, _CHART_NS, "autoTitleDeleted", {"val": "0"})
    plot_area = _element(chart, _CHART_NS, "plotArea")
    _element(plot_area, _CHART_NS, "layout")
    plot_tag = "scatterChart" if chart_type == "scatter" else f"{chart_type}Chart"
    plot = _element(plot_area, _CHART_NS, plot_tag)
    if chart_type == "line":
        _element(plot, _CHART_NS, "grouping", {"val": "standard"})
        _element(plot, _CHART_NS, "varyColors", {"val": "0"})
    elif chart_type == "bar":
        _element(plot, _CHART_NS, "barDir", {"val": "col"})
        _element(plot, _CHART_NS, "grouping", {"val": "clustered"})
        _element(plot, _CHART_NS, "varyColors", {"val": "0"})
    elif chart_type == "scatter":
        _element(plot, _CHART_NS, "scatterStyle", {"val": "marker"})
        _element(plot, _CHART_NS, "varyColors", {"val": "0"})
    axis_ids = (125001, 125002)
    for index, (name, values) in enumerate(series_data):
        if len(values) != len(categories):
            raise ValueError(f"Chart series '{name}' does not match the category count.")
        series = _element(plot, _CHART_NS, "ser")
        _element(series, _CHART_NS, "idx", {"val": index})
        _element(series, _CHART_NS, "order", {"val": index})
        tx = _element(series, _CHART_NS, "tx")
        _add_reference(
            tx,
            f"'Sheet1'!${chr(66 + index)}$1",
            [name],
            True,
        )
        if chart_type == "line":
            _element(series, _CHART_NS, "marker", {"val": "none"})
        if chart_type == "scatter":
            _element(series, _CHART_NS, "marker", {"symbol": "circle", "size": "5"})
            x_values = _element(series, _CHART_NS, "xVal")
            _add_reference(x_values, f"'Sheet1'!$A$2:$A${len(categories) + 1}", categories)
            y_values = _element(series, _CHART_NS, "yVal")
            _add_reference(y_values, f"'Sheet1'!${chr(66 + index)}$2:${chr(66 + index)}${len(values) + 1}", values)
        else:
            category = _element(series, _CHART_NS, "cat")
            _add_reference(
                category,
                f"'Sheet1'!$A$2:$A${len(categories) + 1}",
                categories,
                True,
            )
            values_node = _element(series, _CHART_NS, "val")
            _add_reference(
                values_node,
                f"'Sheet1'!${chr(66 + index)}$2:${chr(66 + index)}${len(values) + 1}",
                values,
            )
    if chart_type == "line":
        _element(plot, _CHART_NS, "marker", {"val": "0"})
        _element(plot, _CHART_NS, "smooth", {"val": "0"})
    _element(plot, _CHART_NS, "axId", {"val": axis_ids[0]})
    _element(plot, _CHART_NS, "axId", {"val": axis_ids[1]})

    if chart_type == "scatter":
        x_axis = _element(plot_area, _CHART_NS, "valAx")
        _element(x_axis, _CHART_NS, "axId", {"val": axis_ids[0]})
        x_scale = _element(x_axis, _CHART_NS, "scaling")
        _element(x_scale, _CHART_NS, "orientation", {"val": "minMax"})
        _element(x_axis, _CHART_NS, "delete", {"val": "0"})
        _element(x_axis, _CHART_NS, "axPos", {"val": "b"})
        _axis_title(x_axis, x_axis_title)
        _element(x_axis, _CHART_NS, "numFmt", {"formatCode": "0.00", "sourceLinked": "0"})
        _element(x_axis, _CHART_NS, "majorTickMark", {"val": "out"})
        _element(x_axis, _CHART_NS, "minorTickMark", {"val": "none"})
        _element(x_axis, _CHART_NS, "tickLblPos", {"val": "nextTo"})
        _element(x_axis, _CHART_NS, "crossAx", {"val": axis_ids[1]})
        _element(x_axis, _CHART_NS, "crosses", {"val": "autoZero"})
        y_axis = _element(plot_area, _CHART_NS, "valAx")
        _element(y_axis, _CHART_NS, "axId", {"val": axis_ids[1]})
        y_scale = _element(y_axis, _CHART_NS, "scaling")
        _element(y_scale, _CHART_NS, "orientation", {"val": "minMax"})
        _element(y_axis, _CHART_NS, "delete", {"val": "0"})
        _element(y_axis, _CHART_NS, "axPos", {"val": "l"})
        _element(y_axis, _CHART_NS, "majorGridlines")
        _axis_title(y_axis, y_axis_title)
        _element(y_axis, _CHART_NS, "numFmt", {"formatCode": "0.00", "sourceLinked": "0"})
        _element(y_axis, _CHART_NS, "majorTickMark", {"val": "out"})
        _element(y_axis, _CHART_NS, "minorTickMark", {"val": "none"})
        _element(y_axis, _CHART_NS, "tickLblPos", {"val": "nextTo"})
        _element(y_axis, _CHART_NS, "crossAx", {"val": axis_ids[0]})
        _element(y_axis, _CHART_NS, "crosses", {"val": "autoZero"})
    else:
        category_axis = _element(plot_area, _CHART_NS, "catAx")
        _element(category_axis, _CHART_NS, "axId", {"val": axis_ids[0]})
        scaling = _element(category_axis, _CHART_NS, "scaling")
        _element(scaling, _CHART_NS, "orientation", {"val": "minMax"})
    # Do not rely on Office's defaults: some renderers suppress tick labels
    # when a chart is created from hand-authored OOXML.
        _element(category_axis, _CHART_NS, "delete", {"val": "0"})
        _element(category_axis, _CHART_NS, "axPos", {"val": "b"})
        _axis_title(category_axis, x_axis_title)
        _element(category_axis, _CHART_NS, "majorTickMark", {"val": "out"})
        _element(category_axis, _CHART_NS, "minorTickMark", {"val": "none"})
        _element(category_axis, _CHART_NS, "tickLblPos", {"val": "nextTo"})
        _element(category_axis, _CHART_NS, "crossAx", {"val": axis_ids[1]})
        _element(category_axis, _CHART_NS, "crosses", {"val": "autoZero"})
        _element(category_axis, _CHART_NS, "auto", {"val": "1"})
        _element(category_axis, _CHART_NS, "lblOffset", {"val": "100"})
        if len(categories) >= 12:
            skip = max(1, int(np.ceil(len(categories) / 8)))
            _element(category_axis, _CHART_NS, "tickLblSkip", {"val": skip})
            _element(category_axis, _CHART_NS, "tickMarkSkip", {"val": skip})
        value_axis = _element(plot_area, _CHART_NS, "valAx")
        _element(value_axis, _CHART_NS, "axId", {"val": axis_ids[1]})
        scaling = _element(value_axis, _CHART_NS, "scaling")
        _element(scaling, _CHART_NS, "orientation", {"val": "minMax"})
        _element(value_axis, _CHART_NS, "delete", {"val": "0"})
        _element(value_axis, _CHART_NS, "axPos", {"val": "l"})
        _element(value_axis, _CHART_NS, "majorGridlines")
        _axis_title(value_axis, y_axis_title)
        _element(value_axis, _CHART_NS, "numFmt", {"formatCode": "0.00", "sourceLinked": "0"})
        _element(value_axis, _CHART_NS, "majorTickMark", {"val": "out"})
        _element(value_axis, _CHART_NS, "minorTickMark", {"val": "none"})
        _element(value_axis, _CHART_NS, "tickLblPos", {"val": "nextTo"})
        _element(value_axis, _CHART_NS, "crossAx", {"val": axis_ids[0]})
        _element(value_axis, _CHART_NS, "crosses", {"val": "autoZero"})
        _element(value_axis, _CHART_NS, "crossBetween", {"val": "between"})
    legend = _element(chart, _CHART_NS, "legend")
    _element(legend, _CHART_NS, "legendPos", {"val": "b"})
    _element(legend, _CHART_NS, "overlay", {"val": "0"})
    _element(chart, _CHART_NS, "plotVisOnly", {"val": "1"})
    _element(chart, _CHART_NS, "dispBlanksAs", {"val": "gap"})
    external_data = _element(
        root,
        _CHART_NS,
        "externalData",
        {"{" + _REL_NS + "}id": workbook_relationship_id},
    )
    _element(external_data, _CHART_NS, "autoUpdate", {"val": "0"})
    _element(root, _CHART_NS, "printSettings")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def add_editable_chart(
    document,
    paragraph,
    title: str,
    categories: Sequence[str],
    series_data: Sequence[tuple[str, Sequence[float | None]]],
    *,
    chart_type: str = "line",
    x_axis_title: str = "Period",
    y_axis_title: str = "Value",
    width: float = 6.4,
) -> None:
    if chart_type not in {"line", "bar", "scatter"}:
        raise ValueError("Native Word charts support line, column, and scatter chart types.")
    if not categories or not series_data:
        raise ValueError("Native Word charts require categories and at least one series.")

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Sheet1"
    sheet.cell(1, 1, "Period")
    for index, (name, values) in enumerate(series_data, start=2):
        sheet.cell(1, index, name)
        if len(values) != len(categories):
            raise ValueError(f"Chart series '{name}' does not match the category count.")
    for row_index, category in enumerate(categories, start=2):
        sheet.cell(row_index, 1, float(category) if chart_type == "scatter" else str(category))
        for column_index, (_, values) in enumerate(series_data, start=2):
            value = values[row_index - 2]
            sheet.cell(row_index, column_index, float(value) if value is not None else None)
    workbook_stream = BytesIO()
    workbook.save(workbook_stream)

    package = document.part.package
    workbook_name = package.next_partname("/word/embeddings/EmbeddedWorkbook%d.xlsx")
    workbook_part = Part(
        workbook_name,
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        workbook_stream.getvalue(),
        package,
    )
    chart_name = package.next_partname("/word/charts/chart%d.xml")
    chart_part = Part(
        chart_name,
        CONTENT_TYPE.DML_CHART,
        b"",
        package,
    )
    workbook_relationship_id = chart_part.relate_to(
        workbook_part, RELATIONSHIP_TYPE.PACKAGE
    )
    chart_part._blob = _build_chart_xml(
        title,
        categories,
        series_data,
        chart_type,
        x_axis_title,
        y_axis_title,
        workbook_relationship_id,
    )
    relationship_id = document.part.relate_to(chart_part, RELATIONSHIP_TYPE.CHART)

    drawing_xml = f"""
    <w:drawing {nsdecls('w', 'wp', 'a', 'c', 'r')}>
      <wp:inline distT="0" distB="0" distL="0" distR="0">
        <wp:extent cx="{int(width * 914400)}" cy="{int(width * 0.58 * 914400)}"/>
        <wp:docPr id="{len(document.part.rels) + 1}" name="{escape(title)}"/>
        <wp:cNvGraphicFramePr><a:graphicFrameLocks noChangeAspect="1"/></wp:cNvGraphicFramePr>
        <a:graphic><a:graphicData uri="{_CHART_NS}">
          <c:chart r:id="{relationship_id}"/>
        </a:graphicData></a:graphic>
      </wp:inline>
    </w:drawing>
    """
    paragraph._p.append(parse_xml(drawing_xml))


def append_editable_charts_xlsx(path, chart_specs: Sequence[dict]) -> None:
    """Add native, data-backed Excel charts and their editable source tables."""
    workbook = load_workbook(path)
    charts_sheet = workbook.create_sheet("Editable charts")
    charts_sheet.sheet_view.showGridLines = False
    for index, spec in enumerate(chart_specs, start=1):
        data_name = f"Chart data {index}"
        data_sheet = workbook.create_sheet(data_name[:31])
        data_sheet.append([spec["x_axis_title"], *[name for name, _ in spec["series"]]])
        for row_index, category in enumerate(spec["categories"], start=2):
            row = [category]
            for _, values in spec["series"]:
                row.append(values[row_index - 2] if row_index - 2 < len(values) else None)
            data_sheet.append(row)
        chart_type = spec.get("chart_type", "line")
        chart_cls = ScatterChart if chart_type == "scatter" else BarChart if chart_type == "bar" else LineChart
        chart = chart_cls()
        if isinstance(chart, ScatterChart):
            xvalues = Reference(data_sheet, min_col=1, min_row=2, max_row=1 + len(spec["categories"]))
            for column in range(2, 2 + len(spec["series"])):
                yvalues = Reference(data_sheet, min_col=column, min_row=1, max_row=1 + len(spec["categories"]))
                chart.series.append(Series(yvalues, xvalues, title_from_data=True))
            chart.style = 13
        elif isinstance(chart, BarChart):
            chart.type = "col"
            chart.style = 10
            data = Reference(data_sheet, min_col=2, max_col=1 + len(spec["series"]), min_row=1, max_row=1 + len(spec["categories"]))
            categories = Reference(data_sheet, min_col=1, min_row=2, max_row=1 + len(spec["categories"]))
            chart.add_data(data, titles_from_data=True)
            chart.set_categories(categories)
        else:
            chart.style = 13
            data = Reference(data_sheet, min_col=2, max_col=1 + len(spec["series"]), min_row=1, max_row=1 + len(spec["categories"]))
            categories = Reference(data_sheet, min_col=1, min_row=2, max_row=1 + len(spec["categories"]))
            chart.add_data(data, titles_from_data=True)
            chart.set_categories(categories)
        chart.title = spec["title"]
        chart.x_axis.title = spec["x_axis_title"]
        chart.y_axis.title = spec["y_axis_title"]
        chart.x_axis.delete = False
        chart.y_axis.delete = False
        chart.x_axis.tickLblPos = "nextTo" if isinstance(chart, ScatterChart) else "low"
        chart.y_axis.tickLblPos = "nextTo"
        chart.x_axis.majorTickMark = "out"
        chart.y_axis.majorTickMark = "out"
        chart.y_axis.numFmt = "0.00"
        chart.height = 8.2
        chart.width = 15.5
        chart.legend.position = "b"
        anchor_row = ((index - 1) // 2) * 17 + 1
        anchor_col = "A" if index % 2 else "J"
        charts_sheet.add_chart(chart, f"{anchor_col}{anchor_row}")
        data_sheet.freeze_panes = "B2"
        data_sheet.auto_filter.ref = data_sheet.dimensions
        for cell in data_sheet[1]:
            cell.font = cell.font.copy(bold=True)
        data_sheet.column_dimensions["A"].width = 22
        for column in range(2, 2 + len(spec["series"])):
            data_sheet.column_dimensions[chr(64 + column)].width = 20
    workbook.save(path)


def _clean_numeric(values: Sequence) -> list[float | None]:
    cleaned = []
    for value in values:
        if value is None:
            cleaned.append(None)
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            cleaned.append(None)
            continue
        cleaned.append(number if number == number and abs(number) != float("inf") else None)
    return cleaned


def time_series_chart_specs(result) -> list[dict]:
    if result.get("analysis_type") in {"exogenous", "multivariate"}:
        return _extended_time_series_chart_specs(result)
    plot = result["time_series_plot"]
    variable = _measurement_axis(result["value_column"])
    variable_name = str(result["value_column"]).replace("_", " ")
    periods = [str(value) for value in plot["periods"]]
    original = _clean_numeric(plot["values"])
    specs = [
        {
            "title": f"{result['value_column']}: original series and trend",
            "categories": periods,
            "series": [
                ("Observed", original),
                ("Linear trend", _clean_numeric(result["trend_values"])),
            ],
            "x_axis_title": result["date_column"],
            "y_axis_title": _measurement_axis(result["value_column"]),
        },
        {
            "title": f"{variable_name}: Rolling Mean and Standard Deviation",
            "categories": periods,
            "series": [
                ("Rolling mean", _clean_numeric(plot["rolling_mean"])),
                ("Rolling standard deviation", _clean_numeric(plot["rolling_standard_deviation"])),
            ],
            "x_axis_title": result["date_column"],
            "y_axis_title": variable,
        },
        {
            "title": f"{variable_name}: First and Second Differences",
            "categories": periods,
            "series": [("First difference", _clean_numeric(plot["first_difference"]))],
            "x_axis_title": result["date_column"],
            "y_axis_title": f"Change in {variable}",
        },
        {
            "title": f"{variable_name}: Autocorrelation and Partial Autocorrelation",
            "categories": [str(index) for index in range(len(result["correlogram"]["acf"]))],
            "series": [
                ("ACF", _clean_numeric(result["correlogram"]["acf"])),
                ("PACF", _clean_numeric(result["correlogram"]["pacf"])),
            ],
            "x_axis_title": "Lag",
            "y_axis_title": "Correlation",
        },
    ]
    decomposition = result.get("decomposition_plot", {})
    if decomposition:
        specs.append(
            {
                "title": f"{variable_name}: {decomposition['model'].title()} Seasonal Decomposition",
                "categories": periods,
                "series": [
                    ("Observed", _clean_numeric(decomposition["observed"])),
                    ("Trend", _clean_numeric(decomposition["trend"])),
                    ("Seasonal", _clean_numeric(decomposition["seasonal"])),
                    ("Residual", _clean_numeric(decomposition["resid"])),
                ],
                "x_axis_title": result["date_column"],
                "y_axis_title": _measurement_axis(result["value_column"]),
            }
        )
    if plot.get("second_difference"):
        specs[2]["series"].append(
            ("Second difference", _clean_numeric(plot["second_difference"]))
        )
    if result.get("fitted_values") and result.get("fitted_index"):
        fitted_periods = [str(value) for value in result["fitted_index"]]
        observed_by_period = dict(zip(periods, original))
        specs.append(
            {
                "title": f"{variable_name}: Actual versus Historical Fitted Values",
                "categories": fitted_periods,
                "series": [
                    ("Actual", [observed_by_period.get(value) for value in fitted_periods]),
                    ("Fitted", _clean_numeric(result["fitted_values"])),
                ],
                "x_axis_title": result["date_column"],
                "y_axis_title": _measurement_axis(result["value_column"]),
            }
        )
    holdout = result.get(
        "holdout", {"periods": [], "actual": [], "predicted": []}
    )
    if holdout["periods"] and len(holdout["periods"]) == len(holdout["predicted"]):
        specs.append(
            {
                "title": f"{variable_name}: Chronological Holdout Predictions",
                "categories": [str(value) for value in holdout["periods"]],
                "series": [
                    ("Actual", _clean_numeric(holdout["actual"])),
                    ("Predicted", _clean_numeric(holdout["predicted"])),
                ],
                "x_axis_title": result["date_column"],
                "y_axis_title": _measurement_axis(result["value_column"]),
            }
        )
    saved_forecasts = result.get("forecast", [])
    forecast_categories = [
        str(value)
        for value in result.get(
            "forecast_index", [item.get("period") for item in saved_forecasts]
        )
    ]
    if forecast_categories:
        forecast_values = result.get(
            "forecast_values", [item.get("value") for item in saved_forecasts]
        )
        forecast_lower = result.get(
            "forecast_lower", [item.get("lower") for item in saved_forecasts]
        )
        forecast_upper = result.get(
            "forecast_upper", [item.get("upper") for item in saved_forecasts]
        )
        interval_series = []
        forecast_intervals = result.get("forecast_intervals", {})
        for level in ("80%", "95%"):
            if level in forecast_intervals:
                interval_series.extend(
                    [
                        (f"Lower {level} interval", _clean_numeric(forecast_intervals[level]["lower"])),
                        (f"Upper {level} interval", _clean_numeric(forecast_intervals[level]["upper"])),
                    ]
                )
        if not interval_series:
            interval_series = [
                ("Lower prediction interval", _clean_numeric(forecast_lower)),
                ("Upper prediction interval", _clean_numeric(forecast_upper)),
            ]
        specs.append(
            {
                "title": f"{variable_name}: Future Forecasts and Prediction Intervals",
                "categories": forecast_categories,
                "series": [
                    ("Forecast", _clean_numeric(forecast_values)),
                    *interval_series,
                ],
                "x_axis_title": result["date_column"],
                "y_axis_title": _measurement_axis(result["value_column"]),
            }
        )
    comparison = result.get("model_comparison", {})
    if comparison:
        names = list(comparison)
        specs.append(
            {
                "title": f"{variable_name}: Forecast Model Comparison (RMSE and MAE)",
                "categories": names,
                "series": [
                    ("RMSE", _clean_numeric([comparison[name]["RMSE"] for name in names])),
                    ("MAE", _clean_numeric([comparison[name]["MAE"] for name in names])),
                ],
                "chart_type": "bar",
                "x_axis_title": "Forecast model",
                "y_axis_title": f"Forecast error ({variable})",
            }
        )
        mape_names = [
            name for name in names if comparison[name].get("MAPE") is not None
        ]
        if mape_names:
            specs.append(
                {
                    "title": f"{variable_name}: Forecast Model Comparison (MAPE)",
                    "categories": mape_names,
                    "series": [
                        (
                            "MAPE (%)",
                            _clean_numeric([comparison[name]["MAPE"] for name in mape_names]),
                        )
                    ],
                    "chart_type": "bar",
                    "x_axis_title": "Forecast model",
                    "y_axis_title": "MAPE (%)",
                }
            )
    residual_plot = result.get("residual_plot", {})
    if residual_plot.get("periods") and residual_plot.get("values"):
        specs.append(
            {
                    "title": f"{variable_name}: Model Residuals over Time",
                "categories": [str(value) for value in residual_plot["periods"]],
                "series": [("Residual", _clean_numeric(residual_plot["values"]))],
                "x_axis_title": result["date_column"],
                    "y_axis_title": f"Residual ({variable})",
            }
        )
    residual_values = _clean_numeric(residual_plot.get("values", []))
    residual_values = [value for value in residual_values if value is not None]
    if len(residual_values) >= 4:
        counts, edges = np.histogram(residual_values, bins="auto")
        specs.append(
            {
                "title": f"{variable_name}: Residual Distribution",
                "categories": [f"{edges[i]:.3g} to {edges[i + 1]:.3g}" for i in range(len(counts))],
                "series": [("Frequency", [int(value) for value in counts])],
                "chart_type": "bar",
                "x_axis_title": f"Residual ({variable})",
                "y_axis_title": "Frequency",
            }
        )
        ordered = np.sort(np.asarray(residual_values, dtype=float))
        try:
            from scipy.stats import norm
            theoretical = norm.ppf((np.arange(len(ordered)) + 0.5) / len(ordered))
        except ImportError:
            theoretical = np.linspace(-2.5, 2.5, len(ordered))
        specs.append(
            {
                "title": f"{variable_name}: Normal Q-Q Diagnostic",
                "categories": [f"{value:.3f}" for value in theoretical],
                "series": [("Ordered residuals", _clean_numeric(ordered.tolist()))],
                "x_axis_title": "Theoretical normal quantile",
                "y_axis_title": f"Observed residual ({variable})",
            }
        )
        residual_acf = _clean_numeric(result.get("residual_acf", []))
        if residual_acf:
            specs.append(
                {
                    "title": f"{variable_name}: Residual Autocorrelation",
                    "categories": [str(lag) for lag in range(len(residual_acf))],
                    "series": [("Residual ACF", residual_acf)],
                    "x_axis_title": "Lag (years)",
                    "y_axis_title": "Autocorrelation",
                }
            )
    return specs


def _extended_time_series_chart_specs(result) -> list[dict]:
    specs = []
    if result.get("analysis_type") == "exogenous":
        holdout = result.get("holdout", {})
        if holdout.get("periods"):
            specs.append(
                {
                    "title": f"{result['dependent_variable']}: actual and predicted",
                    "categories": [str(value) for value in holdout["periods"]],
                    "series": [
                        ("Actual", _clean_numeric(holdout["actual"])),
                        ("Predicted", _clean_numeric(holdout["predicted"])),
                    ],
                    "x_axis_title": result["date_column"],
                    "y_axis_title": _measurement_axis(result["dependent_variable"]),
                }
            )
        for scenario, forecast in result.get("scenario_forecasts", {}).items():
            specs.append(
                {
                    "title": f"{result['dependent_variable']} forecast — {scenario}",
                    "categories": [str(value) for value in forecast["forecast_index"]],
                    "series": [
                        ("Forecast", _clean_numeric(forecast["forecast_values"])),
                        ("Lower interval", _clean_numeric(forecast["forecast_lower"])),
                        ("Upper interval", _clean_numeric(forecast["forecast_upper"])),
                    ],
                    "x_axis_title": result["date_column"],
                    "y_axis_title": _measurement_axis(result["dependent_variable"]),
                }
            )
    else:
        holdout = result.get("holdout", {})
        future = result.get("forecast", {})
        for variable in result.get("endogenous_variables", []):
            if holdout.get("periods"):
                specs.append(
                    {
                        "title": f"{variable}: multivariate holdout forecast",
                        "categories": [str(value) for value in holdout["periods"]],
                        "series": [
                            ("Actual", _clean_numeric(holdout["actual"][variable])),
                            ("Predicted", _clean_numeric(holdout["predicted"][variable])),
                        ],
                        "x_axis_title": result["date_column"],
                        "y_axis_title": variable,
                    }
                )
            if future.get("periods"):
                specs.append(
                    {
                        "title": f"{variable}: multivariate future forecast",
                        "categories": [str(value) for value in future["periods"]],
                        "series": [
                            ("Forecast", _clean_numeric(future["values"][variable])),
                        ],
                        "x_axis_title": result["date_column"],
                        "y_axis_title": variable,
                    }
                )
        impulse = result.get("impulse_responses", {})
        if "values" in impulse:
            values = np.asarray(impulse["values"], dtype=float)
            for response_index, response in enumerate(impulse["variables"]):
                specs.append(
                    {
                        "title": f"Impulse response of {response}",
                        "categories": [str(value) for value in impulse["periods"]],
                        "series": [
                            (
                                f"Shock: {shock}",
                                _clean_numeric(values[:, response_index, shock_index]),
                            )
                            for shock_index, shock in enumerate(impulse["variables"])
                        ],
                        "x_axis_title": "Horizon",
                        "y_axis_title": "Response",
                    }
                )
        fevd = result.get("fevd", {})
        if isinstance(fevd, dict) and "values" in fevd:
            values = np.asarray(fevd["values"], dtype=float)
            for response_index, response in enumerate(fevd["variables"]):
                specs.append(
                    {
                        "title": f"{response}: Forecast Error Variance Decomposition",
                        "categories": [str(value) for value in fevd["periods"]],
                        "series": [
                            (str(shock), _clean_numeric((100 * values[:, response_index, shock_index]).tolist()))
                            for shock_index, shock in enumerate(fevd["variables"])
                        ],
                        "x_axis_title": "Forecast horizon (years)",
                        "y_axis_title": "Variance share (%)",
                    }
                )
    return specs
