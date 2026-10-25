"""Validated utilities for common publication-planning and diagnostics tasks."""

import math

import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.stats.power import TTestIndPower


def independent_t_power(effect_size, alpha=0.05, power=0.80, ratio=1.0, alternative="two-sided"):
    """Return required group sizes for an independent-samples t-test."""
    if effect_size <= 0 or not 0 < alpha < 1 or not 0 < power < 1 or ratio <= 0:
        raise ValueError("effect_size, alpha, power, and ratio must be valid positive values.")
    if alternative not in {"two-sided", "larger", "smaller"}:
        raise ValueError("alternative must be two-sided, larger, or smaller.")
    n1 = TTestIndPower().solve_power(
        effect_size=float(effect_size), alpha=float(alpha), power=float(power),
        ratio=float(ratio), alternative=alternative,
    )
    return {
        "effect_size": float(effect_size), "alpha": float(alpha), "power": float(power),
        "ratio": float(ratio), "alternative": alternative,
        "group_1_n": int(math.ceil(n1)), "group_2_n": int(math.ceil(n1 * ratio)),
    }


def missing_data_sensitivity(dataframe, variables):
    """Describe complete-case loss without pretending to impute missing data."""
    if not isinstance(dataframe, pd.DataFrame) or not variables:
        raise ValueError("A dataframe and at least one variable are required.")
    missing = {name: int(dataframe[name].isna().sum()) for name in variables}
    complete = int(dataframe[list(variables)].dropna().shape[0])
    total = int(len(dataframe))
    return {
        "rows": total,
        "complete_cases": complete,
        "complete_case_percent": (100 * complete / total) if total else 0.0,
        "missing_by_variable": missing,
        "analysis_warning": complete < total,
        "interpretation": (
            "Complete-case results may be biased if missingness is related to the outcome or predictors."
            if complete < total else "No missing values were detected in the selected variables."
        ),
    }


def robust_regression_diagnostics(dataframe, predictor, outcome):
    """Fit OLS and expose HC3 inference plus influence diagnostics."""
    frame = dataframe[[predictor, outcome]].apply(pd.to_numeric, errors="coerce").dropna()
    if len(frame) < 3 or frame[predictor].nunique() < 2:
        raise ValueError("At least three complete rows and a non-constant predictor are required.")
    x = np.column_stack([np.ones(len(frame)), frame[predictor].to_numpy()])
    model = stats.linregress(frame[predictor], frame[outcome])
    from statsmodels.api import OLS
    fitted = OLS(frame[outcome], x).fit(cov_type="HC3")
    influence = fitted.get_influence()
    return {
        "n": int(len(frame)), "intercept": float(model.intercept), "slope": float(model.slope),
        "robust_slope_se": float(fitted.bse.iloc[1]), "robust_slope_t": float(fitted.tvalues.iloc[1]),
        "robust_slope_p": float(fitted.pvalues.iloc[1]), "r_squared": float(fitted.rsquared),
        "max_cooks_distance": float(np.max(influence.cooks_distance[0])),
        "max_leverage": float(np.max(influence.hat_matrix_diag)),
        "covariance": "HC3 heteroscedasticity-consistent standard errors",
    }


def exact_2x2_test(dataframe, first, second):
    """Fisher's exact test for a 2x2 categorical table."""
    table = pd.crosstab(dataframe[first], dataframe[second])
    if table.shape != (2, 2):
        raise ValueError("Fisher's exact test currently requires exactly a 2x2 table.")
    odds_ratio, p_value = stats.fisher_exact(table.to_numpy())
    return {"test": "fisher_exact_2x2", "table": table.to_dict(), "odds_ratio": float(odds_ratio), "p_value": float(p_value)}


def cronbach_alpha(dataframe, items, min_valid_items=None):
    """Calculate internal consistency and report item-level missingness."""
    if not items:
        raise ValueError("At least two questionnaire items are required.")
    if len(items) < 2:
        raise ValueError("Cronbach's alpha requires at least two items.")
    frame = dataframe[list(items)].apply(pd.to_numeric, errors="coerce")
    threshold = min_valid_items if min_valid_items is not None else len(items)
    valid = frame.notna().sum(axis=1) >= int(threshold)
    complete = frame.loc[valid].dropna()
    if len(complete) < 2:
        raise ValueError("At least two complete respondents are required.")
    variances = complete.var(axis=0, ddof=1)
    total_variance = complete.sum(axis=1).var(ddof=1)
    if total_variance == 0:
        raise ValueError("Total scale variance is zero; reliability is undefined.")
    alpha = len(items) / (len(items) - 1) * (1 - variances.sum() / total_variance)
    return {
        "items": list(items), "n": int(len(complete)), "alpha": float(alpha),
        "missing_by_item": {name: int(frame[name].isna().sum()) for name in items},
        "warning": "Alpha is an internal-consistency estimate, not proof of unidimensionality or validity.",
    }


def scale_score(dataframe, items, reverse_items=None, minimum=1, maximum=5, min_valid_items=None):
    """Score a questionnaire scale with explicit reverse-coded items and missing policy."""
    reverse_items = set(reverse_items or [])
    if not set(reverse_items).issubset(set(items)):
        raise ValueError("Every reverse-coded item must be included in items.")
    frame = dataframe[list(items)].apply(pd.to_numeric, errors="coerce")
    for item in reverse_items:
        frame[item] = maximum + minimum - frame[item]
    threshold = int(min_valid_items if min_valid_items is not None else len(items))
    valid_count = frame.notna().sum(axis=1)
    scores = frame.sum(axis=1, min_count=threshold).where(valid_count >= threshold)
    return {"scores": scores, "items": list(items), "reverse_items": sorted(reverse_items), "minimum": minimum, "maximum": maximum, "min_valid_items": threshold}


def cohens_kappa(coder_a, coder_b):
    """Calculate Cohen's kappa for two equal-length categorical coding lists."""
    if len(coder_a) != len(coder_b) or not coder_a:
        raise ValueError("Two non-empty coding lists of equal length are required.")
    labels = sorted(set(coder_a) | set(coder_b), key=str)
    observed = sum(a == b for a, b in zip(coder_a, coder_b)) / len(coder_a)
    expected = sum(
        (sum(a == label for a in coder_a) / len(coder_a))
        * (sum(b == label for b in coder_b) / len(coder_b))
        for label in labels
    )
    if expected == 1:
        return 1.0
    return float((observed - expected) / (1 - expected))
