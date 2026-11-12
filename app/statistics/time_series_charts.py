"""Publication-oriented plots for univariate time-series results."""

from __future__ import annotations

import numpy as np
import pandas as pd


def _unit_for(variable: str, supplied: str = "") -> str:
    if supplied.strip():
        return supplied.strip()
    name = variable.casefold().replace("_", " ")
    if any(token in name for token in ("unemployment", "inflation", "growth", "policy rate", "interest rate", "percent")):
        return "%"
    if "index" in name:
        return "index points"
    return "units not specified"


def _number(value, _position=None):
    if not np.isfinite(value):
        return ""
    magnitude = abs(value)
    if magnitude >= 1000:
        return f"{value:,.0f}"
    if magnitude >= 100:
        return f"{value:,.1f}".rstrip("0").rstrip(".")
    if magnitude >= 1:
        return f"{value:.2f}".rstrip("0").rstrip(".")
    return f"{value:.3f}".rstrip("0").rstrip(".")


def _finish(figure, axes, date_axes=()):
    import matplotlib.dates as mdates
    from matplotlib.ticker import FuncFormatter, MaxNLocator

    for axis in axes:
        axis.grid(axis="y", color="#D9DEE7", alpha=0.8, linewidth=0.65)
        axis.grid(axis="x", color="#D9DEE7", alpha=0.4, linewidth=0.5)
        axis.tick_params(axis="both", which="major", labelsize=9, direction="out", length=3.5, colors="#303846")
        axis.yaxis.set_major_locator(MaxNLocator(nbins=6))
        axis.yaxis.set_major_formatter(FuncFormatter(_number))
        axis.spines["top"].set_visible(False)
        axis.spines["right"].set_visible(False)
        axis.spines["left"].set_color("#9AA3B2")
        axis.spines["bottom"].set_color("#9AA3B2")
    for axis in date_axes:
        locator = mdates.AutoDateLocator(minticks=4, maxticks=8)
        axis.xaxis.set_major_locator(locator)
        axis.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))
        axis.tick_params(axis="x", labelrotation=0)
    figure.tight_layout(rect=(0, 0, 1, 0.92) if figure._suptitle is not None else None, pad=1.6)
    return figure


