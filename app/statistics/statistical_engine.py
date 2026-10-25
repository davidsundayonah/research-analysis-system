from dataclasses import dataclass
import math

import pandas as pd
import numpy as np
from pandas.api.types import is_bool_dtype, is_datetime64_any_dtype
from scipy import stats
from scipy.special import gammaln
from statsmodels.api import OLS, add_constant
from statsmodels.stats.diagnostic import het_breuschpagan
from statsmodels.stats.stattools import durbin_watson
from statsmodels.stats.multicomp import pairwise_tukeyhsd

from app.statistics.statistical_result import StatisticalError, StatisticalResult


@dataclass
class PreparedStatisticalInput:
    data: pd.DataFrame
    result: StatisticalResult


class StatisticalEngine:
    MISSING_POLICIES = {"listwise", "raise"}

    def __init__(self, dataframe):
        if not isinstance(dataframe, pd.DataFrame):
            raise TypeError("dataframe must be a pandas DataFrame.")
        self.dataframe = dataframe.copy()

    def prepare_numeric_data(self, variables, missing_policy="listwise"):
        if not isinstance(variables, (list, tuple)) or not variables:
            return self._invalid_input(
                variables,
                "INVALID_VARIABLES",
                "variables must be a non-empty list or tuple.",
            )

        variable_names = list(variables)
        if any(not isinstance(name, str) or not name.strip() for name in variable_names):
            return self._invalid_input(
                variable_names,
                "INVALID_VARIABLES",
                "variable names must be non-empty strings.",
            )
        if len(set(variable_names)) != len(variable_names):
            return self._invalid_input(
                variable_names,
                "DUPLICATE_VARIABLES",
                "each variable may only be selected once.",
            )

        if (
            not isinstance(missing_policy, str)
            or missing_policy not in self.MISSING_POLICIES
        ):
            return self._invalid_input(
                variable_names,
                "INVALID_MISSING_POLICY",
                "missing_policy must be 'listwise' or 'raise'.",
                {"provided": missing_policy},
            )

        duplicate_columns = [
            name
            for name in variable_names
            if list(self.dataframe.columns).count(name) > 1
        ]
        if duplicate_columns:
            return self._invalid_input(
                variable_names,
                "AMBIGUOUS_COLUMNS",
                "selected column names must be unique in the dataset.",
                {"columns": duplicate_columns},
            )

        missing_variables = [
            name for name in variable_names if name not in self.dataframe.columns
        ]
        if missing_variables:
            return self._invalid_input(
                variable_names,
                "VARIABLE_NOT_FOUND",
                "one or more selected variables do not exist.",
                {"variables": missing_variables},
            )

        converted_columns = {}
        source_missing = {}
        conversion_missing = {}
        for name in variable_names:
            source = self.dataframe[name]
            if is_bool_dtype(source) or is_datetime64_any_dtype(source):
                return self._invalid_input(
                    variable_names,
                    "NON_NUMERIC_VARIABLE",
                    f"'{name}' is boolean or datetime data, not a numeric measure.",
                    {"variable": name, "dtype": str(source.dtype)},
                )

            converted = pd.to_numeric(source, errors="coerce")
            if source.notna().any() and converted.notna().sum() == 0:
                return self._invalid_input(
                    variable_names,
                    "NON_NUMERIC_VARIABLE",
                    f"'{name}' contains no values that can be interpreted as numbers.",
                    {"variable": name, "dtype": str(source.dtype)},
                )
            if converted.map(
                lambda value: (
                    not pd.isna(value)
                    and not math.isfinite(float(value))
                )
            ).any():
                return self._invalid_input(
                    variable_names,
                    "NON_FINITE_VALUES",
                    f"'{name}' contains infinite numeric values.",
                    {"variable": name},
                )
            source_missing[name] = int(source.isna().sum())
            conversion_missing[name] = int(
                (source.notna() & converted.isna()).sum()
            )
            converted_columns[name] = converted

        prepared = pd.DataFrame(converted_columns, index=self.dataframe.index)
        missing_counts = {
            name: source_missing[name] + conversion_missing[name]
            for name in variable_names
        }
        if missing_policy == "raise" and any(missing_counts.values()):
            return self._invalid_input(
                variable_names,
                "MISSING_DATA",
                "selected variables contain missing or non-numeric values.",
                {"missing_data": missing_counts},
                sample_size=int(len(prepared)),
                missing_data=missing_counts,
            )

        complete = prepared.dropna(axis=0, how="any")
        dropped_rows = int(len(prepared) - len(complete))
        if dropped_rows:
            warning = (
                f"{dropped_rows} row(s) omitted using listwise deletion."
            )
            warnings = [warning]
        else:
            warnings = []

        if complete.empty:
            return self._invalid_input(
                variable_names,
                "NO_COMPLETE_CASES",
                "no complete numeric observations remain after missing-data handling.",
                {"missing_data": missing_counts},
                sample_size=0,
                missing_data=missing_counts,
                warnings=warnings,
            )

        result = StatisticalResult(
            test="input_preparation",
            variables=variable_names,
            sample_size=int(len(complete)),
            missing_data=missing_counts,
            warnings=warnings,
            details={
                "missing_policy": missing_policy,
                "rows_received": int(len(prepared)),
                "rows_used": int(len(complete)),
                "rows_omitted": dropped_rows,
                "coerced_to_missing": conversion_missing,
            },
        )
        return PreparedStatisticalInput(complete, result)

    def independent_t_test(
        self,
        outcome,
        group,
        *,
        equal_var=False,
        confidence_level=0.95,
        alpha=0.05,
        missing_policy="listwise",
    ):
        test = "independent_t_test"
        validation = self._validate_inference_options(
            test, [outcome, group], confidence_level, alpha
        )
        if validation is not None:
            return validation
        if outcome == group:
            return self._failure(
                test, [outcome, group], "DUPLICATE_VARIABLES",
                "Outcome and grouping variables must be different.",
            )
        if group not in self.dataframe.columns:
            return self._failure(
                test, [outcome, group], "VARIABLE_NOT_FOUND",
                "Grouping variable does not exist.", {"variable": group},
            )

        prepared = self.prepare_numeric_data([outcome], missing_policy)
        if prepared.result.status != "ok":
            return self._adopt_preparation_error(test, [outcome, group], prepared)

        frame = pd.DataFrame({
            "outcome": prepared.data[outcome],
            "group": self.dataframe[group],
        }, index=prepared.data.index)
        source_missing = int(self.dataframe[group].isna().sum())
        if missing_policy == "raise" and source_missing:
            return self._failure(
                test, [outcome, group], "MISSING_DATA",
                "Grouping variable contains missing values.",
                {"missing_data": {group: source_missing}},
                sample_size=len(frame),
                missing_data={group: source_missing},
            )
        complete = frame.dropna()
        omitted = len(frame) - len(complete)
        labels = list(pd.unique(complete["group"]))
        if len(labels) != 2:
            return self._failure(
                test, [outcome, group], "INVALID_GROUP_COUNT",
                "Independent t-test requires exactly two non-missing groups.",
                {"groups": [str(label) for label in labels]},
                sample_size=len(complete),
            )
        first = complete.loc[complete["group"] == labels[0], "outcome"].to_numpy(
            dtype=float
        )
        second = complete.loc[complete["group"] == labels[1], "outcome"].to_numpy(
            dtype=float
        )
        if len(first) < 2 or len(second) < 2:
            return self._failure(
                test, [outcome, group], "INSUFFICIENT_GROUP_SIZE",
                "Each group must contain at least two observations.",
                {"group_sizes": [len(first), len(second)]},
                sample_size=len(complete),
            )
        if float(first.var(ddof=1)) == 0 and float(second.var(ddof=1)) == 0:
            return self._failure(
                test, [outcome, group], "ZERO_VARIANCE",
                "Both groups have zero variance; the t statistic is undefined.",
                sample_size=len(complete),
            )

        variance_first = float(first.var(ddof=1))
        variance_second = float(second.var(ddof=1))
        n_first, n_second = len(first), len(second)
        difference = float(first.mean() - second.mean())
        display_labels = self._display_group_labels(group, labels)
        if equal_var:
            degrees = n_first + n_second - 2
            pooled_variance = (
                (n_first - 1) * variance_first
                + (n_second - 1) * variance_second
            ) / degrees
            standard_error = (pooled_variance * (1 / n_first + 1 / n_second)) ** 0.5
            pooled_sd = pooled_variance ** 0.5
        else:
            term_first = variance_first / n_first
            term_second = variance_second / n_second
            standard_error = (term_first + term_second) ** 0.5
            denominator = (
                term_first**2 / (n_first - 1)
                + term_second**2 / (n_second - 1)
            )
            degrees = (term_first + term_second) ** 2 / denominator
            pooled_sd = (
                ((n_first - 1) * variance_first + (n_second - 1) * variance_second)
                / (n_first + n_second - 2)
            ) ** 0.5

        critical = stats.t.ppf((1 + confidence_level) / 2, degrees)
        test_statistic = difference / standard_error
        p_value = float(2 * stats.t.sf(abs(test_statistic), degrees))
        ci = (difference - critical * standard_error,
              difference + critical * standard_error)
        cohens_d = difference / pooled_sd if pooled_sd else None
        effect_degrees = n_first + n_second - 2
        correction = self._hedges_correction(effect_degrees)
        assumptions = [
            self._normality_assumption(first, f"{display_labels[0]} group", alpha),
            self._normality_assumption(second, f"{display_labels[1]} group", alpha),
            self._levene_assumption(first, second, alpha=alpha),
        ]
        warnings = list(prepared.result.warnings)
        if omitted:
            warnings.append(f"{omitted} row(s) omitted because the group was missing.")
        if equal_var and assumptions[-1]["passed"] is False:
            warnings.append("Equal-variance test indicated a departure from equal variances; consider Welch's t-test.")
        if equal_var and assumptions[-1]["passed"] is None:
            warnings.append("Equal-variance diagnostic was unavailable for a zero-variance group.")
        return StatisticalResult(
            test=test,
            variables=[outcome, group],
            sample_size=len(complete),
            statistic=float(test_statistic),
            degrees_of_freedom=float(degrees),
            p_value=p_value,
            effect_size={
                "cohens_d": float(cohens_d) if cohens_d is not None else None,
                "hedges_g": float(cohens_d * correction) if cohens_d is not None else None,
            },
            confidence_interval=tuple(float(value) for value in ci),
            assumptions=assumptions,
            decision=self._decision(p_value, alpha),
            interpretation=(
                f"Mean difference ({display_labels[0]} - {display_labels[1]}) is {difference:.6g}."
            ),
            missing_data={
                outcome: prepared.result.missing_data.get(outcome, 0),
                group: source_missing,
            },
            warnings=warnings,
            details={
                "group_order": display_labels,
                "group_sizes": [n_first, n_second],
                "group_means": [float(first.mean()), float(second.mean())],
                "group_standard_deviations": [
                    float(first.std(ddof=1)),
                    float(second.std(ddof=1)),
                ],
                "equal_variance_assumed": bool(equal_var),
                "test_method": "student" if equal_var else "welch",
                "effect_size_convention": "Cohen's d uses the pooled within-group standard deviation.",
                "hedges_correction": "J(df) applied using pooled within-group degrees of freedom.",
                "effect_size_degrees_of_freedom": effect_degrees,
                "missing_policy": missing_policy,
                "rows_omitted_for_missing_group": omitted,
                "confidence_level": confidence_level,
                "alpha": alpha,
            },
        )

    def paired_t_test(
        self,
        first,
        second,
        *,
        confidence_level=0.95,
        alpha=0.05,
        missing_policy="listwise",
    ):
        test = "paired_t_test"
        validation = self._validate_inference_options(
            test, [first, second], confidence_level, alpha
        )
        if validation is not None:
            return validation
        if first == second:
            return self._failure(
                test, [first, second], "DUPLICATE_VARIABLES",
                "Paired variables must be different columns.",
            )
        prepared = self.prepare_numeric_data([first, second], missing_policy)
        if prepared.result.status != "ok":
            return self._adopt_preparation_error(test, [first, second], prepared)

        left = prepared.data[first].to_numpy(dtype=float)
        right = prepared.data[second].to_numpy(dtype=float)
        differences = left - right
        n = len(differences)
        if n < 2:
            return self._failure(
                test, [first, second], "INSUFFICIENT_SAMPLE_SIZE",
                "Paired t-test requires at least two complete pairs.",
                sample_size=n,
            )
        sd = float(differences.std(ddof=1))
        if sd == 0:
            return self._failure(
                test, [first, second], "ZERO_VARIANCE_DIFFERENCES",
                "Paired differences have zero variance; the t statistic is undefined.",
                sample_size=n,
            )

        test_result = stats.ttest_rel(left, right)
        degrees = n - 1
        mean_difference = float(differences.mean())
        standard_error = sd / n**0.5
        critical = stats.t.ppf((1 + confidence_level) / 2, degrees)
        ci = (
            mean_difference - critical * standard_error,
            mean_difference + critical * standard_error,
        )
        assumption = self._normality_assumption(differences, "paired differences", alpha)
        warnings = list(prepared.result.warnings)
        if assumption["passed"] is False:
            warnings.append("Normality test for paired differences indicated a departure from normality.")
        elif assumption["passed"] is None:
            warnings.append("Normality of paired differences could not be evaluated.")
        return StatisticalResult(
            test=test,
            variables=[first, second],
            sample_size=n,
            statistic=float(test_result.statistic),
            degrees_of_freedom=float(degrees),
            p_value=float(test_result.pvalue),
            effect_size={
                "cohens_dz": mean_difference / sd,
                "hedges_gz": mean_difference / sd * self._hedges_correction(degrees),
            },
            confidence_interval=tuple(float(value) for value in ci),
            assumptions=[assumption],
            decision=self._decision(float(test_result.pvalue), alpha),
            interpretation=f"Mean paired difference ({first} - {second}) is {mean_difference:.6g}.",
            missing_data=prepared.result.missing_data.copy(),
            warnings=warnings,
            details={
                "mean_difference": mean_difference,
                "standard_deviation_of_differences": sd,
                "effect_size_convention": "Cohen's dz is mean paired difference divided by the SD of paired differences.",
                "hedges_correction": "J(n - 1) applied to dz.",
                "test_method": "paired Student t-test, two-sided",
                "missing_policy": missing_policy,
                "rows_omitted": prepared.result.details.get("rows_omitted", 0),
                "confidence_level": confidence_level,
                "alpha": alpha,
            },
        )

    def one_way_anova(
        self,
        outcome,
        group,
        *,
        confidence_level=0.95,
        alpha=0.05,
        missing_policy="listwise",
    ):
        test = "one_way_anova"
        validation = self._validate_inference_options(
            test, [outcome, group], confidence_level, alpha
        )
        if validation is not None:
            return validation
        if outcome == group:
            return self._failure(
                test, [outcome, group], "DUPLICATE_VARIABLES",
                "Outcome and grouping variables must be different.",
            )
        if group not in self.dataframe.columns:
            return self._failure(
                test, [outcome, group], "VARIABLE_NOT_FOUND",
                "Grouping variable does not exist.", {"variable": group},
            )
        prepared = self.prepare_numeric_data([outcome], missing_policy)
        if prepared.result.status != "ok":
            return self._adopt_preparation_error(test, [outcome, group], prepared)

        group_missing = int(self.dataframe[group].isna().sum())
        if missing_policy == "raise" and group_missing:
            return self._failure(
                test, [outcome, group], "MISSING_DATA",
                "Grouping variable contains missing values.",
                {"missing_data": {group: group_missing}},
                sample_size=len(prepared.data),
                missing_data={group: group_missing},
            )
        frame = pd.DataFrame({
            "outcome": prepared.data[outcome],
            "group": self.dataframe[group],
        }, index=prepared.data.index).dropna()
        labels = list(pd.unique(frame["group"]))
        groups = [
            frame.loc[frame["group"] == label, "outcome"].to_numpy(dtype=float)
            for label in labels
        ]
        if len(groups) < 2:
            return self._failure(
                test, [outcome, group], "INSUFFICIENT_GROUPS",
                "One-way ANOVA requires at least two groups.",
                sample_size=len(frame),
            )
        if any(len(values) < 2 for values in groups):
            return self._failure(
                test, [outcome, group], "INSUFFICIENT_GROUP_SIZE",
                "Each ANOVA group must contain at least two observations.",
                {"group_sizes": [len(values) for values in groups]},
                sample_size=len(frame),
            )
        if all(float(values.var(ddof=1)) == 0 for values in groups):
            return self._failure(
                test, [outcome, group], "ZERO_WITHIN_GROUP_VARIANCE",
                "All groups have zero within-group variance.", sample_size=len(frame),
            )

        result = stats.f_oneway(*groups)
        sizes = [len(values) for values in groups]
        means = [float(values.mean()) for values in groups]
        overall_mean = float(frame["outcome"].mean())
        ss_between = sum(
            size * (mean - overall_mean) ** 2
            for size, mean in zip(sizes, means)
        )
        ss_within = sum(
            float(((values - values.mean()) ** 2).sum())
            for values in groups
        )
        ss_total = ss_between + ss_within
        df_between = len(groups) - 1
        df_within = len(frame) - len(groups)
        df_total = len(frame) - 1
        mean_square_between = ss_between / df_between
        mean_square_within = ss_within / df_within
        eta_squared = ss_between / ss_total if ss_total else None
        ms_within = mean_square_within
        raw_omega_squared = (
            (ss_between - df_between * ms_within)
            / (ss_total + ms_within)
            if ss_total + ms_within > 0 else None
        )
        omega_squared = (
            max(0.0, raw_omega_squared)
            if raw_omega_squared is not None else None
        )
        variance_assumption = self._levene_assumption(*groups, alpha=alpha)
        residuals = frame["outcome"].to_numpy(dtype=float) - frame.groupby(
            "group", sort=False
        )["outcome"].transform("mean").to_numpy(dtype=float)
        normality = self._normality_assumption(
            residuals,
            "within-group residuals",
            alpha,
        )
        warnings = list(prepared.result.warnings)
        post_hoc = None
        if len(groups) > 2:
            try:
                tukey = pairwise_tukeyhsd(
                    frame["outcome"].to_numpy(dtype=float),
                    frame["group"].astype(str).to_numpy(),
                )
                post_hoc = [
                    {
                        "group_a": str(row[0]),
                        "group_b": str(row[1]),
                        "mean_difference": float(row[2]),
                        "p_adjusted": float(row[3]),
                        "lower": float(row[4]),
                        "upper": float(row[5]),
                        "reject": bool(row[6]),
                        "method": "Tukey HSD",
                    }
                    for row in tukey._results_table.data[1:]
                ]
                warnings.append(
                    "Tukey HSD follow-up comparisons use family-wise error control."
                )
            except (TypeError, ValueError, IndexError):
                warnings.append("Post-hoc comparisons could not be computed.")
        if variance_assumption["passed"] is False:
            warnings.append("Equal-variance test indicated a departure from equal variances.")
        elif variance_assumption["passed"] is None:
            warnings.append("Equal-variance test could not be evaluated.")
        if normality["passed"] is False:
            warnings.append("Within-group residual normality test indicated a departure from normality.")
        elif normality["passed"] is None:
            warnings.append("Within-group residual normality could not be evaluated.")
        return StatisticalResult(
            test=test,
            variables=[outcome, group],
            sample_size=len(frame),
            statistic=float(result.statistic),
            degrees_of_freedom=float(df_within),
            p_value=float(result.pvalue),
            effect_size={
                "eta_squared": float(eta_squared) if eta_squared is not None else None,
                "omega_squared": float(omega_squared) if omega_squared is not None else None,
            },
            assumptions=[normality, variance_assumption],
            decision=self._decision(float(result.pvalue), alpha),
            interpretation=f"At least one group mean differs: {self._decision(float(result.pvalue), alpha)}.",
            missing_data={
                outcome: prepared.result.missing_data.get(outcome, 0),
                group: int(self.dataframe[group].isna().sum()),
            },
            warnings=warnings,
            details={
                "group_order": [str(label) for label in labels],
                "group_sizes": sizes,
                "group_means": means,
                "degrees_of_freedom_between": df_between,
                "degrees_of_freedom_within": df_within,
                "sum_squares_between": ss_between,
                "sum_squares_within": ss_within,
                "sum_squares_total": ss_total,
                "degrees_of_freedom_total": df_total,
                "mean_square_between": mean_square_between,
                "mean_square_within": mean_square_within,
                "omega_squared_convention": "Unbiased estimate truncated at zero when sampling noise makes it negative.",
                "test_method": "classical one-way fixed-effects ANOVA",
                "confidence_interval_method": None,
                "confidence_interval_note": "An omnibus ANOVA interval is not defined; follow-up contrasts require a post-hoc method.",
                "post_hoc": post_hoc,
                "missing_policy": missing_policy,
                "rows_omitted": int(len(self.dataframe) - len(frame)),
                "confidence_level": confidence_level,
                "alpha": alpha,
            },
        )

    def chi_square_test(
        self,
        first,
        second,
        *,
        correction=True,
        alpha=0.05,
        missing_policy="listwise",
    ):
        test = "chi_square_test"
        validation = self._validate_inference_options(
            test, [first, second], 0.95, alpha
        )
        if validation is not None:
            return validation
        if first == second:
            return self._failure(
                test, [first, second], "DUPLICATE_VARIABLES",
                "Chi-square variables must be different columns.",
            )
        if (
            not isinstance(missing_policy, str)
            or missing_policy not in self.MISSING_POLICIES
        ):
            return self._failure(
                test, [first, second], "INVALID_MISSING_POLICY",
                "missing_policy must be 'listwise' or 'raise'.",
            )
        missing = [
            variable for variable in (first, second)
            if variable not in self.dataframe.columns
        ]
        if missing:
            return self._failure(
                test, [first, second], "VARIABLE_NOT_FOUND",
                "One or more categorical variables do not exist.",
                {"variables": missing},
            )
        frame = self.dataframe[[first, second]]
        missing_counts = {name: int(frame[name].isna().sum()) for name in (first, second)}
        if missing_policy == "raise" and any(missing_counts.values()):
            return self._failure(
                test, [first, second], "MISSING_DATA",
                "selected categorical variables contain missing values.",
                {"missing_data": missing_counts},
                sample_size=len(frame),
                missing_data=missing_counts,
            )
        complete = frame.dropna()
        table = pd.crosstab(complete[first], complete[second], dropna=False)
        if table.shape[0] < 2 or table.shape[1] < 2:
            return self._failure(
                test, [first, second], "INSUFFICIENT_CATEGORIES",
                "Chi-square test requires at least two observed categories per variable.",
                {"table_shape": list(table.shape)},
                sample_size=len(complete), missing_data=missing_counts,
            )
        observed = table.to_numpy(dtype=float)
        if observed.sum() == 0:
            return self._failure(
                test, [first, second], "NO_OBSERVATIONS",
                "No complete categorical observations are available.",
                sample_size=0, missing_data=missing_counts,
            )
        statistic, p_value, degrees, expected = stats.chi2_contingency(
            observed,
            correction=bool(correction) and observed.shape == (2, 2),
        )
        if (expected <= 0).any() or not np.isfinite(expected).all():
            return self._failure(
                test, [first, second], "INVALID_EXPECTED_COUNTS",
                "The contingency table produces zero or non-finite expected counts; chi-square is undefined.",
                {"expected": expected.tolist()},
                sample_size=int(observed.sum()),
                missing_data=missing_counts,
            )
        n = int(observed.sum())
        minimum_dimension = min(observed.shape)
        cramers_v = (statistic / (n * (minimum_dimension - 1))) ** 0.5
        assumptions = [{
            "name": "expected_cell_counts",
            "statistic": None,
            "p_value": None,
            "passed": bool((expected >= 5).all()),
            "details": {
                "cells_below_five": int((expected < 5).sum()),
                "minimum_expected": float(expected.min()),
            },
        }]
        warnings = []
        dropped = len(frame) - len(complete)
        if dropped:
            warnings.append(f"{dropped} row(s) omitted using listwise deletion.")
        if not assumptions[0]["passed"]:
            warnings.append(
                "Some expected cell counts are below 5; consider an exact test or combining categories."
            )
        exact_p_value = None
        if observed.shape == (2, 2) and not assumptions[0]["passed"]:
            _, exact_p_value = stats.fisher_exact(observed)
            exact_p_value = float(exact_p_value)
            warnings.append(
                "Fisher's exact p-value is provided because expected counts are small; use it for the primary decision."
            )
        return StatisticalResult(
            test=test,
            variables=[first, second],
            sample_size=n,
            statistic=float(statistic),
            degrees_of_freedom=float(degrees),
            p_value=float(p_value),
            effect_size={"cramers_v": float(cramers_v)},
            assumptions=assumptions,
            decision=self._decision(float(p_value), alpha),
            interpretation=f"Categorical association test: {self._decision(float(p_value), alpha)}.",
            missing_data=missing_counts,
            warnings=warnings,
            details={
                "observed": observed.astype(int).tolist(),
                "expected": expected.tolist(),
                "row_categories": [str(value) for value in table.index],
                "column_categories": [str(value) for value in table.columns],
                "continuity_correction": bool(correction) and observed.shape == (2, 2),
                "test_method": "Pearson chi-square",
                "effect_size_convention": "Cramer's V = sqrt(chi-square / (n * (min(rows, columns) - 1))).",
                "zero_margins": "Unobserved categories are excluded from the contingency table.",
                "confidence_interval_method": None,
                "confidence_interval_note": "The omnibus chi-square test does not provide a single confidence interval.",
                "fisher_exact_p_value": exact_p_value,
                "multiplicity": "Not applicable to this single omnibus test.",
                "missing_policy": missing_policy,
                "alpha": alpha,
            },
        )

    def correlation(
        self,
        first,
        second,
        *,
        method="pearson",
        confidence_level=0.95,
        alpha=0.05,
        missing_policy="listwise",
    ):
        test = f"{str(method).lower()}_correlation"
        validation = self._validate_inference_options(
            test, [first, second], confidence_level, alpha
        )
        if validation is not None:
            return validation
        method = str(method).lower()
        if method not in {"pearson", "spearman"}:
            return self._failure(
                test, [first, second], "INVALID_CORRELATION_METHOD",
                "method must be 'pearson' or 'spearman'.",
            )
        if first == second:
            return self._failure(
                test, [first, second], "DUPLICATE_VARIABLES",
                "Correlation requires two different variables.",
            )
        prepared = self.prepare_numeric_data([first, second], missing_policy)
        if prepared.result.status != "ok":
            return self._adopt_preparation_error(test, [first, second], prepared)
        left = prepared.data[first].to_numpy(dtype=float)
        right = prepared.data[second].to_numpy(dtype=float)
        n = len(left)
        if n < 3:
            return self._failure(
                test, [first, second], "INSUFFICIENT_SAMPLE_SIZE",
                "Correlation requires at least three complete pairs.", sample_size=n,
            )
        if left.std() == 0 or right.std() == 0:
            return self._failure(
                test, [first, second], "CONSTANT_VARIABLE",
                "Correlation is undefined when either variable is constant.", sample_size=n,
            )

        if method == "pearson":
            test_result = stats.pearsonr(left, right)
            coefficient = float(test_result.statistic)
            p_value = float(test_result.pvalue)
            standard_error = ((1 - coefficient**2) / (n - 2)) ** 0.5
            degrees = n - 2
            if n > 3 and abs(coefficient) < 1:
                z = float(stats.norm.ppf((1 + confidence_level) / 2))
                fisher = math.atanh(coefficient)
                margin = z / ((n - 3) ** 0.5)
                ci = (math.tanh(fisher - margin), math.tanh(fisher + margin))
            elif abs(coefficient) == 1:
                ci = None
            else:
                ci = None
            assumptions = [
                self._normality_assumption(left, first, alpha),
                self._normality_assumption(right, second, alpha),
            ]
            warnings = list(prepared.result.warnings)
            if abs(coefficient) == 1:
                warnings.append(
                    "Pearson confidence interval is unavailable for a perfect correlation."
                )
            elif ci is None:
                warnings.append(
                    "Pearson confidence interval is unavailable with fewer than four observations."
                )
            failed = [item["details"].get("sample", "variable") for item in assumptions if item["passed"] is False]
            unavailable = [item["details"].get("sample", "variable") for item in assumptions if item["passed"] is None]
            if failed:
                warnings.append("Pearson normality tests indicated a departure from normality for: " + ", ".join(failed) + ".")
            if unavailable:
                warnings.append("Pearson normality tests could not be evaluated for: " + ", ".join(unavailable) + ".")
        else:
            test_result = stats.spearmanr(left, right)
            coefficient = float(test_result.statistic)
            p_value = float(test_result.pvalue)
            degrees = n - 2
            standard_error = None
            ci = None
            assumptions = [{
                "name": "monotonic_relationship",
                "statistic": None,
                "p_value": None,
                "passed": None,
                "details": {"evaluated": False},
            }]
            warnings = list(prepared.result.warnings)
            warnings.append(
                "Spearman confidence interval is not provided; monotonicity requires visual review."
            )
        return StatisticalResult(
            test=test,
            variables=[first, second],
            sample_size=n,
            statistic=coefficient,
            degrees_of_freedom=float(degrees),
            p_value=p_value,
            effect_size={"correlation": coefficient},
            confidence_interval=ci,
            assumptions=assumptions,
            decision=self._decision(p_value, alpha),
            interpretation=f"{method.title()} correlation is {coefficient:.6g}.",
            missing_data=prepared.result.missing_data.copy(),
            warnings=warnings,
            details={
                "method": method,
                "p_value_method": "two-sided t approximation" if method == "spearman" else "Pearson product-moment test",
                "confidence_interval_method": "Fisher z" if method == "pearson" and ci is not None else None,
                "confidence_interval_note": (
                    None if ci is not None else (
                        "Spearman interval not implemented."
                        if method == "spearman"
                        else "Pearson Fisher-z interval unavailable for this sample/result."
                    )
                ),
                "missing_policy": missing_policy,
                "rows_omitted": prepared.result.details.get("rows_omitted", 0),
                "standard_error": float(standard_error) if standard_error is not None else None,
                "confidence_level": confidence_level,
                "alpha": alpha,
            },
        )

    def linear_regression(
        self,
        predictor,
        outcome,
        *,
        confidence_level=0.95,
        alpha=0.05,
        missing_policy="listwise",
    ):
        test = "linear_regression"
        validation = self._validate_inference_options(
            test, [predictor, outcome], confidence_level, alpha
        )
        if validation is not None:
            return validation
        if predictor == outcome:
            return self._failure(
                test, [predictor, outcome], "DUPLICATE_VARIABLES",
                "Predictor and outcome must be different variables.",
            )
        prepared = self.prepare_numeric_data([predictor, outcome], missing_policy)
        if prepared.result.status != "ok":
            return self._adopt_preparation_error(test, [predictor, outcome], prepared)
        x = prepared.data[predictor].to_numpy(dtype=float)
        y = prepared.data[outcome].to_numpy(dtype=float)
        n = len(x)
        if n < 3:
            return self._failure(
                test, [predictor, outcome], "INSUFFICIENT_SAMPLE_SIZE",
                "Linear regression requires at least three complete observations.",
                sample_size=n,
            )
        if x.std() == 0:
            return self._failure(
                test, [predictor, outcome], "CONSTANT_PREDICTOR",
                "Linear regression requires a non-constant predictor.", sample_size=n,
            )
        if y.std() == 0:
            return self._failure(
                test, [predictor, outcome], "CONSTANT_OUTCOME",
                "Linear regression is not informative for a constant outcome.", sample_size=n,
            )

        try:
            model = OLS(y, add_constant(x, has_constant="add")).fit()
        except (ValueError, np.linalg.LinAlgError) as error:
            return self._failure(
                test, [predictor, outcome], "SINGULAR_DESIGN",
                "The regression design matrix is singular.",
                {"reason": str(error)}, sample_size=n,
            )
        confidence = model.conf_int(alpha=1 - confidence_level)
        slope_ci = tuple(float(value) for value in confidence[1])
        residuals = model.resid
        if model.df_resid < 3:
            normality = {
                "name": "normality",
                "statistic": None,
                "p_value": None,
                "passed": None,
                "details": {
                    "sample": "regression residuals",
                    "evaluated": False,
                    "reason": "fewer than 3 residual degrees of freedom",
                },
            }
        else:
            normality = self._normality_assumption(
                residuals,
                "regression residuals",
                alpha,
            )
        assumptions = [normality]
        warnings = list(prepared.result.warnings)
        if normality["passed"] is False:
            warnings.append("Regression residual normality test indicated a departure from normality.")
        elif normality["passed"] is None:
            warnings.append("Regression residual normality could not be evaluated.")

        if n >= 8:
            try:
                bp_lm, bp_p, _, _ = het_breuschpagan(residuals, model.model.exog)
                homoscedasticity = {
                    "name": "constant_variance",
                    "statistic": float(bp_lm),
                    "p_value": float(bp_p),
                    "passed": bool(bp_p >= alpha),
                    "details": {"method": "Breusch-Pagan"},
                }
                assumptions.append(homoscedasticity)
                if not homoscedasticity["passed"]:
                    warnings.append("Breusch-Pagan test suggests heteroscedasticity.")
            except (ValueError, ZeroDivisionError):
                warnings.append("Homoscedasticity diagnostic could not be computed.")
        else:
            assumptions.append({
                "name": "constant_variance",
                "statistic": None,
                "p_value": None,
                "passed": None,
                "details": {
                    "evaluated": False,
                    "reason": "Breusch-Pagan diagnostic requires at least 8 observations.",
                },
            })

        dw_statistic = float(durbin_watson(residuals))
        autocorrelation_passed = 1.5 <= dw_statistic <= 2.5
        assumptions.append({
            "name": "residual_autocorrelation",
            "statistic": dw_statistic,
            "p_value": None,
            "passed": autocorrelation_passed,
            "details": {
                "method": "Durbin-Watson heuristic",
                "reference_value": 2.0,
                "screening_range": [1.5, 2.5],
            },
        })
        if not autocorrelation_passed:
            warnings.append(
                "Durbin-Watson screening suggests residual autocorrelation; this is a heuristic, not a formal p-value test."
            )

        slope = float(model.params[1])
        intercept = float(model.params[0])
        p_value = float(model.f_pvalue)
        return StatisticalResult(
            test=test,
            variables=[predictor, outcome],
            sample_size=n,
            statistic=float(model.fvalue),
            degrees_of_freedom=float(model.df_resid),
            p_value=p_value,
            effect_size={"r_squared": float(model.rsquared), "adjusted_r_squared": float(model.rsquared_adj)},
            confidence_interval=slope_ci,
            assumptions=assumptions,
            decision=self._decision(p_value, alpha),
            interpretation=(
                f"Estimated outcome change is {slope:.6g} per one-unit increase in {predictor}."
            ),
            missing_data=prepared.result.missing_data.copy(),
            warnings=warnings,
            details={
                "intercept": intercept,
                "slope": slope,
                "intercept_confidence_interval": [float(value) for value in confidence[0]],
                "intercept_standard_error": float(model.bse[0]),
                "intercept_test_statistic": float(model.tvalues[0]),
                "intercept_p_value": float(model.pvalues[0]),
                "slope_standard_error": float(model.bse[1]),
                "slope_test_statistic": float(model.tvalues[1]),
                "slope_p_value": float(model.pvalues[1]),
                "f_statistic": float(model.fvalue),
                "f_degrees_of_freedom": [float(model.df_model), float(model.df_resid)],
                "residual_standard_error": float((model.ssr / model.df_resid) ** 0.5),
                "durbin_watson": dw_statistic,
                "test_method": "ordinary least squares, one predictor, two-sided tests",
                "confidence_interval_method": "OLS t interval",
                "missing_policy": missing_policy,
                "rows_omitted": prepared.result.details.get("rows_omitted", 0),
                "diagnostic_limitations": {
                    "normality": normality["details"].get("reason") if not normality["details"].get("evaluated", True) else None,
                    "autocorrelation": "Durbin-Watson is reported as a screening heuristic without a p-value.",
                },
                "confidence_level": confidence_level,
                "alpha": alpha,
            },
        )

    @staticmethod
    def _validate_inference_options(test, variables, confidence_level, alpha):
        if not isinstance(variables, (list, tuple)) or len(variables) != 2:
            return StatisticalEngine._failure(
                test, [], "INVALID_VARIABLES",
                "This procedure requires exactly two variable names.",
            )
        if any(not isinstance(name, str) or not name.strip() for name in variables):
            safe_variables = [
                name for name in variables if isinstance(name, str) and name.strip()
            ]
            return StatisticalEngine._failure(
                test, safe_variables, "INVALID_VARIABLES",
                "variable names must be non-empty strings.",
            )
        if not isinstance(confidence_level, (int, float)) or not 0 < confidence_level < 1:
            return StatisticalEngine._failure(
                test, variables, "INVALID_CONFIDENCE_LEVEL",
                "confidence_level must be between 0 and 1, exclusive.",
            )
        if not isinstance(alpha, (int, float)) or not 0 < alpha < 1:
            return StatisticalEngine._failure(
                test, variables, "INVALID_ALPHA",
                "alpha must be between 0 and 1, exclusive.",
            )
        return None

    @staticmethod
    def _failure(
        test,
        variables,
        code,
        message,
        details=None,
        sample_size=None,
        missing_data=None,
    ):
        return StatisticalResult(
            test=test,
            variables=list(variables),
            sample_size=sample_size,
            status="invalid_input",
            error=StatisticalError(code, message, details or {}),
            missing_data=missing_data or {},
        )

    @staticmethod
    def _adopt_preparation_error(test, variables, prepared):
        result = prepared.result
        return StatisticalResult(
            test=test,
            variables=list(variables),
            sample_size=result.sample_size,
            status=result.status,
            error=result.error,
            missing_data=result.missing_data,
            warnings=result.warnings,
            details=result.details,
        )

    @staticmethod
    def _decision(p_value, alpha):
        return "reject_null" if p_value < alpha else "fail_to_reject_null"

    @staticmethod
    def _display_group_labels(variable, labels):
        """Use readable labels for standard gender coding without changing data."""
        if str(variable).strip().casefold() not in {"gender", "sex"}:
            return [str(label) for label in labels]
        readable = []
        for label in labels:
            token = str(label).strip().casefold()
            try:
                numeric = float(label)
            except (TypeError, ValueError):
                numeric = None
            if token in {"male", "m", "man"} or numeric == 1:
                readable.append("Male")
            elif token in {"female", "f", "woman"} or numeric == 2:
                readable.append("Female")
            else:
                readable.append(str(label))
        return readable

    @staticmethod
    def _normality_assumption(values, label, alpha=0.05):
        values = pd.Series(values).dropna().to_numpy(dtype=float)
        if len(values) < 3:
            return {
                "name": "normality",
                "statistic": None,
                "p_value": None,
                "passed": None,
                "details": {"sample": label, "evaluated": False, "reason": "fewer than 3 observations"},
            }
        if np.ptp(values) == 0:
            return {
                "name": "normality",
                "statistic": None,
                "p_value": None,
                "passed": None,
                "details": {
                    "sample": label,
                    "evaluated": False,
                    "reason": "sample has zero variance",
                },
            }
        if len(values) > 5000:
            return {
                "name": "normality",
                "statistic": None,
                "p_value": None,
                "passed": None,
                "details": {"sample": label, "evaluated": False, "reason": "Shapiro-Wilk limited to 5000 observations"},
            }
        statistic, p_value = stats.shapiro(values)
        return {
            "name": "normality",
            "statistic": float(statistic),
            "p_value": float(p_value),
            "passed": bool(p_value >= alpha),
            "details": {"sample": label, "method": "Shapiro-Wilk"},
        }

    @staticmethod
    def _levene_assumption(*groups, alpha=0.05):
        if any(np.ptp(group) == 0 for group in groups):
            return {
                "name": "equal_variances",
                "statistic": None,
                "p_value": None,
                "passed": None,
                "details": {
                    "method": "Levene median-centered",
                    "evaluated": False,
                    "reason": "at least one group has zero variance",
                },
            }
        statistic, p_value = stats.levene(*groups, center="median")
        return {
            "name": "equal_variances",
            "statistic": float(statistic),
            "p_value": float(p_value),
            "passed": bool(p_value >= alpha),
            "details": {"method": "Levene median-centered"},
        }

    @staticmethod
    def _hedges_correction(degrees):
        return math.exp(
            gammaln(degrees / 2)
            - 0.5 * math.log(degrees / 2)
            - gammaln((degrees - 1) / 2)
        ) if degrees > 1 else 1.0

    @staticmethod
    def _invalid_input(
        variables,
        code,
        message,
        details=None,
        sample_size=None,
        missing_data=None,
        warnings=None,
    ):
        names = variables if isinstance(variables, (list, tuple)) else []
        error = StatisticalError(code, message, details or {})
        result = StatisticalResult.from_input_error(
            "input_preparation",
            [name for name in names if isinstance(name, str)],
            error,
        )
        result.sample_size = sample_size
        result.missing_data = missing_data or {}
        result.warnings = warnings or []
        return PreparedStatisticalInput(pd.DataFrame(), result)
