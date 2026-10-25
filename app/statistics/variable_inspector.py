import pandas as pd
import numpy as np


class VariableInspector:

    def __init__(self, dataframe):
        self.dataframe = dataframe

    # =========================================================
    # INSPECT ALL VARIABLES
    # =========================================================

    def inspect(self):
        variables = []

        for column in self.dataframe.columns:

            series = self.dataframe[column]

            information = self.inspect_variable(
                column,
                series
            )

            variables.append(
                information
            )

        return variables

    # =========================================================
    # INSPECT ONE VARIABLE
    # =========================================================

    def inspect_variable(
        self,
        name,
        series
    ):

        variable_type = self.detect_type(
            series
        )

        measure = self.detect_measure(
            series
        )

        missing_count = int(
            series.isna().sum()
        )

        unique_count = int(
            series.nunique(
                dropna=True
            )
        )

        result = {
            "name": name,
            "label": name,
            "type": variable_type,
            "measure": measure,
            "missing": missing_count,
            "unique": unique_count,
            "count": int(
                series.count()
            ),
            "value_labels": self.infer_value_labels(name, series),
        }

        # -----------------------------------------------------
        # Numeric information
        # -----------------------------------------------------

        if pd.api.types.is_numeric_dtype(
            series
        ):

            result["minimum"] = self.safe_numeric(
                series.min()
            )

            result["maximum"] = self.safe_numeric(
                series.max()
            )

            result["mean"] = self.safe_numeric(
                series.mean()
            )

            result["std"] = self.safe_numeric(
                series.std()
            )

        else:

            result["minimum"] = None
            result["maximum"] = None
            result["mean"] = None
            result["std"] = None

        return result

    @staticmethod
    def infer_value_labels(name, series):
        """Return safe display labels for the common coded gender field.

        The source values are never changed: both ``1/2`` and ``Male/Female``
        remain valid inputs. Labels are only metadata used by Variable View.
        Unknown values are left unlabeled rather than guessed.
        """
        if str(name).strip().casefold() not in {"gender", "sex"}:
            return {}
        labels = {}
        for value in series.dropna().unique():
            token = str(value).strip().casefold()
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                numeric = None
            if token in {"male", "m", "man"} or numeric == 1:
                labels[str(value)] = "Male"
            elif token in {"female", "f", "woman"} or numeric == 2:
                labels[str(value)] = "Female"
            else:
                return {}
        return labels

    # =========================================================
    # DETECT TYPE
    # =========================================================

    def detect_type(
        self,
        series
    ):

        if pd.api.types.is_bool_dtype(
            series
        ):
            return "Boolean"

        if pd.api.types.is_numeric_dtype(
            series
        ):
            return "Numeric"

        if pd.api.types.is_datetime64_any_dtype(
            series
        ):
            return "Date"

        return "Text"

    # =========================================================
    # DETECT MEASUREMENT LEVEL
    # =========================================================

    def detect_measure(
        self,
        series
    ):

        # -----------------------------------------------------
        # Boolean
        # -----------------------------------------------------

        if pd.api.types.is_bool_dtype(
            series
        ):
            return "Nominal"

        # -----------------------------------------------------
        # Text
        # -----------------------------------------------------

        if not pd.api.types.is_numeric_dtype(
            series
        ):
            return "Nominal"

        clean = series.dropna()

        if len(clean) == 0:
            return "Unknown"

        unique_values = clean.nunique()

        # -----------------------------------------------------
        # Binary numeric variable
        # -----------------------------------------------------

        if unique_values == 2:
            return "Nominal"

        # -----------------------------------------------------
        # Likert-style variable
        # -----------------------------------------------------

        if (
            unique_values <= 7
            and clean.min() >= 1
            and clean.max() <= 7
        ):
            return "Ordinal"

        # -----------------------------------------------------
        # Small categorical numeric variable
        # -----------------------------------------------------

        if unique_values <= 10:
            return "Ordinal"

        # -----------------------------------------------------
        # Continuous variable
        # -----------------------------------------------------

        return "Scale"

    # =========================================================
    # SAFE NUMERIC VALUE
    # =========================================================

    def safe_numeric(
        self,
        value
    ):

        if pd.isna(value):
            return None

        if isinstance(
            value,
            (np.integer,)
        ):
            return int(value)

        if isinstance(
            value,
            (np.floating,)
        ):
            return float(value)

        return value
