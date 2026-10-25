from dataclasses import dataclass, field
import math


@dataclass
class InterpretationResult:
    source_run_id: int | None
    test: str
    finding: str
    conclusion: str
    significance_status: str
    alpha: float | None
    hypothesis_text: str | None = None
    caveats: list[str] = field(default_factory=list)
    unavailable_fields: list[str] = field(default_factory=list)

    def to_dict(self):
        return {
            "source_run_id": self.source_run_id,
            "test": self.test,
            "finding": self.finding,
            "conclusion": self.conclusion,
            "significance_status": self.significance_status,
            "alpha": self.alpha,
            "hypothesis_text": self.hypothesis_text,
            "caveats": self.caveats.copy(),
            "unavailable_fields": self.unavailable_fields.copy(),
        }


class InterpretationEngine:
    SUPPORTED_TESTS = {
        "descriptive_analysis",
        "independent_t_test",
        "paired_t_test",
        "one_way_anova",
        "chi_square_test",
        "pearson_correlation",
        "spearman_correlation",
        "linear_regression",
    }

    def interpret(self, saved_run, hypothesis_text=None):
        if not isinstance(saved_run, dict):
            raise TypeError("saved_run must be a decoded saved-run dictionary or result dictionary.")

        is_run = isinstance(saved_run.get("result"), dict)
        result = saved_run["result"] if is_run else saved_run
        settings = saved_run.get("settings") or {} if is_run else {}
        parameters = settings.get("parameters") or {}
        details = result.get("details") or {}
        test = saved_run.get("actual_test") if is_run else None
        test = test or result.get("test", "unknown")
        source_run_id = saved_run.get("id") if is_run else None
        alpha = self._valid_probability(
            parameters.get("alpha", details.get("alpha")),
            allow_zero=False,
        )
        p_value = self._valid_probability(result.get("p_value"))
        significance_status = self._significance_status(p_value, alpha)
        caveats = []
        unavailable = []

        if result.get("status", "ok") != "ok":
            error = result.get("error") or {}
            message = error.get("message", "The stored result is not a successful analysis.")
            caveats.append(message)
            finding = "This analysis does not have a valid stored statistical result."
            unavailable.extend(["statistic", "p_value", "effect_size"])
            conclusion = self._conclusion(significance_status, hypothesis_text)
            return InterpretationResult(
                source_run_id,
                test,
                finding,
                conclusion,
                significance_status,
                alpha,
                hypothesis_text,
                caveats,
                unavailable,
            )

        if p_value is None:
            unavailable.append("p_value")
        if alpha is None:
            unavailable.append("alpha")
            caveats.append(
                "The saved significance level is unavailable; statistical significance cannot be classified."
            )
        if p_value is None:
            caveats.append("The saved p-value is unavailable; statistical significance cannot be classified.")

        variables = result.get("variables") or []
        if test == "descriptive_analysis":
            finding = "The dataset was summarized with descriptive tables; no inferential test was needed."
            caveats.append(
                "Descriptive summaries describe the observed data; a hypothesis decision was not applicable."
            )
            caveats.extend(str(item) for item in result.get("warnings", []))
            return InterpretationResult(
                source_run_id=source_run_id,
                test=test,
                finding=finding,
                conclusion=(
                    "No statistical-significance decision was required because this was a descriptive analysis."
                ),
                significance_status="not_applicable",
                alpha=None,
                hypothesis_text=hypothesis_text,
                caveats=list(dict.fromkeys(caveats)),
                unavailable_fields=[],
            )
        elif test == "independent_t_test":
            finding = self._independent_t(result, variables, p_value, alpha, unavailable)
        elif test == "paired_t_test":
            finding = self._paired_t(result, variables, p_value, alpha, unavailable)
        elif test == "one_way_anova":
            finding = self._anova(result, p_value, alpha, unavailable, caveats)
        elif test == "chi_square_test":
            finding = self._chi_square(result, variables, p_value, alpha, unavailable, caveats)
        elif test in {"pearson_correlation", "spearman_correlation"}:
            finding = self._correlation(test, result, variables, p_value, alpha, unavailable, caveats)
        elif test == "linear_regression":
            finding = self._regression(result, variables, p_value, alpha, unavailable, caveats)
        else:
            finding = f"No interpretation rule is available for '{test}'."
            unavailable.append("test-specific interpretation")
            caveats.append("The stored values are preserved, but no supported rule was applied.")

        estimate_notes = self._estimate_notes(result)
        if estimate_notes:
            finding += " " + " ".join(estimate_notes)

        if not result.get("effect_size"):
            unavailable.append("effect_size")
            caveats.append("Effect-size information is unavailable; practical importance cannot be assessed from this result.")
        else:
            caveats.append(
                "Statistical significance does not establish practical importance; interpret estimates and effect sizes in the study context."
            )
        if result.get("confidence_interval") is None:
            unavailable.append("confidence_interval")

        caveats.extend(str(item) for item in result.get("warnings", []))
        caveats = list(dict.fromkeys(caveats))
        unavailable = list(dict.fromkeys(unavailable))
        conclusion = self._conclusion(significance_status, hypothesis_text)
        return InterpretationResult(
            source_run_id=source_run_id,
            test=test,
            finding=finding,
            conclusion=conclusion,
            significance_status=significance_status,
            alpha=alpha,
            hypothesis_text=hypothesis_text,
            caveats=caveats,
            unavailable_fields=unavailable,
        )

    @staticmethod
    def _valid_probability(value, allow_zero=True):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        if not math.isfinite(value):
            return None
        if allow_zero:
            return float(value) if 0 <= value <= 1 else None
        return float(value) if 0 < value < 1 else None

    @staticmethod
    def _significance_status(p_value, alpha):
        if p_value is None or alpha is None:
            return "unavailable"
        return "significant" if p_value < alpha else "not_significant"

    @staticmethod
    def _format(value, digits=3, trim_leading_zero=True):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        if not math.isfinite(value):
            return None
        formatted = f"{value:.{digits}f}"
        if trim_leading_zero and 0 <= value < 1:
            return formatted.replace("0.", ".", 1)
        return formatted

    @classmethod
    def _format_interval(cls, interval, trim_leading_zero=True):
        if not isinstance(interval, (list, tuple)) or len(interval) != 2:
            return None
        lower = cls._format(interval[0], trim_leading_zero=trim_leading_zero)
        upper = cls._format(interval[1], trim_leading_zero=trim_leading_zero)
        if lower is None or upper is None:
            return None
        return f"{lower} to {upper}"

    def _p_text(self, p_value):
        if p_value is None:
            return "p-value unavailable"
        if p_value < 0.001:
            return "p < .001"
        return f"p = {self._format(p_value)}"

    def _significance_phrase(self, p_value, alpha):
        status = self._significance_status(p_value, alpha)
        if status == "significant":
            return f"statistically significant at the saved significance level (α = {self._format(alpha)})"
        if status == "not_significant":
            return f"not statistically significant at the saved significance level (α = {self._format(alpha)})"
        return "statistical significance cannot be determined because the saved p-value or alpha is unavailable"

    def _independent_t(self, result, variables, p_value, alpha, unavailable):
        details = result.get("details") or {}
        groups = details.get("group_order") or []
        means = details.get("group_means") or []
        if len(groups) >= 2 and len(means) >= 2:
            if means[0] > means[1]:
                direction = f"The observed mean was higher for {groups[0]} than {groups[1]}"
            elif means[0] < means[1]:
                direction = f"The observed mean was lower for {groups[0]} than {groups[1]}"
            else:
                direction = f"The observed group means were equal for {groups[0]} and {groups[1]}"
        else:
            direction = "The direction of the group mean difference is unavailable"
            unavailable.append("group means or labels")
        statistic = self._format(result.get("statistic"))
        if statistic is None:
            unavailable.append("statistic")
        return (
            f"{direction}. The mean difference was {self._significance_phrase(p_value, alpha)} "
            f"({f't = {statistic}, ' if statistic is not None else ''}{self._p_text(p_value)})."
        )

    def _paired_t(self, result, variables, p_value, alpha, unavailable):
        details = result.get("details") or {}
        difference = details.get("mean_difference")
        if difference is None:
            unavailable.append("mean_difference")
            direction = "The direction and size of the paired mean difference are unavailable"
        elif difference > 0:
            names = " and ".join(variables[:2])
            direction = f"The first measurement ({names}) had a positive mean difference ({self._format(difference)})"
        elif difference < 0:
            direction = f"The first measurement had a negative mean difference ({self._format(difference)})"
        else:
            direction = "The observed mean paired difference was zero"
        return f"{direction}; the paired difference was {self._significance_phrase(p_value, alpha)} ({self._p_text(p_value)})."

    def _anova(self, result, p_value, alpha, unavailable, caveats):
        details = result.get("details") or {}
        group_count = len(details.get("group_order") or [])
        if not group_count:
            group_count = len(details.get("group_means") or [])
        if not group_count:
            unavailable.append("group count")
        if group_count:
            comparison = f"across {group_count} groups"
        else:
            comparison = "among the groups"
        if self._significance_status(p_value, alpha) == "significant":
            caveats.append("This is an omnibus ANOVA result; it does not identify which groups differ. Post-hoc comparisons are needed for pairwise conclusions.")
            evidence = f"At the saved significance level (α = {self._format(alpha)}), there was evidence that at least one group mean differed"
        elif self._significance_status(p_value, alpha) == "not_significant":
            evidence = f"At the saved significance level (α = {self._format(alpha)}), there was not statistically significant evidence of a group mean difference"
            caveats.append("A non-significant omnibus test does not establish that all group means are equal.")
        else:
            evidence = "Group mean significance could not be determined"
        statistic = self._format(result.get("statistic"))
        if statistic is None:
            unavailable.append("statistic")
        suffix = f" (F = {statistic}, {self._p_text(p_value)})" if statistic else f" ({self._p_text(p_value)})"
        return f"{evidence} {comparison}{suffix}."

    def _chi_square(self, result, variables, p_value, alpha, unavailable, caveats):
        if len(variables) < 2:
            unavailable.append("variables")
            pair = "the selected variables"
        else:
            pair = f"{variables[0]} and {variables[1]}"
        status = self._significance_status(p_value, alpha)
        if status == "significant":
            statement = f"There was statistically significant evidence of an association between {pair}"
        elif status == "not_significant":
            statement = f"There was not statistically significant evidence of an association between {pair}"
        else:
            statement = f"The association between {pair} could not be classified for statistical significance"
        statistic = self._format(result.get("statistic"))
        if statistic is None:
            unavailable.append("statistic")
        suffix = f" (χ² = {statistic}, {self._p_text(p_value)})" if statistic else f" ({self._p_text(p_value)})"
        caveats.append("A chi-square association does not, by itself, establish causation.")
        if alpha is not None:
            statement += f" at the saved significance level (α = {self._format(alpha)})"
        return statement + suffix + "."

    def _correlation(self, test, result, variables, p_value, alpha, unavailable, caveats):
        coefficient = result.get("statistic")
        if coefficient is None or not isinstance(coefficient, (int, float)) or not math.isfinite(coefficient):
            unavailable.append("correlation coefficient")
            direction = None
        elif coefficient > 0:
            direction = "positive association"
        elif coefficient < 0:
            direction = "negative association"
        else:
            direction = "zero estimated association"
        if len(variables) < 2:
            unavailable.append("variables")
            pair_text = "the variables"
        else:
            pair_text = f"{variables[0]} and {variables[1]}"
        coefficient_label = "r" if test == "pearson_correlation" else "rs"
        if test == "spearman_correlation":
            caveats.append("Spearman correlation describes rank association; it does not, by itself, establish causation.")
        else:
            caveats.append("Correlation does not, by itself, establish causation.")
        status = self._significance_status(p_value, alpha)
        if direction is None:
            return (
                f"The correlation direction and magnitude between {pair_text} are unavailable; "
                f"statistical significance could not be determined ({self._p_text(p_value)})."
            )
        if status == "unavailable":
            return (
                f"There was an estimated {direction} between {pair_text} "
                f"({coefficient_label} = {self._format(coefficient)}); statistical significance "
                f"could not be classified because saved alpha or p-value is unavailable ({self._p_text(p_value)})."
            )
        if status == "significant":
            description = f"There was a statistically significant {direction}"
            alpha_text = f"; α = {self._format(alpha)}"
        else:
            description = f"There was an estimated {direction}; this association was not statistically significant"
            alpha_text = f" at the saved significance level (α = {self._format(alpha)})"
        return (
            f"{description} between {pair_text} "
            f"({coefficient_label} = {self._format(coefficient)}, {self._p_text(p_value)}{alpha_text})."
        )

    def _regression(self, result, variables, p_value, alpha, unavailable, caveats):
        details = result.get("details") or {}
        effect = result.get("effect_size") or {}
        r_squared = effect.get("r_squared")
        if r_squared is None:
            unavailable.append("r_squared")
            fit_statement = "The proportion of outcome variation explained by the model is unavailable"
        else:
            fit_statement = f"The model explained {self._format(r_squared * 100, 1)}% of the observed outcome variation"
        predictor = variables[0] if variables else "the predictor"
        slope = details.get("slope")
        slope_p = self._valid_probability(details.get("slope_p_value"))
        slope_ci = details.get("slope_confidence_interval", result.get("confidence_interval"))
        if slope is None:
            unavailable.append("slope")
            coefficient_statement = "Individual predictor coefficient information is unavailable"
        else:
            coefficient_statement = f"The estimated coefficient for {predictor} was {self._format(slope, trim_leading_zero=False)}"
            formatted_ci = self._format_interval(slope_ci, trim_leading_zero=False)
            if formatted_ci is not None:
                coefficient_statement += f" (CI {formatted_ci})"
            else:
                unavailable.append("slope confidence interval")
        if slope_p is None:
            unavailable.append("slope_p_value")
            coefficient_statement += "; its individual p-value is unavailable"
        else:
            coefficient_statement += f"; its individual {self._p_text(slope_p)}"
        status = self._significance_status(p_value, alpha)
        if status == "significant":
            model_status = f"The overall model was statistically significant at the saved level (α = {self._format(alpha)})"
        elif status == "not_significant":
            model_status = f"The overall model was not statistically significant at the saved level (α = {self._format(alpha)})"
        else:
            model_status = "The overall model's statistical significance could not be determined"
            unavailable.append("model p_value or alpha")
        caveats.append("Regression estimates describe association/prediction under this model and do not, by themselves, establish causation.")
        caveats.append("Interpret coefficients with their confidence intervals, individual p-values, assumptions, and model specification; statistical significance alone does not establish practical importance.")
        return f"{model_status} ({self._p_text(p_value)}). {fit_statement}. {coefficient_statement}."

    @staticmethod
    def _conclusion(significance_status, hypothesis_text):
        if significance_status == "significant":
            conclusion = "The result provides statistical evidence against the null under the saved significance level; it does not prove the alternative hypothesis or establish practical importance."
        elif significance_status == "not_significant":
            conclusion = "There is insufficient evidence to reject the null hypothesis. This does not prove there is no effect or that groups/variables are equivalent."
        else:
            conclusion = "A research conclusion about statistical significance cannot be determined because required saved values are missing."
        if hypothesis_text:
            conclusion += f" Linked hypothesis: {hypothesis_text}"
        return conclusion

    def _estimate_notes(self, result):
        notes = []
        effect = result.get("effect_size") or {}
        effect_labels = {
            "cohens_d": "Cohen's d",
            "hedges_g": "Hedges' g",
            "cohens_dz": "Cohen's dz",
            "hedges_gz": "Hedges' gz",
            "eta_squared": "eta-squared",
            "omega_squared": "omega-squared",
            "cramers_v": "Cramer's V",
            "correlation": "correlation coefficient",
            "r_squared": "R-squared",
            "adjusted_r_squared": "adjusted R-squared",
        }
        estimates = [
            f"{effect_labels.get(key, key)} = {self._format(value)}"
            for key, value in effect.items()
            if self._format(value) is not None
        ]
        if estimates:
            notes.append("Stored effect estimate(s): " + ", ".join(estimates) + ".")

        interval = result.get("confidence_interval")
        formatted_interval = self._format_interval(interval)
        if formatted_interval is not None:
            details = result.get("details") or {}
            level = details.get("confidence_level")
            label = f"{self._format(level * 100, 0)}% " if isinstance(level, (int, float)) else ""
            notes.append(f"The stored {label}confidence interval was {formatted_interval}.")
        return notes
