import hashlib
import json
import platform
import sys

import pandas as pd
import numpy as np
from pandas.api.types import is_bool_dtype, is_numeric_dtype
import scipy
import statsmodels
from statsmodels.stats.multitest import multipletests

from app.statistics.statistical_engine import StatisticalEngine
from app.statistics.statistical_result import StatisticalError, StatisticalResult
from app.statistics.descriptive_statistics import DescriptiveStatistics
from app.statistics.variable_inspector import VariableInspector


class StatisticalWorkflow:
    TEST_SETTINGS = {
        "independent_t_test": {
            "variables": ("outcome_variable", "grouping_variable"),
            "roles": {"outcome_variable": "outcome", "grouping_variable": "grouping"},
            "method": "independent_t_test",
        },
        "paired_t_test": {
            "variables": ("first_variable", "second_variable"),
            "roles": {"first_variable": "outcome", "second_variable": "outcome"},
            "method": "paired_t_test",
        },
        "one_way_anova": {
            "variables": ("outcome_variable", "grouping_variable"),
            "roles": {"outcome_variable": "outcome", "grouping_variable": "grouping"},
            "method": "one_way_anova",
        },
        "chi_square_test": {
            "variables": ("first_variable", "second_variable"),
            "roles": {},
            "method": "chi_square_test",
        },
        "correlation": {
            "variables": ("first_variable", "second_variable"),
            "roles": {},
            "method": "correlation",
        },
        "linear_regression": {
            "variables": ("predictor_variable", "outcome_variable"),
            "roles": {"predictor_variable": "predictor", "outcome_variable": "outcome"},
            "method": "linear_regression",
        },
    }
    DEFAULT_SETTINGS = {
        "independent_t_test": {
            "equal_var": False,
            "confidence_level": 0.95,
            "alpha": 0.05,
            "missing_policy": "listwise",
        },
        "paired_t_test": {
            "confidence_level": 0.95,
            "alpha": 0.05,
            "missing_policy": "listwise",
        },
        "one_way_anova": {
            "confidence_level": 0.95,
            "alpha": 0.05,
            "missing_policy": "listwise",
        },
        "chi_square_test": {
            "correction": True,
            "alpha": 0.05,
            "missing_policy": "listwise",
        },
        "correlation": {
            "method": "pearson",
            "confidence_level": 0.95,
            "alpha": 0.05,
            "missing_policy": "listwise",
        },
        "linear_regression": {
            "confidence_level": 0.95,
            "alpha": 0.05,
            "missing_policy": "listwise",
        },
    }
    DESCRIPTIVE_TEST = "descriptive_analysis"

    def __init__(self, database):
        self.database = database

    @staticmethod
    def dataset_signature(dataframe):
        schema = json.dumps(
            {
                "columns": [str(column) for column in dataframe.columns],
                "dtypes": [str(dtype) for dtype in dataframe.dtypes],
                "rows": len(dataframe),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        try:
            values = pd.util.hash_pandas_object(
                dataframe,
                index=True,
                categorize=True,
            ).values.tobytes()
        except (TypeError, ValueError):
            values = dataframe.to_csv(index=True).encode("utf-8")
        return hashlib.sha256(schema + values).hexdigest()

    def run_analysis(
        self,
        project_id,
        question_id,
        hypothesis_id,
        dataset_id,
        dataframe,
        test_name,
        settings,
    ):
        if test_name != self.DESCRIPTIVE_TEST and test_name not in self.TEST_SETTINGS:
            return self._error(
                test_name,
                [],
                "UNSUPPORTED_TEST",
                "The selected statistical test is not supported.",
            )
        if not isinstance(dataframe, pd.DataFrame):
            return self._error(
                test_name,
                [],
                "INVALID_DATASET",
                "Analysis requires the active dataset as a DataFrame.",
            )

        question = self.database.get_research_question(project_id, question_id)
        project = self.database.get_project(project_id)
        dataset = self.database.get_dataset(dataset_id)
        if project is None or question is None or dataset is None or dataset["project_id"] != project_id:
            return self._error(
                test_name,
                [],
                "OWNERSHIP_MISMATCH",
                "Question and dataset must belong to the selected project.",
            )
        if test_name == self.DESCRIPTIVE_TEST:
            return self._run_descriptive_analysis(
                project_id,
                question_id,
                dataset_id,
                dataframe,
                settings,
            )
        if hypothesis_id is None:
            return self._error(
                test_name,
                [],
                "HYPOTHESIS_REQUIRED",
                "Select a hypothesis before running an inferential analysis.",
            )
        hypothesis = self.database.get_hypothesis(
            project_id,
            question_id,
            hypothesis_id,
        )
        if hypothesis is None:
            return self._error(
                test_name,
                [],
                "OWNERSHIP_MISMATCH",
                "Hypothesis must belong to the selected question and project.",
            )
        if not hypothesis["null_hypothesis"].strip() or not hypothesis[
            "alternative_hypothesis"
        ].strip():
            return self._error(
                test_name,
                [],
                "INCOMPLETE_HYPOTHESIS",
                "Both null and alternative hypotheses are required.",
            )
        if not isinstance(settings, dict):
            return self._error(
                test_name,
                [],
                "INVALID_SETTINGS",
                "Analysis settings must be a dictionary.",
            )

        spec = self.TEST_SETTINGS[test_name]
        effective_settings = self.DEFAULT_SETTINGS[test_name].copy()
        if "alpha" not in settings and project["significance_level"] is not None:
            effective_settings["alpha"] = float(project["significance_level"])
        effective_settings.update(settings)
        variable_keys = spec["variables"]
        missing_keys = [key for key in variable_keys if key not in effective_settings]
        if missing_keys:
            return self._error(
                test_name,
                [],
                "MISSING_VARIABLE_SELECTION",
                "Settings are missing required variable selections.",
                {"settings": missing_keys},
            )

        selected = [str(effective_settings[key]) for key in variable_keys]
        if any(name not in dataframe.columns for name in selected):
            return self._error(
                test_name,
                selected,
                "VARIABLE_NOT_FOUND",
                "A selected variable does not exist in the active dataset.",
            )

        links = self.database.get_question_variables(project_id, question_id)
        active_links = {
            (link["variable_name"], link["role"])
            for link in links
            if link["dataset_id"] == dataset_id
            and link["variable_exists"]
            and link["variable_name"] in dataframe.columns
        }
        for key, role in spec["roles"].items():
            if (str(settings[key]), role) not in active_links:
                return self._error(
                    test_name,
                    selected,
                    "VARIABLE_ROLE_MISMATCH",
                    f"'{settings[key]}' must be linked to this question with role '{role}'.",
                    {"variable": str(effective_settings[key]), "required_role": role},
                )
        if test_name in {"chi_square_test", "correlation"}:
            active_names = {name for name, _role in active_links}
            unlinked = [name for name in selected if name not in active_names]
            if unlinked:
                return self._error(
                    test_name,
                    selected,
                    "UNLINKED_VARIABLE",
                    "All selected variables must be linked to the research question and active dataset.",
                    {"variables": unlinked},
                )

        engine = StatisticalEngine(dataframe)
        try:
            result = getattr(engine, spec["method"])(
                *[settings[key] for key in variable_keys],
                **{
                    key: value
                    for key, value in effective_settings.items()
                    if key not in variable_keys
                },
            )
        except (TypeError, ValueError) as error:
            return self._error(
                test_name,
                selected,
                "INVALID_SETTINGS",
                str(error),
            )

        if result.status != "ok":
            return result

        serialized = result.to_dict()
        serialized["result_schema_version"] = 1
        serialized["details"]["hypothesis_directionality"] = hypothesis[
            "directionality"
        ]
        serialized["details"]["decision_scope"] = (
            "Decision uses the test p-value and alpha; directionality is recorded but is not inferred from a two-sided test."
        )
        settings_record = {
            "result_schema_version": 1,
            "test": test_name,
            "parameters": effective_settings,
            "software": {
                "application": "research-analysis-system 0.2.0",
                "python": sys.version.split()[0],
                "platform": platform.platform(),
                "scipy": scipy.__version__,
                "statsmodels": statsmodels.__version__,
                "pandas": pd.__version__,
            },
            "schema": [
                {"name": str(column), "dtype": str(dtype)}
                for column, dtype in dataframe.dtypes.items()
            ],
        }
        signature = self.dataset_signature(dataframe)
        run_id = self.database.create_analysis_run(
            project_id=project_id,
            question_id=question_id,
            hypothesis_id=hypothesis_id,
            dataset_id=dataset_id,
            dataset_signature=signature,
            actual_test=result.test,
            settings=settings_record,
            result=serialized,
            hypothesis_decision=result.decision,
        )
        self._apply_project_multiplicity(project_id)
        saved_row = next(
            row for row in self.database.get_project_analysis_runs(project_id)
            if row["id"] == run_id
        )
        saved_result = self.database.decode_analysis_run(saved_row)["result"]
        result.p_value = saved_result.get("p_value")
        result.decision = saved_result.get("decision")
        result.details.update(saved_result.get("details") or {})
        return result

    def _apply_project_multiplicity(self, project_id):
        """Apply the project's declared correction to all saved inferential runs."""
        project = self.database.get_project(project_id)
        method = str((project["multiplicity_method"] if project else "holm") or "holm")
        runs = self.database.get_project_analysis_runs(project_id)
        inferential = []
        for row in runs:
            decoded = self.database.decode_analysis_run(row)
            result = decoded.get("result") or {}
            raw_p = result.get("details", {}).get("raw_p_value", result.get("p_value"))
            if decoded.get("actual_test") != self.DESCRIPTIVE_TEST and raw_p is not None:
                inferential.append((row, decoded, float(raw_p)))
        if not inferential:
            return
        raw_values = [entry[2] for entry in inferential]
        adjusted_values = raw_values if method == "none" else multipletests(
            raw_values, method=method
        )[1].tolist()
        alpha = float(project["significance_level"] if project else 0.05)
        for (row, decoded, raw_p), adjusted_p in zip(inferential, adjusted_values):
            result = decoded["result"]
            details = result.setdefault("details", {})
            details["raw_p_value"] = raw_p
            details["adjusted_p_value"] = float(adjusted_p)
            details["multiplicity_method"] = method
            details["multiplicity_family_size"] = len(inferential)
            result["p_value"] = float(adjusted_p)
            decision = "reject_null" if adjusted_p < alpha else "fail_to_reject_null"
            result["decision"] = decision
            self.database.update_analysis_run_result(row["id"], result, decision)

    def _run_descriptive_analysis(
        self,
        project_id,
        question_id,
        dataset_id,
        dataframe,
        settings,
    ):
        question = self.database.get_research_question(project_id, question_id)
        if question["design_type"] != "descriptive":
            return self._error(
                self.DESCRIPTIVE_TEST,
                [],
                "DESCRIPTIVE_DESIGN_REQUIRED",
                "Descriptive analysis is only available for descriptive research questions.",
            )
        if not isinstance(settings, dict):
            return self._error(
                self.DESCRIPTIVE_TEST,
                [],
                "INVALID_SETTINGS",
                "Analysis settings must be a dictionary.",
            )
        variables = [str(value) for value in settings.get("variables", [])]
        if not variables:
            return self._error(
                self.DESCRIPTIVE_TEST,
                [],
                "MISSING_VARIABLE_SELECTION",
                "Link at least one outcome variable before running descriptive analysis.",
            )
        if any(variable not in dataframe.columns for variable in variables):
            return self._error(
                self.DESCRIPTIVE_TEST,
                variables,
                "VARIABLE_NOT_FOUND",
                "A selected descriptive variable does not exist in the active dataset.",
            )
        report = DescriptiveStatistics(dataframe).full_report()
        report_details = {
            "overview": report["overview"],
            "numeric_summary": self._frame_records(report["numeric_summary"]),
            "missing_summary": self._frame_records(report["missing_summary"]),
            "frequency_tables": {
                name: self._frame_records(table)
                for name, table in report["frequency_tables"].items()
            },
        }
        missing_cells = report["overview"]["Missing Cells"]
        result = StatisticalResult(
            test=self.DESCRIPTIVE_TEST,
            variables=variables,
            sample_size=len(dataframe),
            decision="descriptive_only",
            interpretation=(
                "Descriptive analysis summarizes the observed dataset. "
                "No inferential test or hypothesis decision was required."
            ),
            warnings=(
                [f"The dataset contains {missing_cells:,} missing cells; review valid N and missing percentages."]
                if missing_cells
                else []
            ),
            details={"report": report_details},
        )
        serialized = result.to_dict()
        serialized["result_schema_version"] = 2
        settings_record = {
            "result_schema_version": 2,
            "test": self.DESCRIPTIVE_TEST,
            "parameters": {"variables": variables},
            "software": {
                "application": "research-analysis-system 0.2.0",
                "python": sys.version.split()[0],
                "platform": platform.platform(),
                "pandas": pd.__version__,
            },
            "schema": [
                {"name": str(column), "dtype": str(dtype)}
                for column, dtype in dataframe.dtypes.items()
            ],
        }
        self.database.create_analysis_run(
            project_id=project_id,
            question_id=question_id,
            hypothesis_id=None,
            dataset_id=dataset_id,
            dataset_signature=self.dataset_signature(dataframe),
            actual_test=self.DESCRIPTIVE_TEST,
            settings=settings_record,
            result=serialized,
            hypothesis_decision=None,
        )
        return result

    @staticmethod
    def _frame_records(frame):
        return json.loads(frame.to_json(orient="records", date_format="iso"))

    def is_snapshot_current(self, analysis_run, dataframe):
        return analysis_run["dataset_signature"] == self.dataset_signature(dataframe)

    @staticmethod
    def _error(test, variables, code, message, details=None):
        return StatisticalResult(
            test=test or "unknown",
            variables=[name for name in variables if isinstance(name, str) and name],
            status="invalid_input",
            error=StatisticalError(code, message, details or {}),
        )


class TestRecommendationEngine:
    def recommend(
        self,
        question,
        dataframe,
        linked_variables,
        sample_structure="independent",
        dataset_id=None,
        variable_metadata=None,
    ):
        if question is None:
            return self._incomplete("Select a research question before choosing a test.", 0)
        design = question["design_type"]
        if not isinstance(dataframe, pd.DataFrame):
            return [{
                "test": None,
                "settings": {},
                "reason": "No active dataset is available to inspect.",
                "warnings": ["Import or select a dataset first."],
            }]

        linked_variables = list(linked_variables)
        links = [
            link for link in linked_variables
            if link["variable_exists"]
            and link["variable_name"] in dataframe.columns
            and (
                dataset_id is None
                or (
                    "dataset_id" in link.keys()
                    and link["dataset_id"] == dataset_id
                )
            )
        ]
        stale_count = len(linked_variables) - len(links)
        role_names = {}
        for link in links:
            names = role_names.setdefault(link["role"], [])
            if link["variable_name"] not in names:
                names.append(link["variable_name"])

        def numeric(name):
            series = dataframe[name]
            return bool(is_numeric_dtype(series) and not is_bool_dtype(series))

        inspector = VariableInspector(dataframe)
        metadata_by_name = {
            str(row.get("name")): row
            for row in (variable_metadata or [])
            if isinstance(row, dict) and row.get("name") is not None
        }

        def measurement_level(name):
            saved_measure = str(
                metadata_by_name.get(str(name), {}).get("measure") or ""
            ).strip().lower()
            if saved_measure in {"nominal", "ordinal", "scale"}:
                return saved_measure
            return inspector.detect_measure(dataframe[name]).lower()

        def association_level(name):
            return "numeric" if measurement_level(name) in {"ordinal", "scale"} else "categorical"

        def variable_warnings(names):
            warnings = []
            for name in names:
                if not numeric(name):
                    warnings.append(f"'{name}' is not a numeric measure.")
            if stale_count:
                warnings.append(f"{stale_count} linked variable(s) are stale or absent from the active dataset.")
            return warnings

        if design == "descriptive":
            outcomes = role_names.get("outcome", [])
            if not outcomes:
                return self._incomplete(
                    "Descriptive analysis needs at least one linked outcome variable.",
                    stale_count,
                )
            return [{
                "test": StatisticalWorkflow.DESCRIPTIVE_TEST,
                "settings": {"variables": outcomes},
                "reason": "This question is descriptive, so the app will produce frequency, percentage, valid N, missing N, mean, median, and spread summaries. No inferential test or hypothesis is required.",
                "warnings": ([f"{stale_count} linked variable(s) are stale."] if stale_count else []),
            }]

        outcomes = role_names.get("outcome", [])
        predictors = role_names.get("predictor", [])
        groups = role_names.get("grouping", [])

        if design == "comparison":
            if sample_structure not in {"paired", "independent"}:
                return self._incomplete(
                    "Choose whether observations are paired or independent before selecting a test.",
                    stale_count,
                )
            if sample_structure == "paired":
                if len(outcomes) < 2:
                    return self._incomplete(
                        "Paired comparison requires at least two linked outcome measurements.",
                        stale_count,
                    )
                candidates = []
                for index, first in enumerate(outcomes):
                    for second in outcomes[index + 1:]:
                        if not numeric(first) or not numeric(second):
                            continue
                        pairs = dataframe[[first, second]].dropna()
                        warnings = variable_warnings([first, second])
                        if len(pairs) < 2:
                            warnings.append("At least two complete pairs are needed to run a paired t-test.")
                        if len(pairs) < 8:
                            warnings.append("Small paired samples make the normality-of-differences check especially important.")
                        if any(measurement_level(name) == "ordinal" for name in (first, second)):
                            warnings.append("One or both paired outcomes are ordinal-coded; interpret the mean difference cautiously.")
                        candidates.append({
                            "test": "paired_t_test",
                            "settings": {"first_variable": first, "second_variable": second},
                            "reason": f"Paired sample structure compares within-unit differences for '{first}' and '{second}'.",
                            "warnings": warnings,
                        })
                if not candidates:
                    return self._incomplete(
                        "Paired comparison needs two linked numeric outcome measurements.",
                        stale_count,
                    )
                if len(candidates) > 1:
                    for candidate in candidates:
                        candidate["reason"] += " Multiple outcome pairs are linked; choose the comparison of interest."
                return candidates
            if not outcomes or not groups:
                return self._incomplete("Comparison design needs an outcome and grouping variable link.", stale_count)
            candidates = []
            for outcome in outcomes:
                if not numeric(outcome):
                    continue
                for group in groups:
                    count = dataframe[group].nunique(dropna=True)
                    if count < 2:
                        continue
                    level = measurement_level(outcome)
                    group_sizes = dataframe.groupby(group, dropna=True)[outcome].count()
                    warnings = variable_warnings([outcome])
                    if (group_sizes < 2).any():
                        warnings.append("Each group needs at least two complete outcome observations.")
                    if level == "ordinal":
                        warnings.append("Outcome is ordinal-coded; mean-based inference relies on an interval-scale approximation, and no nonparametric comparison test is implemented.")
                    if count == 2:
                        warnings.append("Levene's equal-variance diagnostic will be reported; Welch's t-test does not assume equal variances.")
                        if (group_sizes < 8).any():
                            warnings.append("Small group samples limit the power of normality checks and the stability of the mean comparison.")
                        test = "independent_t_test"
                        reason = f"Numeric {level} outcome '{outcome}' is compared between two independent groups in '{group}'; Welch's t-test is the default unequal-variance option."
                    else:
                        warnings.append("Classical ANOVA assumes independent observations; its normality and equal-variance diagnostics will be reported.")
                        if (group_sizes < 8).any():
                            warnings.append("Some groups have fewer than eight observations; assumption checks may have limited power.")
                        test = "one_way_anova"
                        reason = f"Numeric {level} outcome '{outcome}' is compared across {count} independent groups in '{group}'; one-way ANOVA supplies the omnibus comparison."
                    candidates.append({
                        "test": test,
                        "settings": {"outcome_variable": outcome, "grouping_variable": group},
                        "reason": reason,
                        "warnings": warnings,
                    })
            if not candidates:
                return self._incomplete(
                    "No supported numeric outcome and grouping-variable combination has at least two observed groups.",
                    stale_count,
                )
            if len(candidates) > 1:
                for candidate in candidates:
                    candidate["reason"] += " Multiple outcome/group role combinations are linked; choose the intended comparison."
            return candidates

        if design == "association":
            if not predictors or not outcomes:
                return self._incomplete(
                    "Association design needs at least one predictor and one outcome variable link.",
                    stale_count,
                )
            pairs = [
                (predictor, outcome)
                for predictor in predictors
                for outcome in outcomes
                if predictor != outcome
            ]
            numeric_links = [
                pair for pair in pairs
                if association_level(pair[0]) == "numeric"
                and association_level(pair[1]) == "numeric"
            ]
            categorical_links = [
                pair for pair in pairs
                if measurement_level(pair[0]) in {"nominal", "ordinal"}
                and measurement_level(pair[1]) in {"nominal", "ordinal"}
                and not (
                    measurement_level(pair[0]) == "ordinal"
                    and measurement_level(pair[1]) == "ordinal"
                )
            ]
            recommendations = []
            for first, second in numeric_links:
                    complete = dataframe[[first, second]].dropna()
                    warnings = variable_warnings([first, second])
                    if len(complete) < 3:
                        warnings.append("At least three complete observations are required to test correlation.")
                    if len(complete) < 8:
                        warnings.append("Small samples make correlation inference and confidence intervals less reliable.")
                    if complete[first].nunique() < 2 or complete[second].nunique() < 2:
                        warnings.append("Correlation is undefined when either selected variable is constant.")
                    ordinal = any(measurement_level(name) == "ordinal" for name in (first, second))
                    preferred = "spearman" if ordinal else "pearson"
                    alternative = "pearson" if ordinal else "spearman"
                    reason = (
                        "At least one selected measure is ordinal; Spearman's rank correlation is preferred for monotonic association."
                        if ordinal else
                        "Both selected measures are scale-level; Pearson tests linear association, subject to linearity and distribution checks."
                    )
                    recommendations.append({
                        "test": "correlation",
                        "settings": {"first_variable": first, "second_variable": second, "method": preferred},
                        "reason": reason,
                        "warnings": warnings + (
                            ["Review a scatterplot for linearity, outliers, and normality before interpreting Pearson inference."]
                            if preferred == "pearson" else []
                        ),
                    })
                    recommendations.append({
                        "test": "correlation",
                        "settings": {"first_variable": first, "second_variable": second, "method": alternative},
                        "reason": (
                            "Pearson is an alternative if these ordinal scores can reasonably be treated as interval-scale and their relation is linear."
                            if ordinal else
                            "Spearman is a rank-based alternative for a monotonic relationship or when Pearson assumptions are questionable."
                        ),
                        "warnings": warnings.copy() + ["Review a scatterplot for linearity, monotonicity, and influential observations."],
                    })
            for first, second in categorical_links:
                    complete = dataframe[[first, second]].dropna()
                    observed = pd.crosstab(complete[first], complete[second]).to_numpy()
                    warnings = []
                    if (
                        measurement_level(first) == "ordinal"
                        or measurement_level(second) == "ordinal"
                    ):
                        warnings.append("Chi-square treats ordinal categories as nominal and does not use their ordering.")
                    if observed.shape[0] < 2 or observed.shape[1] < 2:
                        warnings.append("Both variables need at least two observed categories.")
                    elif observed.sum():
                        expected = np.outer(observed.sum(axis=1), observed.sum(axis=0)) / observed.sum()
                        if (expected < 5).any():
                            warnings.append("Some expected chi-square cell counts are below 5; the asymptotic approximation is questionable.")
                    if len(complete) < 20:
                        warnings.append("Small contingency tables may need an exact test; no exact categorical test is currently implemented.")
                    recommendations.append({
                        "test": "chi_square_test",
                        "settings": {"first_variable": first, "second_variable": second},
                        "reason": f"Both variables are nominal/categorical; chi-square tests independence for '{first}' and '{second}'.",
                        "warnings": warnings + ["Inspect expected cell counts; this test uses an asymptotic approximation."],
                    })
            if recommendations:
                if len(recommendations) > 1:
                    for recommendation in recommendations:
                        recommendation["reason"] += " Multiple eligible variable/test options are shown; choose the one matching the research question."
                if stale_count:
                    for recommendation in recommendations:
                        recommendation["warnings"].append(
                            f"{stale_count} linked variable(s) are stale or absent from the active dataset."
                        )
                return recommendations
            if pairs and not recommendations:
                return self._incomplete(
                    "The linked predictor/outcome pair has incompatible measurement levels for the implemented association tests.",
                    stale_count,
                )
            return self._incomplete("Association design needs an eligible predictor/outcome pair.", stale_count)

        if design == "prediction":
            if not predictors or not outcomes:
                return self._incomplete("Prediction design needs predictor and outcome links.", stale_count)
            candidates = []
            for predictor in predictors:
                for outcome in outcomes:
                    if not numeric(predictor) or not numeric(outcome) or predictor == outcome:
                        continue
                    levels = {
                        "predictor": measurement_level(predictor),
                        "outcome": measurement_level(outcome),
                    }
                    warnings = variable_warnings([predictor, outcome])
                    if "ordinal" in levels.values():
                        warnings.append("Simple linear regression assumes interval-scale numeric measures; one or both selected variables are ordinal-coded.")
                    complete = dataframe[[predictor, outcome]].dropna()
                    if len(complete) < 3:
                        warnings.append("At least three complete observations are required to fit the regression.")
                    if len(complete) < 8:
                        warnings.append("Small samples limit residual diagnostics and make regression estimates unstable.")
                    if complete[predictor].nunique() < 2:
                        warnings.append("Regression cannot be fit when the predictor is constant or singular.")
                    warnings.append("Residual normality, constant variance, and autocorrelation diagnostics will be reported; inspect them before inference.")
                    candidates.append({
                        "test": "linear_regression",
                        "settings": {"predictor_variable": predictor, "outcome_variable": outcome},
                        "reason": f"Numeric {levels['predictor']} predictor '{predictor}' and {levels['outcome']} outcome '{outcome}'; simple linear regression estimates linear outcome change per predictor unit.",
                        "warnings": warnings,
                    })
            if candidates:
                if len(candidates) > 1:
                    for candidate in candidates:
                        candidate["reason"] += " Multiple linked predictor/outcome pairs are eligible; choose the intended model."
                return candidates
            return self._incomplete("Prediction design requires distinct numeric predictor and outcome links.", stale_count)

        return self._incomplete(f"Unsupported research design '{design}'.", stale_count)

    @staticmethod
    def _incomplete(reason, stale_count):
        warnings = ["Link the required variables before choosing a test."]
        if stale_count:
            warnings.append(f"{stale_count} linked variable(s) are stale or absent from the active dataset.")
        return [{"test": None, "settings": {}, "reason": reason, "warnings": warnings}]