def create_time_series_charts(dataframe: pd.DataFrame, result: dict) -> dict:
    """Create labelled, consistently styled figures from computed result fields."""
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    from matplotlib.ticker import MaxNLocator
    from scipy.stats import probplot
    from .time_series_analysis import prepare_time_series_frame

    frame = prepare_time_series_frame(dataframe, result["date_column"], result["value_column"])
    dates = frame.index
    values = frame["value"].to_numpy(dtype=float)
    plot = result["time_series_plot"]
    variable = str(result["value_column"]).replace("_", " ").strip()
    date_name = str(result["date_column"]).replace("_", " ").strip()
    unit = _unit_for(variable, str(result.get("measurement_units") or ""))
    value_label = f"{variable} ({unit})"
    change_label = f"Change in {variable} ({unit})"
    colors = {"blue": "#2457A7", "red": "#B8423C", "orange": "#C66A13", "teal": "#16817A", "purple": "#7653A6", "green": "#32845B", "gray": "#687386"}
    figures = {}

    with plt.rc_context({"font.family": "DejaVu Sans", "font.size": 10, "axes.titlesize": 11, "axes.labelsize": 10, "figure.titlesize": 14, "legend.fontsize": 9, "savefig.dpi": 300}):
        # Observed series, straight trend, and rolling mean show distinct types of trend evidence.
        figure, axis = plt.subplots(figsize=(10, 5.6), dpi=120)
        axis.plot(dates, values, color=colors["blue"], linewidth=2.1, label="Observed series", zorder=3)
        axis.plot(result["trend"].index, result["trend"].to_numpy(), color=colors["red"], linestyle="--", linewidth=1.9, label="Fitted linear trend", zorder=2)
        rolling = np.asarray(plot["rolling_mean"], dtype=float)
        if len(rolling) == len(dates):
            axis.plot(dates, rolling, color=colors["teal"], linewidth=1.9, label=f"Moving average ({result['rolling_window']} periods)", zorder=4)
        if variable.casefold() == "unemployment rate" and dates[0].year == 1991 and dates[-1].year == 2025:
            title = "Annual Unemployment Rate and Linear Trend (1991–2025)"
        else:
            title = f"{variable}: Observed Series, Moving Average, and Linear Trend"
        axis.set_title(title, pad=10)
        axis.set_xlabel("Year")
        axis.set_ylabel(value_label)
        axis.legend(loc="best", frameon=True, framealpha=0.94, edgecolor="#D9DEE7")
        if variable.casefold() == "unemployment rate" and dates[0].year == 1991 and dates[-1].year == 2025:
            axis.set_xlim(pd.Timestamp("1991-01-01"), pd.Timestamp("2025-12-31"))
        figures["Original series and trend"] = _finish(figure, [axis], [axis])

        decomposition = result.get("decomposition_plot", {})
        if decomposition:
            figure, axes = plt.subplots(4, 1, figsize=(10, 8), dpi=120, sharex=True)
            periods = pd.to_datetime(decomposition["periods"])
            components = [("observed", "Observed series", colors["blue"]), ("trend", "Estimated trend", colors["red"]), ("seasonal", "Seasonal component", colors["teal"]), ("resid", "Residual component", colors["purple"])]
            for axis, (key, label, color) in zip(axes, components):
                axis.plot(periods, decomposition[key], color=color, linewidth=1.7)
                axis.set_title(label, loc="left", fontsize=10)
                axis.set_ylabel(value_label if key == "observed" else f"{label} ({unit})")
            axes[-1].set_xlabel("Year")
            figure.suptitle(f"{variable}: {decomposition['model'].title()} Seasonal Decomposition (period {decomposition['period']})")
            figures["Seasonal decomposition"] = _finish(figure, list(axes), list(axes))

        figure, axis = plt.subplots(figsize=(10, 5.6), dpi=120)
        axis.plot(dates, plot["first_difference"], color=colors["blue"], linewidth=1.7, label="First difference")
        if plot.get("second_difference"):
            axis.plot(dates, plot["second_difference"], color=colors["orange"], linewidth=1.6, label="Second difference")
        axis.axhline(0, color=colors["gray"], linewidth=0.9)
        axis.set_title(f"{variable}: First-Difference Series")
        axis.set_xlabel("Year")
        axis.set_ylabel(change_label)
        axis.legend(loc="best", frameon=True, edgecolor="#D9DEE7")
        figures["Differences"] = _finish(figure, [axis], [axis])

        figure, axes = plt.subplots(1, 2, figsize=(10, 5.1), dpi=120)
        band = 1.96 / np.sqrt(len(values))
        for axis, key, title, color in zip(axes, ("acf", "pacf"), ("Autocorrelation (ACF)", "Partial Autocorrelation (PACF)"), (colors["blue"], colors["teal"])):
            corr = np.asarray(result["correlogram"][key], dtype=float)
            lags = np.arange(len(corr))
            axis.bar(lags, corr, color=color, width=0.72, edgecolor="white")
            axis.axhspan(-band, band, color=colors["gray"], alpha=0.12, label="Approximate 95% bounds")
            axis.axhline(0, color=colors["gray"], linewidth=0.9)
            axis.set_title(f"{variable}: {title}")
            axis.set_xlabel("Lag (years)")
            axis.set_ylabel("Correlation")
            axis.xaxis.set_major_locator(MaxNLocator(integer=True, nbins=8))
            axis.legend(loc="best", frameon=False, fontsize=8)
        figures["ACF and PACF"] = _finish(figure, list(axes))

        residuals = np.asarray(result.get("residual_plot", {}).get("values", []), dtype=float)
        figure, axes = plt.subplots(2, 2, figsize=(10, 7.2), dpi=120)
        residual_axis, acf_axis, hist_axis, qq_axis = axes.flat
        if len(residuals):
            residual_dates = pd.to_datetime(result["residual_plot"]["periods"])
            residual_axis.plot(residual_dates, residuals, color=colors["purple"], linewidth=1.6)
            residual_axis.axhline(0, color=colors["gray"], linewidth=0.9)
            hist_axis.hist(residuals, bins="auto", color=colors["teal"], alpha=0.83, edgecolor="white")
            residual_acf = np.asarray(result.get("residual_acf", []), dtype=float)
            acf_axis.bar(np.arange(len(residual_acf)), residual_acf, color=colors["blue"], width=0.72)
            residual_band = 1.96 / np.sqrt(len(residuals))
            acf_axis.axhspan(-residual_band, residual_band, color=colors["gray"], alpha=0.12)
            acf_axis.axhline(0, color=colors["gray"], linewidth=0.9)
            acf_axis.xaxis.set_major_locator(MaxNLocator(integer=True, nbins=8))
            if len(residuals) > 2:
                theoretical, ordered = probplot(residuals, dist="norm", fit=False)
                qq_axis.scatter(theoretical, ordered, color=colors["blue"], s=22, alpha=0.85)
                slope, intercept = np.polyfit(theoretical, ordered, 1)
                qq_axis.plot(theoretical, intercept + slope * np.asarray(theoretical), color=colors["red"], linewidth=1.5, linestyle="--", label="Reference line")
                qq_axis.legend(loc="best", frameon=False, fontsize=8)
        else:
            for axis in axes.flat:
                axis.text(0.5, 0.5, "Residuals unavailable", ha="center", va="center", transform=axis.transAxes)
        residual_axis.set_title("Residuals over time", loc="left")
        residual_axis.set_xlabel("Year")
        residual_axis.set_ylabel(f"Residual ({unit})")
        acf_axis.set_title("Residual autocorrelation", loc="left")
        acf_axis.set_xlabel("Lag (years)")
        acf_axis.set_ylabel("Autocorrelation")
        hist_axis.set_title("Residual distribution", loc="left")
        hist_axis.set_xlabel(f"Residual ({unit})")
        hist_axis.set_ylabel("Frequency (observations)")
        qq_axis.set_title("Normal Q–Q assessment", loc="left")
        qq_axis.set_xlabel("Theoretical normal quantiles")
        qq_axis.set_ylabel(f"Observed residual quantiles ({unit})")
        figure.suptitle(f"{variable}: Residual Diagnostics ({result.get('convergence_status', 'model diagnostics')})")
        figures["Residual diagnostics"] = _finish(figure, list(axes.flat), [residual_axis])

        figure, axis = plt.subplots(figsize=(10, 5.6), dpi=120)
        holdout = result["holdout"]
        holdout_dates = pd.to_datetime(holdout["periods"]) if holdout.get("periods") else pd.DatetimeIndex([])
        if len(holdout_dates):
            training_mask = dates < holdout_dates[0]
            axis.plot(dates[training_mask], values[training_mask], color=colors["blue"], linewidth=1.8, label="Training observations")
            axis.plot(holdout_dates, holdout["actual"], color=colors["purple"], marker="o", markersize=4, linewidth=1.6, label="Holdout actual")
            axis.plot(holdout_dates, holdout["predicted"], color=colors["red"], marker="x", markersize=5, linestyle="--", linewidth=1.6, label="Holdout prediction")
            axis.axvline(holdout_dates[0], color=colors["gray"], linestyle=":", linewidth=1.2, label="Holdout begins")
        else:
            axis.plot(dates, values, color=colors["blue"], linewidth=1.8, label="Observed series")
        future_dates = pd.to_datetime(result.get("forecast_index", []))
        if len(future_dates):
            axis.plot(future_dates, result["forecast_values"], color=colors["green"], marker="o", markersize=4, linestyle="--", linewidth=2, label="Forecast")
            bands = result.get("forecast_intervals", {})
            if "95%" in bands:
                axis.fill_between(future_dates, bands["95%"]["lower"], bands["95%"]["upper"], color=colors["green"], alpha=0.11, label="95% prediction interval")
            if "80%" in bands:
                axis.fill_between(future_dates, bands["80%"]["lower"], bands["80%"]["upper"], color=colors["green"], alpha=0.24, label="80% prediction interval")
            if not bands:
                level = float(result.get("prediction_interval", {}).get("confidence_level", 0.95))
                axis.fill_between(future_dates, result["forecast_lower"], result["forecast_upper"], color=colors["green"], alpha=0.17, label=f"{level:.0%} prediction interval")
            axis.axvline(future_dates[0], color=colors["gray"], linestyle=":", linewidth=1.25, label="Forecast begins")
        axis.set_title(f"{variable}: Chronological Predictions and Forecast")
        axis.set_xlabel("Year")
        axis.set_ylabel(value_label)
        axis.legend(loc="best", frameon=True, framealpha=0.95, edgecolor="#D9DEE7", fontsize=8.5)
        figures["Forecasts"] = _finish(figure, [axis], [axis])

        comparison = result.get("model_comparison", {})
        errors = [(name, values.get("RMSE"), values.get("MAE")) for name, values in comparison.items()]
        errors = [row for row in errors if row[1] is not None and row[2] is not None]
        if errors:
            names = [row[0] for row in errors]
            positions = np.arange(len(names))
            figure, axis = plt.subplots(figsize=(10, max(4.8, 0.38 * len(names) + 1.5)), dpi=120)
            axis.barh(positions - 0.18, [row[1] for row in errors], height=0.34, color=colors["blue"], label="RMSE")
            axis.barh(positions + 0.18, [row[2] for row in errors], height=0.34, color=colors["orange"], label="MAE")
            axis.set_yticks(positions, labels=names)
            axis.invert_yaxis()
            axis.set_title(f"{variable}: Chronological Forecast Error by Model")
            axis.set_xlabel(f"Forecast error ({unit})")
            axis.set_ylabel("Candidate model")
            axis.legend(loc="best", frameon=False)
            figures["Model comparison"] = _finish(figure, [axis])
            axis.set_yticks(positions, labels=names)
            figure.tight_layout()

    return figures
