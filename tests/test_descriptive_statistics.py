from io import StringIO
from pathlib import Path

import pandas as pd
import pytest

from app.statistics.descriptive_statistics import DescriptiveStatistics

DATA_FILE = "test_research_data.csv"


@pytest.fixture
def research_dataframe():
    # The checked-in fixture is an instructional brief containing the embedded
    # synthetic CSV. Production imports still require a real CSV file.
    lines = Path(DATA_FILE).read_text(encoding="utf-8").splitlines()
    header_index = next(i for i, line in enumerate(lines) if line.startswith("ID,"))
    csv_lines = [lines[header_index]]
    for line in lines[header_index + 1:]:
        if line.count(",") != 15 or not line.split(",", 1)[0].isdigit():
            break
        csv_lines.append(line)
    return pd.read_csv(StringIO("\n".join(csv_lines)))


@pytest.fixture
def statistics_engine(research_dataframe):
    return DescriptiveStatistics(research_dataframe)


def test_research_data_loads(research_dataframe):
    assert isinstance(research_dataframe, pd.DataFrame)
    assert len(research_dataframe) == 100
    assert len(research_dataframe.columns) == 16


def test_research_columns(research_dataframe):
    assert research_dataframe.columns.tolist() == [
        "ID", "Gender", "Age", "StudyLevel", "SM_Hours", "SM1", "SM2",
        "SM3", "SM4", "AD1", "AD2", "AD3", "AP1", "AP2", "AP3", "GPA",
    ]


def test_dataset_overview(statistics_engine):
    overview = statistics_engine.dataset_overview()
    assert overview["Rows"] == 100
    assert overview["Columns"] == 16
    assert overview["Numeric Variables"] == 16
    assert overview["Categorical Variables"] == 0


def test_numeric_variables(statistics_engine):
    variables = statistics_engine.numeric_variables()
    assert {"Age", "GPA", "SM1", "AP3"}.issubset(variables)
    assert len(variables) == 16


def test_age_summary(statistics_engine):
    result = statistics_engine.variable_summary("Age")
    assert result["N"] == 100
    assert result["Missing"] == 0
    assert result["Minimum"] == 18
    assert result["Maximum"] == 22
    assert result["Mean"] == 20


def test_gpa_summary(statistics_engine):
    result = statistics_engine.variable_summary("GPA")
    assert result["N"] == 100
    assert result["Missing"] == 0
    assert result["Minimum"] == 1.9
    assert result["Maximum"] == 4.9


def test_questionnaire_items(statistics_engine):
    result = statistics_engine.numeric_summary(["SM1", "SM2", "SM3", "SM4"])
    assert len(result) == 4
    assert (result["N"] == 100).all()
    assert (result["Missing"] == 0).all()


def test_gender_frequency_columns(statistics_engine):
    result = statistics_engine.frequency_table("Gender")
    assert {"Value", "Frequency", "Percent", "Valid Percent", "Cumulative Percent"}.issubset(result.columns)


def test_gender_counts(statistics_engine):
    result = statistics_engine.frequency_table("Gender")
    assert int(result.loc[result["Value"] == 1, "Frequency"].iloc[0]) == 50
    assert int(result.loc[result["Value"] == 2, "Frequency"].iloc[0]) == 50


def test_study_level_frequency(statistics_engine):
    assert len(statistics_engine.frequency_table("StudyLevel")) == 4


def test_missing_summary(statistics_engine):
    result = statistics_engine.missing_summary()
    assert len(result) == 16
    assert (result["Missing"] == 0).all()


def test_full_report(statistics_engine):
    report = statistics_engine.full_report()
    assert {"overview", "numeric_summary", "missing_summary", "frequency_tables"}.issubset(report)


def test_full_report_content(statistics_engine):
    report = statistics_engine.full_report()
    assert len(report["numeric_summary"]) == 16
    assert "Gender" in report["frequency_tables"]
    assert "StudyLevel" in report["frequency_tables"]
