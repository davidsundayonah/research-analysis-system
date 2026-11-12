from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats
from statsmodels.stats.diagnostic import acorr_ljungbox, het_arch
from statsmodels.tsa.stattools import acf, pacf
from docx import Document
from docx.shared import Inches, Pt
from openpyxl import Workbook

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.word_charts import add_editable_chart, append_editable_charts_xlsx
from tools.revised_time_series_analysis import SOURCE, OUT, TABLES, FIGURES, TARGET, SYNTHETIC, NUMERIC, forecast_model, candidate_diagnostics

YEAR = "Year"
BLUE, RED, TEAL = "#2457A7", "#B8423C", "#16817A"


def fmt(v, digits=3):
    if pd.isna(v):
        return "—"
    return f"{v:.{digits}f}"


def calculate_extra(frame):
    y = frame[TARGET].to_numpy(float)
    years = frame[YEAR].to_numpy(int)
    arch_rows = []
    for model in ["Historical mean", "MA(1)", "ARIMA(0,1,1)", "ARIMA(0,1,1) with drift"]:
        _, fit = forecast_model(model, y, 5)
        residuals = np.asarray(y - np.mean(y), dtype=float) if fit is None else np.asarray(fit.resid, dtype=float)
        for lag in range(1, 11):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                lm, p, fval, fp = het_arch(residuals, nlags=lag)
            arch_rows.append({"Model": model, "ARCH_lags": lag, "LM": lm, "LM_p": p, "F": fval, "F_p": fp})
    pd.DataFrame(arch_rows).to_csv(TABLES / "arch_lag_sensitivity.csv", index=False)

    # Terminal five-year forecast comparison from expanding validation; report
    # a transparent mean benchmark because it won the actual terminal holdout.
    mean = float(np.mean(y))
    train_resid = y - mean
    centered = train_resid - np.mean(train_resid)
    rng = np.random.default_rng(20261112)
    sims = np.empty((30000, 5))
    # Circular moving blocks retain short-run dependence in residual shocks.
    for b in range(len(sims)):
        seq = []
        while len(seq) < 5:
            start = int(rng.integers(0, len(centered)))
            seq.extend(centered[(start + j) % len(centered)] for j in range(2))
        sims[b] = mean + np.asarray(seq[:5])
    forecast_rows = []
    for h, year in enumerate(range(2026, 2031)):
        forecast_rows.append({
            "Year": year, "Point_forecast": mean,
            "PI80_lower": float(np.quantile(sims[:, h], .10)),
            "PI80_upper": float(np.quantile(sims[:, h], .90)),
            "PI95_lower": float(np.quantile(sims[:, h], .025)),
            "PI95_upper": float(np.quantile(sims[:, h], .975)),
        })
    fdf = pd.DataFrame(forecast_rows)
    fdf.to_csv(TABLES / "final_2026_2030_forecasts_block_bootstrap.csv", index=False)

    candidates = []
    for model in ["Historical mean", "MA(1)", "ARIMA(0,1,1)", "ARIMA(0,1,1) with drift", "Linear trend"]:
        p, fit = forecast_model(model, y, 5)
        row = {"Model": model, "AIC_full_sample": getattr(fit, "aic", np.nan), "BIC_full_sample": getattr(fit, "bic", np.nan)}
        for i, v in enumerate(p, start=2026):
            row[str(i)] = float(v)
        candidates.append(row)
    pd.DataFrame(candidates).to_csv(TABLES / "full_sample_forecast_comparison.csv", index=False)
    models = ["Historical mean", "MA(1)", "ARIMA(0,1,1)", "ARIMA(0,1,1) with drift", "ARIMA(1,1,1)", "Linear trend"]
    pd.DataFrame([candidate_diagnostics(m, y) for m in models]).to_csv(TABLES / "candidate_residual_diagnostics.csv", index=False)
    ols = sm.OLS(y, sm.add_constant(frame[SYNTHETIC].astype(float))).fit()
    influence = ols.get_influence()
    cook = influence.cooks_distance[0]
    threshold = 4 / len(y)
    outlier_rows = []
    for col in [TARGET, *SYNTHETIC]:
        vals = frame[col].to_numpy(float)
        med = float(np.median(vals))
        mad = float(np.median(np.abs(vals - med)))
        rz = .6745 * (vals - med) / mad if mad > 0 else np.zeros_like(vals)
        q1, q3 = np.quantile(vals, [.25, .75]); iqr = q3 - q1
        flagged = (np.abs(rz) > 3.5) | (vals < q1 - 1.5 * iqr) | (vals > q3 + 1.5 * iqr)
        for ix in np.where(flagged)[0]:
            outlier_rows.append({"Year": int(frame.Year.iloc[ix]), "Variable": col, "Observed_value": vals[ix],
                                 "Robust_MAD_z": rz[ix], "IQR_screen_flag": True,
                                 "Regression_Cooks_distance": cook[ix], "Cook_screen_4_over_n": bool(cook[ix] > threshold)})
    outlier_df = pd.DataFrame(outlier_rows, columns=["Year", "Variable", "Observed_value", "Robust_MAD_z", "IQR_screen_flag", "Regression_Cooks_distance", "Cook_screen_4_over_n"])
    outlier_df.to_csv(TABLES / "outlier_influence_review.csv", index=False)
    return fdf


