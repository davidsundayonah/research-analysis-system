import pandas as pd

from app.statistics.descriptive_statistics import (
    DescriptiveStatistics,
)
from app.statistics.variable_inspector import VariableInspector


def test_engine_accepts_different_research_datasets():
    education_data = pd.DataFrame({
        "School": ["A", "B", "A", "C"],
        "Score": [60, 75, 80, 85],
    })

    business_data = pd.DataFrame({
        "Department": ["HR", "IT", "IT", "Sales"],
        "Revenue": [1200, 2500, 3000, 1800],
    })

    education_engine = DescriptiveStatistics(
        education_data
    )

    business_engine = DescriptiveStatistics(
        business_data
    )

    assert education_engine.variable_summary(
        "Score"
    )["Mean"] == 75

    assert business_engine.variable_summary(
        "Revenue"
    )["Mean"] == 2125

    assert "School" in (
        education_engine.frequency_tables(["School"])
    )

    assert "Department" in (
        business_engine.frequency_tables(["Department"])
    )


def test_engine_handles_different_column_names():
    data = pd.DataFrame({
        "Monthly_Expenses": [100, 200, 300],
        "Customer_Type": ["New", "Returning", "New"],
    })

    engine = DescriptiveStatistics(data)

    assert engine.variable_summary(
        "Monthly_Expenses"
    )["Mean"] == 200

    assert "New" in engine.frequency_table(
        "Customer_Type"
    )["Value"].tolist()


def test_engine_handles_missing_values():
    data = pd.DataFrame({
        "Score": [10, 20, None, 40],
        "Group": ["A", "B", None, "A"],
    })

    engine = DescriptiveStatistics(data)

    summary = engine.variable_summary("Score")

    assert summary["N"] == 3
    assert summary["Missing"] == 1

    frequencies = engine.frequency_table("Group")

    assert frequencies["Frequency"].sum() == 4


def test_variable_detection_respects_column_dtypes():
    data = pd.DataFrame({
        "Count": pd.Series([1, 2], dtype="int64"),
        "Rate": pd.Series([0.25, 0.75], dtype="float64"),
        "Optional_Count": pd.Series([1, None], dtype="Int64"),
        "Numeric_Text": ["1", "2"],
        "Group": ["control", "treatment"],
        "Enabled": [True, False],
        "Observed_At": pd.to_datetime([
            "2025-01-01",
            "2025-01-02",
        ]),
    })

    engine = DescriptiveStatistics(data)

    assert engine.numeric_variables() == [
        "Count",
        "Rate",
        "Optional_Count",
    ]
    assert engine.categorical_variables() == [
        "Numeric_Text",
        "Group",
        "Enabled",
        "Observed_At",
    ]


def test_numeric_text_can_be_summarized_without_being_detected_as_numeric():
    data = pd.DataFrame({
        "Score_Text": ["10", "invalid", None, "20"],
    })

    engine = DescriptiveStatistics(data)

    assert engine.numeric_variables() == []
    assert engine.categorical_variables() == ["Score_Text"]

    summary = engine.variable_summary("Score_Text")
    assert summary["N"] == 2
    assert summary["Missing"] == 2
    assert summary["Mean"] == 15


def test_empty_and_all_missing_columns_are_classified_and_summarized():
    data = pd.DataFrame({
        "Empty_Number": pd.Series(dtype="float64"),
        "Missing_Number": pd.Series([pd.NA, pd.NA], dtype="Float64"),
        "Missing_Label": pd.Series([None, None], dtype="object"),
    })

    engine = DescriptiveStatistics(data)

    assert engine.numeric_variables() == [
        "Empty_Number",
        "Missing_Number",
    ]
    assert engine.categorical_variables() == ["Missing_Label"]

    summary = engine.variable_summary("Missing_Number")
    assert summary["N"] == 0
    assert summary["Missing"] == 2


def test_empty_frequency_table_keeps_its_documented_columns():
    data = pd.DataFrame({
        "Group": pd.Series(dtype="object"),
    })

    result = DescriptiveStatistics(data).frequency_table("Group")

    assert result.columns.tolist() == [
        "Value",
        "Frequency",
        "Percent",
        "Valid Percent",
        "Cumulative Percent",
    ]
    assert result.empty


def test_full_report_frequencies_include_coded_categories_not_continuous_values():
    data = pd.DataFrame({
        "Group_Code": [1, 2] * 6,
        "Measurement": [float(value) for value in range(12)],
        "Region": ["north", "south", "north", "west"] * 3,
    })

    report = DescriptiveStatistics(data).full_report()

    assert set(report["frequency_tables"]) == {
        "Group_Code",
        "Region",
    }


def test_gender_accepts_readable_words_and_preserves_them_as_categories():
    data = pd.DataFrame({
        "Gender": ["Male", "Female", "male", "female", "Female"],
        "Score": [10, 20, 30, 40, 50],
    })
    engine = DescriptiveStatistics(data)
    frequencies = engine.frequency_table("Gender")

    assert set(frequencies["Value"]) == {"Male", "Female", "male", "female"}
    assert engine.categorical_variables() == ["Gender"]
    assert VariableInspector.infer_value_labels("Gender", data["Gender"]) == {
        "Male": "Male",
        "Female": "Female",
        "male": "Male",
        "female": "Female",
    }


def test_gender_codes_are_labeled_without_changing_source_values():
    data = pd.DataFrame({"Gender": [1, 2, 1, 2], "Score": [10, 20, 30, 40]})
    labels = VariableInspector.infer_value_labels("Gender", data["Gender"])

    assert labels == {"1": "Male", "2": "Female"}
    assert data["Gender"].tolist() == [1, 2, 1, 2]
