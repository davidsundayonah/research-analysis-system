import pandas as pd
import numpy as np
import pandas as pd


class DataCleaner:

    def __init__(self, dataframe):
        self.dataframe = dataframe.copy()

    # =========================================================
    # RENAME VARIABLE
    # =========================================================

    def rename_variable(
        self,
        old_name,
        new_name
    ):

        if old_name not in self.dataframe.columns:
            raise ValueError(
                f"Variable '{old_name}' does not exist."
            )

        if not new_name:
            raise ValueError(
                "New variable name cannot be empty."
            )

        if new_name in self.dataframe.columns:
            raise ValueError(
                f"Variable '{new_name}' already exists."
            )

        self.dataframe = self.dataframe.rename(
            columns={
                old_name: new_name
            }
        )

        return self.dataframe

    # =========================================================
    # RECODE VALUES
    # =========================================================

    def recode_values(
        self,
        variable,
        mapping,
        new_variable=None
    ):

        if variable not in self.dataframe.columns:
            raise ValueError(
                f"Variable '{variable}' does not exist."
            )

        target = (
            new_variable
            if new_variable
            else variable
        )

        self.dataframe[target] = (
            self.dataframe[variable]
            .replace(mapping)
        )

        return self.dataframe

    # =========================================================
    # DEFINE MISSING VALUES
    # =========================================================

    def define_missing_values(
        self,
        variable,
        missing_values
    ):

        if variable not in self.dataframe.columns:
            raise ValueError(
                f"Variable '{variable}' does not exist."
            )

        self.dataframe[variable] = (
            self.dataframe[variable]
            .replace(
                missing_values,
                np.nan
            )
        )

        return self.dataframe

    # =========================================================
    # REVERSE SCORE
    # =========================================================

    def reverse_score(
        self,
        variable,
        minimum=1,
        maximum=5,
        new_variable=None
    ):

        if variable not in self.dataframe.columns:
            raise ValueError(
                f"Variable '{variable}' does not exist."
            )

        target = (
            new_variable
            if new_variable
            else variable
        )

        self.dataframe[target] = (
            maximum
            + minimum
            - self.dataframe[variable]
        )

        return self.dataframe

    def create_range_groups(self, variable, ranges, new_variable):
        """Create labelled inclusive numeric bands without changing the source.

        ``ranges`` is a sequence of ``(lower, upper, label)`` tuples. Values
        outside the declared bands become missing in the new variable so that
        incomplete coverage is visible rather than silently misclassified.
        """
        if variable not in self.dataframe.columns:
            raise ValueError(f"Variable '{variable}' does not exist.")
        if not new_variable or new_variable in self.dataframe.columns:
            raise ValueError("Enter a new variable name that does not already exist.")
        if not ranges:
            raise ValueError("At least one numeric range is required.")

        numeric = pd.to_numeric(self.dataframe[variable], errors="coerce")
        grouped = pd.Series(pd.NA, index=self.dataframe.index, dtype="object")
        previous = None
        for lower, upper, label in ranges:
            lower, upper = float(lower), float(upper)
            if lower > upper:
                raise ValueError("Each range must start at or below its end.")
            if previous is not None and lower <= previous:
                raise ValueError("Ranges overlap or are not in ascending order.")
            mask = numeric.ge(lower) & numeric.le(upper)
            grouped.loc[mask] = label
            previous = upper

        self.dataframe[new_variable] = grouped
        return self.dataframe

    # =========================================================
    # COMPUTED VARIABLE
    # =========================================================

    def compute_variable(
        self,
        new_variable,
        variables,
        operation="mean"
    ):

        missing = [
            variable
            for variable in variables
            if variable not in self.dataframe.columns
        ]

        if missing:
            raise ValueError(
                f"Variables not found: {missing}"
            )

        if operation == "mean":

            self.dataframe[new_variable] = (
                self.dataframe[variables]
                .mean(axis=1)
            )

        elif operation == "sum":

            self.dataframe[new_variable] = (
                self.dataframe[variables]
                .sum(axis=1)
            )

        elif operation == "min":

            self.dataframe[new_variable] = (
                self.dataframe[variables]
                .min(axis=1)
            )

        elif operation == "max":

            self.dataframe[new_variable] = (
                self.dataframe[variables]
                .max(axis=1)
            )

        else:

            raise ValueError(
                f"Unsupported operation: {operation}"
            )

        return self.dataframe

    # =========================================================
    # DUPLICATES
    # =========================================================

    def find_duplicates(self):

        return self.dataframe[
            self.dataframe.duplicated(
                keep=False
            )
        ]

    # =========================================================
    # REMOVE DUPLICATES
    # =========================================================

    def remove_duplicates(self):

        self.dataframe = (
            self.dataframe
            .drop_duplicates()
            .reset_index(drop=True)
        )

        return self.dataframe

    # =========================================================
    # MISSING VALUE SUMMARY
    # =========================================================

    def missing_summary(self):

        summary = []

        for column in self.dataframe.columns:

            missing = int(
                self.dataframe[column]
                .isna()
                .sum()
            )

            total = len(
                self.dataframe
            )

            percentage = (
                missing / total * 100
                if total > 0
                else 0
            )

            summary.append(
                {
                    "variable": column,
                    "missing": missing,
                    "percentage": percentage,
                }
            )

        return summary

    # =========================================================
    # NUMERIC RANGE CHECK
    # =========================================================

    def find_out_of_range(
        self,
        variable,
        minimum,
        maximum
    ):

        if variable not in self.dataframe.columns:
            raise ValueError(
                f"Variable '{variable}' does not exist."
            )

        numeric = pd.to_numeric(
            self.dataframe[variable],
            errors="coerce"
        )

        mask = (
            (numeric < minimum)
            | (numeric > maximum)
        )

        return self.dataframe[
            mask
        ]

    # =========================================================
    # GET DATAFRAME
    # =========================================================

    def get_dataframe(self):

        return self.dataframe.copy()
