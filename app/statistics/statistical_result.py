from dataclasses import dataclass, field
import math


@dataclass
class StatisticalError:
    code: str
    message: str
    details: dict = field(default_factory=dict)

    def to_dict(self):
        return {
            "code": self.code,
            "message": self.message,
            "details": self.details.copy(),
        }


@dataclass
class StatisticalResult:
    test: str
    variables: list[str]
    sample_size: int | None = None
    statistic: float | None = None
    degrees_of_freedom: float | None = None
    p_value: float | None = None
    effect_size: object | None = None
    confidence_interval: tuple[float, float] | None = None
    assumptions: list[dict] = field(default_factory=list)
    decision: str | None = None
    interpretation: str | None = None
    status: str = "ok"
    error: StatisticalError | None = None
    missing_data: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    details: dict = field(default_factory=dict)

    def __post_init__(self):
        if not isinstance(self.test, str) or not self.test.strip():
            raise ValueError("test must be a non-empty string.")
        if not isinstance(self.variables, list) or any(
            not isinstance(variable, str) or not variable.strip()
            for variable in self.variables
        ):
            raise ValueError("variables must be a list of non-empty strings.")
        if self.status not in {"ok", "invalid_input", "error"}:
            raise ValueError("status must be 'ok', 'invalid_input', or 'error'.")
        if self.error is not None and not isinstance(self.error, StatisticalError):
            raise ValueError("error must be a StatisticalError or None.")
        if self.sample_size is not None and (
            isinstance(self.sample_size, bool)
            or not isinstance(self.sample_size, int)
            or self.sample_size < 0
        ):
            raise ValueError("sample_size must be a non-negative integer or None.")

        for field_name in ("statistic", "degrees_of_freedom", "p_value"):
            value = getattr(self, field_name)
            if value is not None and (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
            ):
                raise ValueError(f"{field_name} must be finite or None.")

        if self.degrees_of_freedom is not None and self.degrees_of_freedom <= 0:
            raise ValueError("degrees_of_freedom must be positive or None.")
        if self.p_value is not None and not 0 <= self.p_value <= 1:
            raise ValueError("p_value must be between 0 and 1.")
        if self.confidence_interval is not None:
            if len(self.confidence_interval) != 2:
                raise ValueError("confidence_interval must contain two bounds.")
            lower, upper = self.confidence_interval
            if not all(
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(value)
                for value in (lower, upper)
            ):
                raise ValueError("confidence interval bounds must be finite.")
            if lower > upper:
                raise ValueError("confidence interval lower bound exceeds upper bound.")
        if self.status in {"invalid_input", "error"} and self.error is None:
            raise ValueError("failed results must include a structured error.")
        if self.status == "ok" and self.error is not None:
            raise ValueError("successful results cannot include an error.")

    @classmethod
    def from_input_error(cls, test, variables, error):
        return cls(
            test=test,
            variables=list(variables),
            status="invalid_input",
            error=error,
        )

    def to_dict(self):
        return {
            "test": self.test,
            "variables": self.variables.copy(),
            "sample_size": self.sample_size,
            "statistic": self.statistic,
            "degrees_of_freedom": self.degrees_of_freedom,
            "p_value": self.p_value,
            "effect_size": self.effect_size,
            "confidence_interval": (
                list(self.confidence_interval)
                if self.confidence_interval is not None
                else None
            ),
            "assumptions": [assumption.copy() for assumption in self.assumptions],
            "decision": self.decision,
            "interpretation": self.interpretation,
            "status": self.status,
            "error": self.error.to_dict() if self.error is not None else None,
            "missing_data": self.missing_data.copy(),
            "warnings": self.warnings.copy(),
            "details": self.details.copy(),
        }
