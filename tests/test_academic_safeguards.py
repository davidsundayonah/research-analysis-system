import pandas as pd
import pytest

from app.security import SecureExport
from app.statistics.academic_statistics import (
    cronbach_alpha,
    exact_2x2_test,
    independent_t_power,
    missing_data_sensitivity,
    robust_regression_diagnostics,
    scale_score,
)


def test_secure_export_round_trip(tmp_path):
    security = SecureExport(tmp_path / "export.key")
    payload = b"confidential research result"
    encrypted = security.encrypt_bytes(payload)
    assert encrypted != payload
    assert security.decrypt_bytes(encrypted) == payload
    with pytest.raises(Exception):
        SecureExport(tmp_path / "other.key").decrypt_bytes(encrypted)


def test_power_and_missing_sensitivity_are_explicit():
    result = independent_t_power(0.5)
    assert result["group_1_n"] > 0
    sensitivity = missing_data_sensitivity(pd.DataFrame({"x": [1, None, 3], "y": [2, 4, 6]}), ["x", "y"])
    assert sensitivity["complete_cases"] == 2
    assert sensitivity["analysis_warning"] is True


def test_robust_regression_and_exact_2x2():
    data = pd.DataFrame({"x": range(10), "y": [0, 1, 2, 3, 4, 5, 6, 7, 8, 30], "a": ["yes"] * 5 + ["no"] * 5, "b": ["yes", "yes", "yes", "no", "no"] * 2})
    diagnostics = robust_regression_diagnostics(data, "x", "y")
    assert diagnostics["covariance"] == "HC3 heteroscedasticity-consistent standard errors"
    exact = exact_2x2_test(data, "a", "b")
    assert exact["test"] == "fisher_exact_2x2"


def test_scale_scoring_and_reliability():
    data = pd.DataFrame({"q1": [1, 2, 3, 4], "q2": [5, 4, 3, 2], "q3": [1, 2, 3, 4]})
    scored = scale_score(data, ["q1", "q2", "q3"], reverse_items=["q2"])
    assert scored["scores"].tolist() == [3, 6, 9, 12]
    reliability = cronbach_alpha(data, ["q1", "q2", "q3"])
    assert reliability["n"] == 4
    assert "not proof" in reliability["warning"]