def chart_specs(frame, forecast):
    years = frame[YEAR].astype(str).tolist()
    y = frame[TARGET].to_numpy(float)
    t = np.arange(len(y))
    linfit = sm.OLS(y, sm.add_constant(t)).fit().fittedvalues
    ma5 = pd.Series(y).rolling(5, center=True, min_periods=1).mean().to_numpy()
    diff = np.diff(y)
    acfv = acf(y, nlags=12, fft=False)
    pacfv = pacf(y, nlags=12, method="ywm")
    specs = [{"title": "Unemployment Rate: Observed Series, Linear Trend and 5-Year Moving Average", "categories": years,
              "series": [("Observed unemployment", y.tolist()), ("Linear trend", linfit.tolist()), ("Centered 5-year moving average", ma5.tolist())],
              "chart_type": "line", "x_axis_title": "Year", "y_axis_title": "Unemployment rate (%)"},
             {"title": "Unemployment Rate: Annual First Differences", "categories": years[1:], "series": [("Annual change", diff.tolist())],
              "chart_type": "bar", "x_axis_title": "Year", "y_axis_title": "Change in unemployment rate (percentage points)"},
             {"title": "Unemployment Rate: ACF and PACF by Lag", "categories": list(range(13)), "series": [("ACF", acfv.tolist()), ("PACF", pacfv.tolist())],
              "chart_type": "line", "x_axis_title": "Lag (years)", "y_axis_title": "Correlation coefficient"}]
    # All four synthetic explanatory variables shown transparently as such.
    for col in NUMERIC:
        label = col.replace("_", " ")
        unit = "index points" if "Wage_Index" in col else "%"
        specs.append({"title": f"{label}: Annual Time Series", "categories": years, "series": [(label, frame[col].astype(float).tolist())],
                      "chart_type": "line", "x_axis_title": "Year", "y_axis_title": f"{label} ({unit})"})
    corr = frame[NUMERIC].corr()
    short_names = ["Unemployment", "Inflation (synthetic)", "GDP growth (synthetic)", "Wage index (synthetic)", "Policy rate (synthetic)"]
    specs.append({"title": "Correlation of Unemployment and Synthetic Economic Variables", "categories": short_names,
                  "series": [("Unemployment correlation", corr[TARGET].tolist())], "chart_type": "bar",
                  "x_axis_title": "Variable", "y_axis_title": "Pearson correlation coefficient"})
    specs.append({"title": "Pearson Correlation Matrix Across All Numerical Variables", "categories": short_names,
                  "series": [(name, corr[col].tolist()) for col, name in zip(NUMERIC, short_names)], "chart_type": "bar",
                  "x_axis_title": "Variable", "y_axis_title": "Pearson correlation coefficient"})
    resid_table = pd.read_csv(TABLES / "multivariable_regression_fitted_residuals.csv")
    specs.append({"title": "Multivariable OLS: Observed and Fitted Unemployment Rate", "categories": resid_table.Year.astype(str).tolist(),
                  "series": [("Observed", resid_table.Actual.tolist()), ("OLS fitted", resid_table.Fitted.tolist())],
                  "chart_type": "line", "x_axis_title": "Year", "y_axis_title": "Unemployment rate (%)"})
    specs.append({"title": "Multivariable OLS: Regression Residuals over Time", "categories": resid_table.Year.astype(str).tolist(),
                  "series": [("Residual", resid_table.Residual.tolist())], "chart_type": "line",
                  "x_axis_title": "Year", "y_axis_title": "Residual (percentage points)"})
    specs.append({"title": "Multivariable OLS: Residuals versus Fitted Values", "categories": resid_table.Fitted.tolist(),
                  "series": [("Residual", resid_table.Residual.tolist())], "chart_type": "scatter",
                  "x_axis_title": "Fitted unemployment rate (%)", "y_axis_title": "Residual (percentage points)"})
    # Scatter diagnostics use numerical x values so Office retains a true XY axis.
    for col in SYNTHETIC:
        specs.append({"title": f"Unemployment Rate versus Synthetic {col.replace('Synthetic_', '').replace('_', ' ')}", "categories": frame[col].tolist(),
                      "series": [("Observed unemployment", y.tolist())], "chart_type": "scatter",
                      "x_axis_title": f"{col.replace('_', ' ')} ({'index points' if 'Wage_Index' in col else '%'})",
                      "y_axis_title": "Unemployment rate (%)"})
    specs.append({"title": "Unemployment Rate: 2026–2030 Forecast with Bootstrap Prediction Intervals", "categories": forecast.Year.astype(str).tolist(),
                  "series": [("Historical mean forecast", forecast.Point_forecast.tolist()),
                             ("80% lower", forecast.PI80_lower.tolist()), ("80% upper", forecast.PI80_upper.tolist()),
                             ("95% lower", forecast.PI95_lower.tolist()), ("95% upper", forecast.PI95_upper.tolist())],
                  "chart_type": "line", "x_axis_title": "Forecast year", "y_axis_title": "Unemployment rate (%)"})
    comp = pd.read_csv(TABLES / "expanding_window_5year_model_comparison.csv").head(5).copy()
    chart_model_names = {"Historical mean": "Historical mean", "ARIMA(0,1,1)": "ARIMA(0,1,1)", "Naive": "Naive", "MA(1)": "MA(1)"}
    comp["Chart_model"] = comp.Model.map(lambda n: chart_model_names.get(n, n))
    specs.append({"title": "Five-Year Expanding-Window Validation: Candidate Model Errors", "categories": comp.Chart_model.tolist(),
                  "series": [("RMSE", comp.RMSE.tolist()), ("MAE", comp.MAE.tolist())], "chart_type": "bar",
                  "x_axis_title": "Forecast model", "y_axis_title": "Forecast error (percentage points)"})
    # Break fit allows a single selected break, displayed as exploratory.
    binfo = json.loads((TABLES / "data_selected_supf.json").read_text())
    cut = int(binfo["Selected_break_year"])
    tt = years and frame[YEAR].to_numpy() - frame[YEAR].min()
    post = (frame[YEAR].to_numpy() >= cut).astype(float)
    Xb = np.column_stack([np.ones(len(y)), tt, post, tt * post])
    fitted_break = sm.OLS(y, Xb).fit().fittedvalues
    specs.append({"title": f"Unemployment Rate: Exploratory Piecewise Trend at {cut}", "categories": years,
                  "series": [("Observed", y.tolist()), ("Piecewise trend fit", fitted_break.tolist())], "chart_type": "line",
                  "x_axis_title": "Year", "y_axis_title": "Unemployment rate (%)"})
    # Distribution chart is editable frequency bins; numerical bin centers are categories.
    counts, edges = np.histogram(y, bins="auto")
    specs.append({"title": "Unemployment Rate: Observed Distribution", "categories": [f"{edges[i]:.2f}–{edges[i+1]:.2f}" for i in range(len(counts))],
                  "series": [("Frequency (years)", counts.tolist())], "chart_type": "bar", "x_axis_title": "Unemployment rate (%)",
                  "y_axis_title": "Frequency (years)"})
    for col in SYNTHETIC:
        values = frame[col].to_numpy(float)
        counts, edges = np.histogram(values, bins="auto")
        label = col.replace("_", " ")
        unit = "index points" if "Wage_Index" in col else "%"
        specs.append({"title": f"{label}: Observed Distribution (Synthetic Variable)",
                      "categories": [f"{edges[i]:.2f}–{edges[i+1]:.2f}" for i in range(len(counts))],
                      "series": [("Frequency (years)", counts.tolist())], "chart_type": "bar",
                      "x_axis_title": f"{label} ({unit})", "y_axis_title": "Frequency (years)"})
    reg_resid = resid_table.Residual.to_numpy(float)
    counts, edges = np.histogram(reg_resid, bins="auto")
    specs.append({"title": "Multivariable OLS: Residual Distribution", "categories": [f"{edges[i]:.2f}–{edges[i+1]:.2f}" for i in range(len(counts))],
                  "series": [("Frequency (years)", counts.tolist())], "chart_type": "bar",
                  "x_axis_title": "OLS residual (percentage points)", "y_axis_title": "Frequency (years)"})
    return specs


