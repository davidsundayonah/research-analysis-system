"""Independent checks for revised analysis outputs; no source files are changed."""
from __future__ import annotations

import hashlib
import json
import posixpath
import re
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import numpy as np
import pandas as pd
import openpyxl

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.revised_time_series_analysis import SOURCE, OUT, TABLES, TARGET, forecast_model
from tools.build_revision_report import chart_specs

NS = {
    "c": "http://schemas.openxmlformats.org/drawingml/2006/chart",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
}


def eq_values(actual, expected, tol=1e-10):
    if len(actual) != len(expected):
        return False
    for a, e in zip(actual, expected):
        if e is None:
            if a is not None:
                return False
        elif isinstance(e, (int, float, np.number)):
            if a is None or not np.isclose(float(a), float(e), rtol=tol, atol=tol):
                return False
        elif str(a) != str(e):
            return False
    return True


def main():
    frame = pd.read_csv(SOURCE)
    sha = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    recorded_sha = (OUT / "source_sha256.txt").read_text().strip()
    validation = pd.read_csv(TABLES / "expanding_window_5year_forecasts.csv")
    origins = sorted(validation.Origin_year.unique().tolist())
    origin_structure_ok = origins == list(range(2010, 2021))
    per_model_ok = True
    per_model_counts = {}
    source_values = dict(zip(frame.Year, frame[TARGET]))
    for model, group in validation.groupby("Model"):
        per_model_counts[model] = {"origins": int(group.Origin_year.nunique()), "errors": len(group)}
        per_model_ok &= len(group) == 55 and group.groupby("Origin_year").Horizon.apply(lambda x: sorted(x.tolist()) == [1,2,3,4,5]).all()
        for origin, og in group.groupby("Origin_year"):
            og = og.sort_values("Horizon")
            per_model_ok &= (og.Forecast_year.to_numpy() == np.arange(origin + 1, origin + 6)).all()
            per_model_ok &= np.allclose(og.Actual.to_numpy(), [source_values[int(y)] for y in og.Forecast_year], atol=1e-12)
    # Independently refit every candidate on each prefix only.
    leakage_checks = {}
    convergence = {}
    years = frame.Year.to_numpy(int)
    y = frame[TARGET].to_numpy(float)
    for model in sorted(validation.Model.unique()):
        max_abs_diff = 0.0
        observed_convergence = []
        for origin in origins:
            observed = validation[(validation.Model == model) & (validation.Origin_year == origin)].sort_values("Horizon")
            prefix_length = int(np.where(years == origin)[0][0] + 1)
            pred, fit = forecast_model(model, y[:prefix_length], 5)
            max_abs_diff = max(max_abs_diff, float(np.max(np.abs(pred - observed.Predicted.to_numpy()))))
            if fit is not None and hasattr(fit, "mle_retvals"):
                observed_convergence.append(bool(fit.mle_retvals.get("converged", True)))
        leakage_checks[model] = max_abs_diff
        if observed_convergence:
            convergence[model] = {"fits_with_convergence_flag": len(observed_convergence), "converged": int(sum(observed_convergence)),
                                  "not_converged": int(len(observed_convergence) - sum(observed_convergence))}

    fdf = pd.read_csv(TABLES / "final_2026_2030_forecasts_block_bootstrap.csv")
    chart_spec = chart_specs(frame, fdf)
    docx_path = OUT / "revised_time_series_analysis_report.docx"
    xlsx_path = OUT / "revised_time_series_editable_charts.xlsx"
    docx = zipfile.ZipFile(docx_path)
    chart_files = sorted([n for n in docx.namelist() if re.fullmatch(r"word/charts/chart\d+\.xml", n)], key=lambda n: int(re.search(r"chart(\d+)", n).group(1)))
    chart_values_ok, chart_axes_ok, titles = True, True, []
    legends_ok, chart_cache_ok = True, True
    chart_sources = []
    for i, name in enumerate(chart_files):
        root = ET.fromstring(docx.read(name))
        title = "".join(t.text or "" for t in root.findall(".//c:title//a:t", NS))
        titles.append(title)
        spec = chart_spec[i]
        chart_axes = root.findall(".//c:catAx", NS) + root.findall(".//c:valAx", NS)
        chart_axes_ok &= bool(title and chart_axes)
        legends_ok &= root.find(".//c:legend", NS) is not None
        for axis_index, axis in enumerate(chart_axes):
            axis_title = "".join(t.text or "" for t in axis.findall("c:title//a:t", NS))
            delete = axis.find("c:delete", NS)
            tickpos = axis.find("c:tickLblPos", NS)
            chart_axes_ok &= bool(axis_title and delete is not None and delete.get("val") == "0" and tickpos is not None and tickpos.get("val") == "nextTo")
            expected_axis_title = spec["x_axis_title"] if axis_index == 0 else spec["y_axis_title"]
            chart_axes_ok &= axis_title == expected_axis_title
            if axis.tag.endswith("valAx"):
                chart_axes_ok &= axis.find("c:numFmt", NS) is not None

        # Chart cache values must match the chart's editable embedded workbook values.
        relname = name.rsplit("/", 1)[0] + "/_rels/" + name.rsplit("/", 1)[1] + ".rels"
        relroot = ET.fromstring(docx.read(relname))
        rel = next(r for r in relroot if r.get("Type", "").endswith("/package"))
        target = posixpath.normpath(posixpath.join("word/charts", rel.get("Target")))
        chart_sources.append(target)
        book_bytes = docx.read(target)
        import io
        wb = openpyxl.load_workbook(io.BytesIO(book_bytes), data_only=True, read_only=True)
        ws = wb["Sheet1"]
        categories = [ws.cell(r, 1).value for r in range(2, 2 + len(spec["categories"]))]
        chart_values_ok &= eq_values(categories, list(spec["categories"]))
        for j, (series_name, series_values) in enumerate(spec["series"], start=2):
            chart_values_ok &= ws.cell(1, j).value == series_name
            values = [ws.cell(r, j).value for r in range(2, 2 + len(series_values))]
            chart_values_ok &= eq_values(values, list(series_values))
        # Also compare each chart's cached/display values with the same spec.
        chart_series = root.findall(".//c:ser", NS)
        chart_cache_ok &= len(chart_series) == len(spec["series"])
        for ser, (expected_name, expected_values) in zip(chart_series, spec["series"]):
            name_values = [x.text for x in ser.findall(".//c:tx//c:strCache/c:pt/c:v", NS)]
            chart_cache_ok &= name_values == [expected_name]
            is_scatter = root.find(".//c:scatterChart", NS) is not None
            cat_tag = "c:xVal" if is_scatter else "c:cat"
            val_tag = "c:yVal" if is_scatter else "c:val"
            cat_cache = ser.findall(f"{cat_tag}//c:pt/c:v", NS)
            val_cache = ser.findall(f"{val_tag}//c:pt/c:v", NS)
            chart_cache_ok &= eq_values([x.text for x in cat_cache], list(spec["categories"]))
            chart_cache_ok &= eq_values([float(x.text) for x in val_cache], list(expected_values))

    excel = openpyxl.load_workbook(xlsx_path, data_only=False, read_only=False)
    excel_chart_count = sum(len(s._charts) for s in excel.worksheets)
    excel_values_ok = excel_chart_count == len(chart_spec)
    for i, spec in enumerate(chart_spec, start=1):
        ws = excel[f"Chart data {i}"]
        excel_values_ok &= ws.cell(1, 1).value == spec["x_axis_title"]
        for j, (name, values) in enumerate(spec["series"], start=2):
            excel_values_ok &= ws.cell(1, j).value == name
            observed = [ws.cell(r, 1).value for r in range(2, 2 + len(spec["categories"]))]
            excel_values_ok &= eq_values(observed, list(spec["categories"]))
            observed_values = [ws.cell(r, j).value for r in range(2, 2 + len(values))]
            excel_values_ok &= eq_values(observed_values, list(values))

    result = {
        "source_rows": len(frame), "source_years": [int(frame.Year.min()), int(frame.Year.max())],
        "source_columns": list(frame.columns), "source_sha256": sha,
        "source_hash_matches_analysis_record": sha == recorded_sha,
        "validation_origins": origins, "five_year_origin_structure_ok": origin_structure_ok,
        "per_model_origin_error_counts_and_horizons_ok": bool(per_model_ok),
        "validation_models": per_model_counts,
        "max_abs_prediction_difference_vs_refit_on_training_prefix": leakage_checks,
        "all_model_prefix_refit_no_leakage_match": all(v < 1e-8 for v in leakage_checks.values()),
        "optimizer_convergence_for_models_exposing_flag": convergence,
        "word_chart_count": len(chart_files), "word_chart_unique_titles": len(set(titles)) == len(titles),
        "word_chart_axis_title_tick_and_numfmt_checks": bool(chart_axes_ok),
        "word_embedded_workbooks_match_chart_specs": bool(chart_values_ok),
        "word_chart_cached_series_and_category_values_match_specs": bool(chart_cache_ok),
        "word_chart_legends_present": bool(legends_ok),
        "excel_chart_count": excel_chart_count, "excel_chart_source_sheets_match_specs": bool(excel_values_ok),
        "word_chart_embedded_workbook_count": len(set(chart_sources)),
        "visual_rendering_available": False,
        "visual_rendering_limitation": "No Microsoft Word/Excel or LibreOffice renderer is installed; axis visibility is confirmed from chart XML/settings, not a rendered screenshot.",
    }
    (OUT / "final_independent_verification.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
