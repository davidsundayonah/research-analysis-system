from dataclasses import dataclass, field
import math

import pandas as pd


@dataclass
class TableNumberingContext:
    scope_id: str
    _assigned: dict[str, int] = field(default_factory=dict)

    def number_for(self, source_key):
        source_key = str(source_key)
        if source_key not in self._assigned:
            self._assigned[source_key] = len(self._assigned) + 1
        return self._assigned[source_key]


@dataclass
class GeneratedTable:
    title: str
    columns: list[str]
    rows: list[list[str]]
    source: dict
    number: int | None = None
    numbering_scope_id: str | None = None
    footnotes: list[str] = field(default_factory=list)

    @property
    def display_title(self):
        if self.number is None:
            return self.title
        return f"Table {self.number}. {self.title}"

    def to_dict(self):
        return {
            "number": self.number,
            "title": self.title,
            "display_title": self.display_title,
            "numbering_scope_id": self.numbering_scope_id,
            "columns": self.columns.copy(),
            "rows": [row.copy() for row in self.rows],
            "footnotes": self.footnotes.copy(),
            "source": self.source.copy(),
        }


class TableGenerator:
    TEST_TITLES = {
        "descriptive_analysis": "Descriptive statistics",
        "independent_t_test": "Independent-samples t-test",
        "paired_t_test": "Paired-samples t-test",
        "one_way_anova": "One-way analysis of variance",
        "chi_square_test": "Chi-square test of independence",
        "pearson_correlation": "Pearson correlation",
        "spearman_correlation": "Spearman rank correlation",
        "linear_regression": "Simple linear regression",
    }

    def __init__(self, decimal_places=2, p_value_threshold=0.001):
        if isinstance(decimal_places, bool) or not isinstance(decimal_places, int):
            raise ValueError("decimal_places must be a non-negative integer.")
        if decimal_places < 0:
            raise ValueError("decimal_places must be a non-negative integer.")
        if not isinstance(p_value_threshold, (int, float)) or not 0 < p_value_threshold < 1:
            raise ValueError("p_value_threshold must be between 0 and 1.")
        self.decimal_places = decimal_places
        self.p_value_threshold = float(p_value_threshold)

    def from_saved_run(self, run, numbering=None, *, variable_labels=None, value_labels=None):
        result = run.get("result")
        if not isinstance(result, dict):
            raise ValueError("saved run must contain a decoded result dictionary.")
        source = {
            "type": "analysis_run",
            "run_id": run.get("id"),
            "project_id": run.get("project_id"),
            "question_id": run.get("research_question_id"),
            "hypothesis_id": run.get("hypothesis_id"),
            "dataset_id": run.get("dataset_id"),
            "dataset_signature": run.get("dataset_signature"),
            "actual_test": run.get("actual_test"),
            "created_at": run.get("created_at"),
        }
        return self.from_result(
            result,
            run.get("actual_test") or result.get("test", "unknown"),
            source=source,
            settings=run.get("settings") or {},
            numbering=numbering,
            source_key=run.get("id"),
            variable_labels=variable_labels,
            value_labels=value_labels,
        )

    def from_result(
        self,
        result,
        test_name=None,
        *,
        source=None,
        settings=None,
        numbering=None,
        source_key=None,
        variable_labels=None,
        value_labels=None,
    ):
        if hasattr(result, "to_dict"):
            result = result.to_dict()
        if not isinstance(result, dict):
            raise TypeError("result must be a StatisticalResult or result dictionary.")
        test_name = test_name or result.get("test", "unknown")
        details = result.get("details") or {}
        effect = result.get("effect_size") or {}
        settings = settings or {}
        parameters = settings.get("parameters") or {}
        confidence_level = parameters.get(
            "confidence_level",
            details.get("confidence_level", 0.95),
        )
        ci_label = f"{self._format_number(float(confidence_level) * 100, 0)}% CI"
        warnings = list(result.get("warnings") or [])
        footnotes = []

        if result.get("status", "ok") != "ok":
            error = result.get("error") or {}
            message = error.get("message", "This analysis did not produce a valid result.")
            footnotes.append(message)
            rows = [[
                self._format_variables(result.get("variables"), variable_labels),
                self._format_value(result.get("sample_size")),
                self._format_value(error.get("code")),
                message,
            ]]
            columns = ["Variables", "N", "Status", "Message"]
            title = self.TEST_TITLES.get(test_name, str(test_name))
        elif test_name == "descriptive_analysis":
            title = self.TEST_TITLES[test_name]
            summary = details.get("report", {}).get("numeric_summary") or []
            rows = [[
                self._format_labeled_value(record.get("Variable"), None, variable_labels),
                self._format_value(record.get("N")),
                self._format_value(record.get("Missing")),
                self._format_number(record.get("Mean")),
                self._format_number(record.get("Median")),
                self._format_number(record.get("Std. Deviation")),
                self._format_number(record.get("Minimum")),
                self._format_number(record.get("Maximum")),
            ] for record in summary]
            columns = ["Variable", "N", "Missing", "Mean", "Median", "SD", "Minimum", "Maximum"]
            footnotes.append(
                "Frequency tables with category counts and percentages are preserved in the saved result details and exported report."
            )
        elif test_name == "independent_t_test":
            title = self.TEST_TITLES[test_name]
            groups = details.get("group_order") or []
            sizes = details.get("group_sizes") or []
            means = details.get("group_means") or []
            sds = details.get("group_standard_deviations") or []
            rows = [[
                self._format_variables(result.get("variables"), variable_labels),
                self._format_labeled_value(groups[0] if len(groups) > 0 else None, result.get("variables", [None, None])[1] if len(result.get("variables") or []) > 1 else None, value_labels),
                self._format_value(sizes[0] if len(sizes) > 0 else None),
                self._format_value(means[0] if len(means) > 0 else None),
                self._format_value(sds[0] if len(sds) > 0 else None),
                self._format_labeled_value(groups[1] if len(groups) > 1 else None, result.get("variables", [None, None])[1] if len(result.get("variables") or []) > 1 else None, value_labels),
                self._format_value(sizes[1] if len(sizes) > 1 else None),
                self._format_value(means[1] if len(means) > 1 else None),
                self._format_value(sds[1] if len(sds) > 1 else None),
                self._format_number(result.get("statistic")),
                self._format_number(result.get("degrees_of_freedom")),
                self._format_p_value(result.get("p_value")),
                self._format_interval(result.get("confidence_interval")),
                self._format_number(effect.get("cohens_d")),
                self._format_number(effect.get("hedges_g")),
            ]]
            columns = [
                "Outcome", "Group 1", "n", "M", "SD", "Group 2", "n", "M", "SD",
                "t", "df", "p", ci_label, "Cohen's d", "Hedges' g",
            ]
            footnotes.extend(self._assumption_notes(result, warnings))
            footnotes.extend(self._convention_notes(details))
            self._note_unavailable(footnotes, "Group SDs were not stored in this saved result.", sds)
        elif test_name == "paired_t_test":
            title = self.TEST_TITLES[test_name]
            rows = [[
                self._format_variables(result.get("variables"), variable_labels),
                self._format_value(result.get("sample_size")),
                self._format_number(details.get("mean_difference")),
                self._format_number(details.get("standard_deviation_of_differences")),
                self._format_number(result.get("statistic")),
                self._format_number(result.get("degrees_of_freedom")),
                self._format_p_value(result.get("p_value")),
                self._format_interval(result.get("confidence_interval")),
                self._format_number(effect.get("cohens_dz")),
                self._format_number(effect.get("hedges_gz")),
            ]]
            columns = ["Comparison", "N", "Mean difference", "SD difference", "t", "df", "p", ci_label, "Cohen's dz", "Hedges' gz"]
            footnotes.extend(self._assumption_notes(result, warnings))
            footnotes.extend(self._convention_notes(details))
        elif test_name == "one_way_anova":
            title = self.TEST_TITLES[test_name]
            sources = [
                (
                    "Between groups",
                    details.get("sum_squares_between"),
                    details.get("degrees_of_freedom_between"),
                    details.get("mean_square_between"),
                    result.get("statistic"),
                    result.get("p_value"),
                ),
                (
                    "Within groups",
                    details.get("sum_squares_within"),
                    details.get("degrees_of_freedom_within"),
                    details.get("mean_square_within"),
                    None,
                    None,
                ),
                (
                    "Total",
                    details.get("sum_squares_total"),
                    details.get("degrees_of_freedom_total"),
                    None,
                    None,
                    None,
                ),
            ]
            rows = [[
                source,
                self._format_number(ss),
                self._format_value(df),
                self._format_number(ms),
                self._format_number(f_value),
                self._format_p_value(p_value),
            ] for source, ss, df, ms, f_value, p_value in sources]
            columns = ["Source", "Sum of squares", "df", "Mean square", "F", "p"]
            if any(sources[index][3] is None for index in (0, 1)):
                footnotes.append("Mean squares were not stored in this saved result and are shown as unavailable.")
            if sources[2][1] is None or sources[2][2] is None:
                footnotes.append("Total sum of squares or degrees of freedom were not stored in this saved result.")
            footnotes.append(
                "Effect sizes: "
                + ", ".join(
                    f"{name} = {self._format_number(value)}"
                    for name, value in effect.items()
                )
            )
            footnotes.extend(self._assumption_notes(result, warnings))
        elif test_name == "chi_square_test":
            title = self.TEST_TITLES[test_name]
            row_categories = details.get("row_categories") or []
            column_categories = details.get("column_categories") or []
            observed = details.get("observed") or []
            expected = details.get("expected") or []
            rows = []
            for row_index, category in enumerate(row_categories):
                for column_index, column_category in enumerate(column_categories):
                    obs = self._matrix_value(observed, row_index, column_index)
                    exp = self._matrix_value(expected, row_index, column_index)
                    rows.append([
                        self._format_labeled_value(category, (result.get("variables") or [None])[0], value_labels),
                        self._format_labeled_value(column_category, (result.get("variables") or [None, None])[1], value_labels),
                        self._format_value(obs),
                        self._format_number(exp),
                    ])
            rows.append([
                "Test statistic", "χ²", self._format_number(result.get("statistic")),
                f"df = {self._format_number(result.get('degrees_of_freedom'), 0)}; {self._format_p_value(result.get('p_value'))}",
            ])
            rows.append(["Effect size", "Cramer's V", self._format_number(effect.get("cramers_v")), ""])
            columns = ["Row category", "Column category", "Observed", "Expected / test"]
            footnotes.extend(self._assumption_notes(result, warnings))
            if details.get("continuity_correction"):
                footnotes.append("Yates continuity correction was applied to the 2 × 2 table.")
        elif test_name in {"pearson_correlation", "spearman_correlation"}:
            title = self.TEST_TITLES[test_name]
            variables = result.get("variables") or []
            rows = [[
                self._format_labeled_value(variables[0] if len(variables) > 0 else None, None, variable_labels),
                self._format_labeled_value(variables[1] if len(variables) > 1 else None, None, variable_labels),
                self._format_value(result.get("sample_size")),
                self._format_number(result.get("statistic")),
                self._format_p_value(result.get("p_value")),
                self._format_interval(result.get("confidence_interval")),
            ]]
            columns = ["Variable 1", "Variable 2", "N", "r" if test_name == "pearson_correlation" else "rs", "p", ci_label]
            if result.get("confidence_interval") is None:
                note = details.get("confidence_interval_note")
                footnotes.append(note or "Confidence interval unavailable in this saved result.")
            footnotes.extend(self._assumption_notes(result, warnings))
        elif test_name == "linear_regression":
            title = self.TEST_TITLES[test_name]
            variables = result.get("variables") or []
            predictor = variables[0] if len(variables) > 0 else "Predictor"
            coefficient_specs = [
                (
                    "Intercept",
                    details.get("intercept"),
                    details.get("intercept_standard_error"),
                    details.get("intercept_test_statistic"),
                    details.get("intercept_p_value"),
                    details.get("intercept_confidence_interval"),
                ),
                (
                    predictor,
                    details.get("slope"),
                    details.get("slope_standard_error"),
                    details.get("slope_test_statistic"),
                    details.get("slope_p_value"),
                    result.get("confidence_interval"),
                ),
            ]
            rows = [[
                    self._format_labeled_value(term, None, variable_labels),
                self._format_number(coefficient),
                self._format_number(standard_error),
                self._format_number(test_statistic),
                self._format_p_value(p_value),
                self._format_interval(interval),
            ] for term, coefficient, standard_error, test_statistic, p_value, interval in coefficient_specs]
            columns = ["Term", "Coefficient", "SE", "t", "p", ci_label]
            footnotes.append(
                f"Model: F({self._format_number(details.get('f_degrees_of_freedom', [None, None])[0], 0)}, "
                f"{self._format_number(details.get('f_degrees_of_freedom', [None, None])[1], 0)}) = "
                f"{self._format_number(details.get('f_statistic'))}; model p {self._format_p_value(result.get('p_value'))}; "
                f"R² = {self._format_number(effect.get('r_squared'))}; adjusted R² = {self._format_number(effect.get('adjusted_r_squared'))}."
            )
            if details.get("intercept_standard_error") is None:
                footnotes.append("Intercept standard error and test were not stored in this saved result.")
            footnotes.extend(self._assumption_notes(result, warnings))
        else:
            title = self.TEST_TITLES.get(test_name, str(test_name))
            rows = [[
                self._format_variables(result.get("variables"), variable_labels),
                self._format_value(result.get("sample_size")),
                self._format_number(result.get("statistic")),
                self._format_p_value(result.get("p_value")),
            ]]
            columns = ["Variables", "N", "Statistic", "p"]
            footnotes.append("No specialized table adapter exists for this result type.")

        if result.get("decision"):
            footnotes.append(f"Decision: {result['decision'].replace('_', ' ')}.")
        if result.get("interpretation"):
            footnotes.append(str(result["interpretation"]))
        if not footnotes:
            footnotes.append("Unavailable values are shown as 'Not available'.")

        number = None
        if numbering is not None:
            if not isinstance(numbering, TableNumberingContext):
                raise TypeError("numbering must be a TableNumberingContext or None.")
            key = source_key
            if key is None:
                key = (source or {}).get("run_id") or id(result)
            number = numbering.number_for(key)

        return GeneratedTable(
            title=title,
            number=number,
            numbering_scope_id=(numbering.scope_id if numbering is not None else None),
            columns=columns,
            rows=rows,
            footnotes=footnotes,
            source=(source or {"type": "statistical_result", "test": test_name}).copy(),
        )

    def from_descriptive_summary(
        self,
        summary,
        *,
        title="Descriptive statistics",
        source=None,
        numbering=None,
        source_key=None,
        variable_labels=None,
    ):
        records = self._records(summary)
        columns = ["Variable", "N", "Mean", "SD", "Minimum", "Maximum"]
        rows = []
        for record in records:
            rows.append([
                self._format_labeled_value(record.get("Variable", record.get("variable")), None, variable_labels),
                self._format_value(record.get("N", record.get("Valid"))),
                self._format_number(record.get("Mean", record.get("mean"))),
                self._format_number(record.get("Std. Deviation", record.get("std"))),
                self._format_number(record.get("Minimum", record.get("minimum"))),
                self._format_number(record.get("Maximum", record.get("maximum"))),
            ])
        return self._make_table(
            title,
            columns,
            rows,
            {"type": "descriptive_summary", **(source or {})},
            numbering,
            source_key or (source or {}).get("source_id", "descriptive_summary"),
            footnotes=["Values are formatted from the supplied descriptive summary; no statistics were recalculated."],
        )

    def from_frequency_table(
        self,
        frequency_table,
        *,
        variable,
        title=None,
        source=None,
        numbering=None,
        source_key=None,
        value_labels=None,
        variable_labels=None,
    ):
        records = self._records(frequency_table)
        rows = [[
            self._format_labeled_value(record.get("Value", record.get("value")), variable, value_labels),
            self._format_value(record.get("Frequency", record.get("frequency"))),
            self._format_percentage(record.get("Percent", record.get("percent"))),
        ] for record in records]
        return self._make_table(
            title or f"Demographic distribution: {self._format_labeled_value(variable, None, variable_labels)}",
            ["Category", "Frequency", "Percentage"],
            rows,
            {"type": "frequency_table", "variable": variable, **(source or {})},
            numbering,
            source_key or (source or {}).get("source_id", f"frequency:{variable}"),
            footnotes=["Percentages are formatted from the supplied frequency table."],
        )

    def from_descriptive_report(
        self,
        report,
        *,
        report_id,
        numbering=None,
        variable_labels=None,
        value_labels=None,
    ):
        if not isinstance(report, dict):
            raise TypeError("report must be a descriptive-report dictionary.")
        tables = []
        numeric_summary = report.get("numeric_summary")
        if numeric_summary is not None:
            tables.append(self.from_descriptive_summary(
                numeric_summary,
                title="Descriptive statistics",
                source={
                    "type": "descriptive_report",
                    "report_id": report_id,
                    "section": "numeric_summary",
                },
                numbering=numbering,
                source_key=f"{report_id}:numeric_summary",
                variable_labels=variable_labels,
            ))

        frequency_tables = report.get("frequency_tables") or {}
        for variable, frequency_table in frequency_tables.items():
            tables.append(self.from_frequency_table(
                frequency_table,
                variable=variable,
                title=f"Frequency distribution: {variable}",
                source={
                    "type": "descriptive_report",
                    "report_id": report_id,
                    "section": "frequency_tables",
                    "variable": variable,
                },
                numbering=numbering,
                source_key=f"{report_id}:frequency:{variable}",
                value_labels=value_labels,
                variable_labels=variable_labels,
            ))
        return tables

    def _make_table(self, title, columns, rows, source, numbering, source_key, footnotes):
        number = None
        if numbering is not None:
            if not isinstance(numbering, TableNumberingContext):
                raise TypeError("numbering must be a TableNumberingContext or None.")
            number = numbering.number_for(source_key)
        return GeneratedTable(
            title=title,
            number=number,
            numbering_scope_id=(numbering.scope_id if numbering is not None else None),
            columns=columns,
            rows=rows,
            source=source.copy(),
            footnotes=footnotes,
        )

    def _format_number(self, value, decimals=None):
        if value is None:
            return "Not available"
        try:
            value = float(value)
        except (TypeError, ValueError):
            return "Not available"
        if not math.isfinite(value):
            return "Not available"
        return f"{value:.{self.decimal_places if decimals is None else decimals}f}"

    def _format_p_value(self, value):
        if value is None:
            return "Not available"
        try:
            value = float(value)
        except (TypeError, ValueError):
            return "Not available"
        if not math.isfinite(value):
            return "Not available"
        if value < self.p_value_threshold:
            threshold = self._format_number(self.p_value_threshold, 3)
            return f"p < {threshold.replace('0.', '.')}"
        return f"p = {self._format_number(value, 3).replace('0.', '.')}"

    def _format_percentage(self, value):
        if value is None:
            return "Not available"
        text = self._format_number(value)
        return "Not available" if text == "Not available" else f"{text}%"

    def _format_interval(self, interval):
        if interval is None or not isinstance(interval, (list, tuple)) or len(interval) != 2:
            return "Not available"
        return f"{self._format_number(interval[0])} to {self._format_number(interval[1])}"

    def _format_value(self, value):
        if value is None:
            return "Not available"
        if isinstance(value, (list, tuple)):
            return "[" + ", ".join(self._format_value(item) for item in value) + "]"
        if isinstance(value, dict):
            return "; ".join(
                f"{key}: {self._format_value(item)}"
                for key, item in value.items()
            )
        try:
            if pd.isna(value):
                return "Not available"
        except (TypeError, ValueError):
            pass
        if isinstance(value, int) and not isinstance(value, bool):
            return str(value)
        if isinstance(value, float):
            return self._format_number(value)
        return str(value)

    @staticmethod
    def _format_variables(variables, variable_labels=None):
        return ", ".join(
            str((variable_labels or {}).get(value, value))
            for value in variables
        ) if variables else "Not available"

    def _format_labeled_value(self, value, variable=None, labels=None):
        if variable is None and isinstance(labels, dict) and value in labels:
            return str(labels[value])
        if isinstance(labels, dict) and variable in labels:
            mapped = labels[variable]
            if isinstance(mapped, dict):
                try:
                    if value in mapped:
                        return str(mapped[value])
                    numeric_value = float(value)
                    if numeric_value.is_integer() and int(numeric_value) in mapped:
                        return str(mapped[int(numeric_value)])
                except (TypeError, ValueError):
                    pass
        return self._format_value(value)

    @staticmethod
    def _matrix_value(matrix, row, column):
        try:
            return matrix[row][column]
        except (IndexError, TypeError):
            return None

    @staticmethod
    def _records(value):
        if isinstance(value, pd.DataFrame):
            return value.to_dict(orient="records")
        if isinstance(value, dict):
            return [value]
        if isinstance(value, (list, tuple)):
            return [dict(item) for item in value]
        raise TypeError("Table input must be a DataFrame, record dictionary, or sequence of records.")

    @staticmethod
    def _assumption_notes(result, warnings):
        notes = []
        for assumption in result.get("assumptions") or []:
            if assumption.get("passed") is False:
                notes.append(
                    f"Assumption check '{assumption.get('name', 'unknown')}' indicated a departure from the assumption."
                )
            elif assumption.get("passed") is None:
                reason = (assumption.get("details") or {}).get("reason")
                notes.append(
                    f"Assumption check '{assumption.get('name', 'unknown')}' could not be evaluated."
                    + (f" {reason}." if reason else "")
                )
        notes.extend(str(warning) for warning in warnings)
        return list(dict.fromkeys(notes))

    @staticmethod
    def _convention_notes(details):
        notes = []
        for key in ("effect_size_convention", "hedges_correction", "omega_squared_convention"):
            if details.get(key):
                notes.append(str(details[key]))
        return notes

    @staticmethod
    def _note_unavailable(footnotes, explanation, values):
        if not values or any(value is None for value in values):
            footnotes.append(explanation)