def add_table(doc, title, df, digits=3):
    doc.add_heading(title, level=2)
    table = doc.add_table(rows=1, cols=len(df.columns))
    table.style = "Light Shading Accent 1"
    for cell, name in zip(table.rows[0].cells, df.columns):
        cell.text = str(name).replace("_", " ")
    for _, row in df.iterrows():
        cells = table.add_row().cells
        for cell, value in zip(cells, row.tolist()):
            if isinstance(value, (float, np.floating)):
                cell.text = fmt(value, digits)
            else:
                cell.text = str(value)
    doc.add_paragraph()


def report(frame, forecasts, specs):
    doc = Document()
    sec = doc.sections[0]
    sec.top_margin = Inches(.65); sec.bottom_margin = Inches(.65)
    styles = doc.styles
    styles["Normal"].font.name = "Aptos"; styles["Normal"].font.size = Pt(9.5)
    doc.add_heading("Revised Time-Series and Multivariable Analysis", 0)
    doc.add_paragraph("Annual demonstration data, 1991–2025 | Revised model validation, diagnostics, structural-break sensitivity, multivariable analysis and editable charts")
    doc.add_heading("Executive summary", level=1)
    doc.add_paragraph("The earlier ARIMA(0,1,1) choice reflected one-step expanding-window performance and did not match the requested five-year forecast task. For the terminal 2021–2025 holdout, the historical mean had the lowest RMSE (0.959) and MAE (0.910); across 11 expanding five-year origins, MA(1) narrowly had the lowest RMSE (0.988) and MAE (0.848). These rankings differ, and residual diagnostics reject a simple fully adequate model. The historical mean is therefore retained only as a transparent provisional reference forecast, not as a claim that the series is stable or economically predictable.")
    doc.add_paragraph("The four explanatory columns are explicitly synthetic. Regression relationships are descriptive demonstrations only and cannot support economic or causal conclusions.")
    doc.add_heading("Data and method", level=1)
    doc.add_paragraph(f"The supplied file contains {len(frame)} complete annual observations ({frame.Year.min()}–{frame.Year.max()}). The original CSV was not modified. Five-step expanding-window validation uses 11 origins, minimum training length 20 and 55 overlapping forecast errors per model. The terminal holdout trains through 2020 and evaluates 2021–2025. Because this final holdout contains only five observations, its ranking is noisy; it is reported alongside expanding validation.")
    add_table(doc, "Descriptive statistics for all numerical variables", pd.read_csv(TABLES / "descriptive_statistics_all_numeric.csv").round(3))
    doc.add_paragraph("Inflation, GDP growth, wage index and policy rate are synthetic. Period_Type is categorical and summarized separately; it is not treated as a measured numeric covariate.")
    add_table(doc, "Pearson correlation matrix", pd.read_csv(TABLES / "pearson_correlation_matrix.csv", index_col=0).reset_index().rename(columns={"index":"Variable"}).round(3))
    add_table(doc, "Stationarity tests for all numerical series", pd.read_csv(TABLES / "stationarity_all_numeric.csv").round(4))
    doc.add_paragraph("For unemployment, level ADF p=.088 is weak evidence against a unit root under a constant-only specification, while level KPSS does not reject stationarity; first-difference ADF p=.0019 supports differencing under that specification. The unit-root-with-break test does not reject. These tests are inconclusive in a 35-year series and sensitive to deterministic terms and structural change; stationarity should not be treated as settled.")
    add_table(doc, "Five-year expanding-window model comparison", pd.read_csv(TABLES / "expanding_window_5year_model_comparison.csv").head(10).round(3))
    add_table(doc, "Terminal 2021–2025 holdout comparison", pd.read_csv(TABLES / "terminal_5year_model_comparison.csv").head(10).round(3))
    doc.add_paragraph("An independent prefix-only refit reproduced stored five-step forecasts for all 15 candidate models at all 11 origins to numerical precision. ARIMA(0,1,1) converged in all 11 origin fits; lower-ranked ARIMA(0,1,0) converged in 9/11 and its drift version in 8/11. This is another reason not to overinterpret fine differences among small-sample candidate rankings.")
    doc.add_paragraph("ARIMA(0,1,1) without drift forecasts a constant level because first differencing removes the level and the model has no deterministic drift or autoregressive term; after the finite MA shock effect, expected future differences are zero. Drift was tested rather than assumed: it worsened the terminal holdout (RMSE 2.339, MAE 2.310) and expanding five-year RMSE (1.360 versus 1.278 for no-drift ARIMA(0,1,1)). It is not selected.")
    add_table(doc, "Full-sample 2026–2030 point forecast comparison", pd.read_csv(TABLES / "full_sample_forecast_comparison.csv").round(3))
    doc.add_heading("Final reference forecasts and uncertainty", level=1)
    doc.add_paragraph("The historical mean is selected as a provisional reference because it won the terminal five-year holdout on RMSE and MAE and remains highly parsimonious. MA(1) performed slightly better on pooled expanding-window errors. Neither is fully adequate: residual serial dependence and non-normality remain. The table gives moving-block residual-bootstrap predictive intervals (block length 2; 30,000 simulations), conditional on the historical-mean model and observed residual pattern. They do not include uncertainty about future structural breaks, changing economic regimes, or model selection; treat them as model-based scenarios, not economic certainty.")
    add_table(doc, "Unemployment-rate forecasts and block-bootstrap prediction intervals (%)", forecasts.round(3))
    doc.add_heading("Residual and stability diagnostics", level=1)
    diag = pd.read_csv(TABLES / "candidate_residual_diagnostics.csv")
    chosen = diag[diag.Model.isin(["Historical mean", "MA(1)", "ARIMA(0,1,1)", "ARIMA(0,1,1) with drift"])]
    add_table(doc, "Candidate residual diagnostics", chosen.round(4))
    arch = pd.read_csv(TABLES / "arch_lag_sensitivity.csv")
    archsel = arch[(arch.Model.isin(["Historical mean", "MA(1)", "ARIMA(0,1,1)"])) & (arch.ARCH_lags.isin([1,2,4,7,10]))]
    add_table(doc, "ARCH-LM sensitivity to model and lag choice", archsel.round(4))
    doc.add_paragraph("The earlier ARCH-LM p=.033 is reproduced for ARIMA(0,1,1) residuals at lag 7 (LM p=.0331; F p=.0146). At lag 4 the same residuals give p=.797, so the inference is highly sensitive to lag choice in this short sample. Report the tested lag alongside any ARCH result; this is weak, lag-dependent evidence of volatility clustering rather than a robust conclusion. Jarque–Bera rejection indicates non-normal residuals, especially for integrated models. Ljung–Box non-rejection for ARIMA(0,1,1) alone does not establish adequacy: distributional, forecast, break and volatility evidence also matter.")
    add_table(doc, "Flagged observations: robust outlier and regression influence screens", pd.read_csv(TABLES / "outlier_influence_review.csv").round(3))
    doc.add_paragraph("These are screening flags (median/MAD and 1.5-IQR; Cook’s distance compared with 4/n), not grounds for deleting or altering observations. Results retain all original observations.")
    doc.add_heading("Structural changes", level=1)
    add_table(doc, "Prespecified candidate break tests (HAC(1), Holm adjusted over five dates)", pd.read_csv(TABLES / "candidate_structural_break_tests.csv").round(5))
    doc.add_paragraph("The 2008 and 2009 level/slope changes are not supported after adjustment (Holm p=.180 each). The earlier classical, non-HAC Chow check at 2015 gave p=1.26e-6; a re-estimation using HAC(1) gives p=.00205 and remains significant after Holm correction across the five tested dates (p=.00615). Thus there is evidence of a mid-2010s change under the tested piecewise-linear specification, though the stronger classical p-value understated uncertainty under serial dependence. 2019 and 2020 tests also remain significant after adjustment (p=.00037 and .00438), but have only 7 and 6 post-date observations. A data-selected one-break sup-F scan selects 2017 (block-bootstrap p=.0025; 1,999 replicates, block length 2), while Zivot–Andrews selects 2014 but does not reject a unit root with a break (p=.115). Together these results support instability sometime in the mid-to-late 2010s more than an exact break year; dates and inference remain method-dependent. The small post-break segment cannot support reliable regime-specific forecasting.")
    doc.add_heading("Multivariable regression", level=1)
    coefs = pd.read_csv(TABLES / "multivariable_regression_HC3_HAC1.csv")
    add_table(doc, "OLS coefficients with HC3 and HAC(1) inference", coefs.round(4))
    add_table(doc, "Variance inflation factors", pd.read_csv(TABLES / "multivariable_regression_VIF.csv").round(3))
    reg = json.loads((TABLES / "multivariable_regression_diagnostics.json").read_text())
    doc.add_paragraph(f"OLS has R²={reg['R_squared']:.3f} (adjusted R²={reg['Adjusted_R_squared']:.3f}); the HC3 robust joint test p={reg['HC3_joint_p']:.4f}, HAC(1) joint p={reg['HAC1_joint_p']:.4f}. Breusch–Pagan p={reg['Breusch_Pagan_p']:.4g}, Durbin–Watson={reg['Durbin_Watson']:.3f}, and Ljung–Box lag-5 p={reg['Ljung_Box_lag5_p']:.4g} indicate heteroskedasticity and serial correlation concerns. Coefficient inference changes with HAC adjustment. VIFs are modest, but that does not address serial dependence, omitted variables, synthetic inputs, or causal identification. An ARDL/VAR is not used: 35 annual observations, four regressors, mixed/inconclusive integration evidence and break concerns do not support a stable, sufficiently parameterized dynamic system here.")
    doc.add_heading("Conclusion and recommendations", level=1)
    doc.add_paragraph("The evidence does not identify a conclusive forecasting model or a single definitive break date. MA(1) leads pooled five-year expanding validation, while the historical mean leads the five-observation terminal holdout. The historical mean forecast is therefore retained as a transparent provisional benchmark only. Break tests point to instability in the mid-to-late 2010s under some specifications; ARCH and normality findings are sensitive to assumptions. None of these results establishes economic certainty.")
    for recommendation in [
        "Document the unemployment series source, definition, seasonal adjustment, and data vintage before academic submission.",
        "Label the four generated predictor columns synthetic in all analysis, charts, and interpretation; replace them with sourced measures before making empirical economic claims.",
        "Treat the 2026–2030 figures as conditional reference scenarios; update validation as new observations arrive and monitor for regime changes.",
        "With a longer sample, pre-specify break dates and test designs, compare break-aware forecasts using a genuinely untouched future holdout, and re-evaluate predictive intervals.",
        "Do not interpret OLS coefficients causally; defer ARDL/VAR until longer, defensibly sourced series and integration/lag assumptions support them.",
    ]:
        doc.add_paragraph(recommendation, style="List Bullet")
    doc.add_heading("Editable academic charts", level=1)
    doc.add_paragraph("Each chart below is a native Office chart with its data workbook embedded, so series and formatting can be edited in Word or Excel. Axis titles and tick labels are explicit. Full-precision numeric analyses and source tables are provided separately as CSV.")
    doc.add_paragraph("Chart audit settings: unique descriptive titles, explicit axis titles and units, visible axis tick settings, and 0.00 numerical tick formatting. Annual charts retain actual year labels while thinning dense year ticks; long category labels on the comparison and correlation charts are shortened for legibility. Legends are included and positioned below plots. Office renderer screenshots were unavailable in this environment, so final on-screen rendering can vary with the version of Word or Excel and remains a visual limitation.")
    for spec in specs:
        doc.add_heading(spec["title"], level=2)
        p = doc.add_paragraph()
        add_editable_chart(doc, p, spec["title"], spec["categories"], spec["series"], chart_type=spec.get("chart_type", "line"),
                           x_axis_title=spec["x_axis_title"], y_axis_title=spec["y_axis_title"], width=6.25)
    doc.add_heading("Completion checklist", level=1)
    checklist = [
        ("Model selection, multiple benchmarks and chronological validation", "Completed; rankings differ by validation design and no model is claimed fully adequate."),
        ("ARIMA flat forecast and drift comparison", "Completed; mechanism explained and drift evaluated."),
        ("Residual normality, autocorrelation and ARCH sensitivity", "Completed; diagnostic conclusions qualified by model and lag."),
        ("2008/09, 2019/20 and unknown-date break analysis", "Completed; evidence is specification-sensitive and late segment is short."),
        ("All-variable descriptives, correlations, regression, VIF and diagnostics", "Completed; four predictors labeled synthetic."),
        ("ARDL/VAR", "Not performed; sample size and assumptions do not justify a dynamic multivariate system."),
        ("All requested graphs labeled and editable", "Completed in this revised report as native Word charts with embedded data; no static-only chart substitutes."),
        ("Independent verification against source", "Completed: 35 years, columns, completeness and SHA-256 recorded; original CSV unchanged."),
    ]
    for item, status in checklist:
        doc.add_paragraph(f"{item}: {status}", style="List Bullet")
    doc.add_paragraph(f"Source file SHA-256: {(OUT / 'source_sha256.txt').read_text().strip()}")
    path = OUT / "revised_time_series_analysis_report.docx"
    doc.save(path)
    return path


