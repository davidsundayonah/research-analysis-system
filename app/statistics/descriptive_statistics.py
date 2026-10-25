import pandas as pd
import numpy as np


class DescriptiveStatistics:

    def __init__(self, dataframe):
        """
        Initialize the descriptive statistics engine.

        Parameters
        ----------
        dataframe : pandas.DataFrame
            Dataset to analyze.
        """

        if not isinstance(dataframe, pd.DataFrame):
            raise TypeError(
                "dataframe must be a pandas DataFrame."
            )

        self.dataframe = dataframe.copy()

    # =========================================================
    # INTERNAL HELPERS
    # =========================================================

    def _validate_variable(self, variable):
        """
        Check that a variable exists in the dataset.
        """

        if variable not in self.dataframe.columns:
            raise ValueError(
                f"Variable '{variable}' does not exist."
            )

    def _numeric_series(self, variable):
        """
        Convert a variable to numeric values.

        Invalid values are converted to NaN.
        """

        self._validate_variable(variable)

        return pd.to_numeric(
            self.dataframe[variable],
            errors="coerce"
        )

    # =========================================================
    # NUMERIC SUMMARY
    # =========================================================

    def numeric_summary(self, variables=None):
        """
        Generate descriptive statistics for numeric variables.

        Returns
        -------
        pandas.DataFrame
        """

        if variables is None:
            variables = self.dataframe.columns.tolist()

        results = []

        for variable in variables:

            if variable not in self.dataframe.columns:
                continue

            series = pd.to_numeric(
                self.dataframe[variable],
                errors="coerce"
            )
            invalid = int((self.dataframe[variable].notna() & series.isna()).sum())

            valid = series.dropna()

            if len(valid) == 0:
                continue

            mode_values = valid.mode()

            if len(mode_values) > 0:
                mode = mode_values.iloc[0]
            else:
                mode = np.nan

            results.append({
                "Variable": variable,

                "N": int(valid.count()),

                "Missing": int(
                    series.isna().sum()
                ),

                "Invalid": invalid,

                "Mean": round(
                    valid.mean(),
                    3
                ),

                "Median": round(
                    valid.median(),
                    3
                ),

                "Mode": round(
                    mode,
                    3
                ) if pd.notna(mode) else np.nan,

                "Std. Deviation": round(
                    valid.std(),
                    3
                ),

                "Variance": round(
                    valid.var(),
                    3
                ),

                "Minimum": round(
                    valid.min(),
                    3
                ),

                "Maximum": round(
                    valid.max(),
                    3
                ),

                "Range": round(
                    valid.max() - valid.min(),
                    3
                ),

                "Skewness": round(
                    valid.skew(),
                    3
                ) if len(valid) >= 3 else np.nan,

                "Kurtosis": round(
                    valid.kurt(),
                    3
                ) if len(valid) >= 4 else np.nan,

                "Q1": round(
                    valid.quantile(0.25),
                    3
                ),

                "Q2": round(
                    valid.quantile(0.50),
                    3
                ),

                "Q3": round(
                    valid.quantile(0.75),
                    3
                ),
            })

        return pd.DataFrame(results)

    # =========================================================
    # SINGLE VARIABLE SUMMARY
    # =========================================================

    def variable_summary(self, variable):
        """
        Generate a detailed summary for one variable.
        """

        self._validate_variable(variable)

        series = pd.to_numeric(
            self.dataframe[variable],
            errors="coerce"
        )
        invalid = int((self.dataframe[variable].notna() & series.isna()).sum())

        valid = series.dropna()

        if len(valid) == 0:
            return {
                "Variable": variable,
                "N": 0,
                "Missing": int(series.isna().sum()),
                "Invalid": invalid,
                "Mean": np.nan,
                "Median": np.nan,
                "Mode": np.nan,
                "Std. Deviation": np.nan,
                "Variance": np.nan,
                "Minimum": np.nan,
                "Maximum": np.nan,
                "Range": np.nan,
                "Skewness": np.nan,
                "Kurtosis": np.nan,
                "Q1": np.nan,
                "Q2": np.nan,
                "Q3": np.nan,
            }

        mode_values = valid.mode()

        mode = (
            mode_values.iloc[0]
            if len(mode_values) > 0
            else np.nan
        )

        return {
            "Variable": variable,

            "N": int(valid.count()),

            "Missing": int(
                series.isna().sum()
            ),

            "Invalid": invalid,

            "Mean": round(
                valid.mean(),
                3
            ),

            "Median": round(
                valid.median(),
                3
            ),

            "Mode": round(
                mode,
                3
            ) if pd.notna(mode) else np.nan,

            "Std. Deviation": round(
                valid.std(),
                3
            ),

            "Variance": round(
                valid.var(),
                3
            ),

            "Minimum": round(
                valid.min(),
                3
            ),

            "Maximum": round(
                valid.max(),
                3
            ),

            "Range": round(
                valid.max() - valid.min(),
                3
            ),

            "Skewness": round(
                valid.skew(),
                3
            ) if len(valid) >= 3 else np.nan,

            "Kurtosis": round(
                valid.kurt(),
                3
            ) if len(valid) >= 4 else np.nan,

            "Q1": round(
                valid.quantile(0.25),
                3
            ),

            "Q2": round(
                valid.quantile(0.50),
                3
            ),

            "Q3": round(
                valid.quantile(0.75),
                3
            ),
        }

    # =========================================================
    # FREQUENCY TABLE
    # =========================================================

    def frequency_table(self, variable):
        """
        Generate a frequency table.

        Columns:
        - Value
        - Frequency
        - Percent
        - Valid Percent
        - Cumulative Percent
        """

        self._validate_variable(variable)

        series = self.dataframe[variable]

        total = len(series)

        valid_series = series.dropna()

        valid_total = len(valid_series)

        frequencies = (
            series
            .value_counts(
                dropna=False
            )
        )

        results = []

        cumulative_valid = 0

        for value, frequency in frequencies.items():

            is_missing = pd.isna(value)

            if is_missing:

                label = "Missing"

                percent = (
                    frequency / total * 100
                    if total > 0
                    else 0
                )

                valid_percent = np.nan

                cumulative_percent = np.nan

            else:

                label = value

                percent = (
                    frequency / total * 100
                    if total > 0
                    else 0
                )

                valid_percent = (
                    frequency / valid_total * 100
                    if valid_total > 0
                    else 0
                )

                cumulative_valid += valid_percent

                cumulative_percent = cumulative_valid

            results.append({

                "Value": label,

                "Frequency": int(
                    frequency
                ),

                "Percent": round(
                    percent,
                    2
                ),

                "Valid Percent": (
                    round(
                        valid_percent,
                        2
                    )
                    if pd.notna(valid_percent)
                    else np.nan
                ),

                "Cumulative Percent": (
                    round(
                        cumulative_percent,
                        2
                    )
                    if pd.notna(
                        cumulative_percent
                    )
                    else np.nan
                ),
            })

        return pd.DataFrame(
            results,
            columns=[
                "Value",
                "Frequency",
                "Percent",
                "Valid Percent",
                "Cumulative Percent",
            ],
        )

    # =========================================================
    # MULTIPLE FREQUENCY TABLES
    # =========================================================

    def frequency_tables(self, variables):
        """
        Generate frequency tables for multiple variables.

        Returns
        -------
        dict
            Dictionary where keys are variable names and
            values are frequency DataFrames.
        """

        tables = {}

        for variable in variables:

            tables[variable] = (
                self.frequency_table(
                    variable
                )
            )

        return tables

    # =========================================================
    # MODE
    # =========================================================

    def mode(self, variable):
        """
        Return the mode(s) of a variable.

        Returns
        -------
        pandas.Series
        """

        self._validate_variable(variable)

        series = self.dataframe[
            variable
        ].dropna()

        if len(series) == 0:
            return pd.Series(
                dtype="float64"
            )

        return series.mode()

    # =========================================================
    # PERCENTILES
    # =========================================================

    def percentiles(
        self,
        variable,
        percentiles=None
    ):
        """
        Calculate requested percentiles.

        Example
        -------
        percentiles(
            "Age",
            [10, 25, 50, 75, 90]
        )
        """

        if percentiles is None:
            percentiles = [
                10,
                25,
                50,
                75,
                90
            ]

        series = self._numeric_series(
            variable
        ).dropna()

        if len(series) == 0:
            return {}

        results = {}

        for percentile in percentiles:

            if not 0 <= percentile <= 100:
                raise ValueError(
                    "Percentiles must be between "
                    "0 and 100."
                )

            results[
                f"P{percentile}"
            ] = round(
                series.quantile(
                    percentile / 100
                ),
                3
            )

        return results

    # =========================================================
    # MISSING VALUE SUMMARY
    # =========================================================

    def missing_summary(self):
        """
        Generate a missing-value summary for
        every variable.
        """

        results = []

        total_rows = len(
            self.dataframe
        )

        for variable in self.dataframe.columns:

            missing = int(
                self.dataframe[
                    variable
                ].isna().sum()
            )

            valid = (
                total_rows - missing
            )

            missing_percentage = (
                missing / total_rows * 100
                if total_rows > 0
                else 0
            )

            valid_percentage = (
                valid / total_rows * 100
                if total_rows > 0
                else 0
            )

            results.append({

                "Variable": variable,

                "Valid": valid,

                "Missing": missing,

                "Valid Percent": round(
                    valid_percentage,
                    2
                ),

                "Missing Percent": round(
                    missing_percentage,
                    2
                ),
            })

        return pd.DataFrame(results)

    # =========================================================
    # DATASET OVERVIEW
    # =========================================================

    def dataset_overview(self):
        """
        Return a high-level overview of the dataset.
        """

        numeric_columns = (
            self.dataframe
            .select_dtypes(
                include=np.number
            )
            .columns
        )

        categorical_columns = (
            self.dataframe
            .select_dtypes(
                exclude=np.number
            )
            .columns
        )

        return {

            "Rows": int(
                len(self.dataframe)
            ),

            "Columns": int(
                len(
                    self.dataframe.columns
                )
            ),

            "Numeric Variables": int(
                len(numeric_columns)
            ),

            "Categorical Variables": int(
                len(categorical_columns)
            ),

            "Missing Cells": int(
                self.dataframe
                .isna()
                .sum()
                .sum()
            ),

            "Complete Rows": int(
                self.dataframe
                .dropna()
                .shape[0]
            ),

            "Duplicate Rows": int(
                self.dataframe
                .duplicated()
                .sum()
            ),
        }

    # =========================================================
    # NUMERIC VARIABLES
    # =========================================================

    def numeric_variables(self):
        """
        Return a list of numeric variables.
        """

        return (
            self.dataframe
            .select_dtypes(
                include=np.number
            )
            .columns
            .tolist()
        )

    # =========================================================
    # CATEGORICAL VARIABLES
    # =========================================================

    def categorical_variables(self):
        """
        Return a list of categorical variables.
        """

        return (
            self.dataframe
            .select_dtypes(
                exclude=np.number
            )
            .columns
            .tolist()
        )

    # =========================================================
    # FULL DESCRIPTIVE REPORT
    # =========================================================

    def full_report(self):
        """
        Generate a complete descriptive-statistics report.

        Returns
        -------
        dict
        """

        numeric_vars = (
            self.numeric_variables()
        )

        categorical_vars = (
            self.categorical_variables()
        )

        coded_categorical_vars = [
            variable
            for variable in numeric_vars
            if self.dataframe[variable].nunique(dropna=True) <= 10
        ]

        frequency_vars = list(dict.fromkeys(
            categorical_vars + coded_categorical_vars
        ))

        return {

            "overview":
                self.dataset_overview(),

            "numeric_summary":
                self.numeric_summary(
                    numeric_vars
                ),

            "missing_summary":
                self.missing_summary(),

            "frequency_tables":
                self.frequency_tables(
                    frequency_vars
                ),
        }