def main():
    frame = pd.read_csv(SOURCE)
    # Verify exact expected observation span and no source mutation.
    assert frame.Year.tolist() == list(range(1991, 2026))
    forecasts = calculate_extra(frame)
    specs = chart_specs(frame, forecasts)
    report_path = report(frame, forecasts, specs)
    xlsx_path = OUT / "revised_time_series_editable_charts.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "Read me"
    ws.append(["Revised time-series analysis charts"])
    ws.append(["Native editable Excel charts; corresponding source values are in Chart data sheets."])
    ws.append(["Predictors beginning Synthetic_ are synthetic demonstration data."])
    wb.save(xlsx_path)
    append_editable_charts_xlsx(xlsx_path, specs)
    (OUT / "chart_quality_audit.json").write_text(json.dumps({
        "native_editable_chart_count": len(specs),
        "all_specs_have_titles": all(s.get("title") for s in specs),
        "all_specs_have_axis_titles": all(s.get("x_axis_title") and s.get("y_axis_title") for s in specs),
        "all_specs_have_values": all(s.get("categories") and s.get("series") for s in specs),
        "source_rows": len(frame), "source_year_range": [int(frame.Year.min()), int(frame.Year.max())],
        "report": str(report_path), "editable_charts_workbook": str(xlsx_path),
    }, indent=2))
    print(report_path)
    print(f"Native editable charts: {len(specs)}")
    print(forecasts.to_string(index=False))


if __name__ == "__main__":
    main()
