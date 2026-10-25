"""Schema-aware CSV/XLSX import helpers.

The UI can use these pure functions to preview and review an import before it
creates a managed dataset snapshot. No columns or rows are discarded here.
"""

from __future__ import annotations

from pathlib import Path
import re

import pandas as pd

from app.questionnaire import validate_responses


def read_import_file(path, *, max_rows=2_000_000, max_bytes=250 * 1024 * 1024):
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"Import file does not exist: {path}")
    if path.stat().st_size > max_bytes:
        raise ValueError("Import file exceeds the configured safety limit.")
    if path.suffix.lower() == ".csv":
        dataframe = pd.read_csv(path, low_memory=False)
    elif path.suffix.lower() in {".xlsx", ".xls"}:
        dataframe = pd.read_excel(path)
    else:
        raise ValueError("Spreadsheet import supports CSV and XLSX/XLS files.")
    if len(dataframe) > max_rows:
        raise ValueError("Import exceeds the configured row limit.")
    if dataframe.columns.duplicated().any():
        raise ValueError("Import contains duplicate column names; rename them before mapping.")
    if any(not str(column).strip() for column in dataframe.columns):
        raise ValueError("Import contains an empty column name.")
    return dataframe


def suggest_column_mapping(columns, questions):
    """Suggest exact, normalized, and label-based mappings without forcing them."""
    question_rows = [dict(question) for question in questions]
    result = {}
    normalized = {re.sub(r"[^a-z0-9]", "", str(column).lower()): column for column in columns}
    for question in question_rows:
        name = question["variable_name"]
        label = question.get("label") or question.get("prompt") or ""
        if name in columns:
            result[name] = name
            continue
        candidates = [name, label, question.get("prompt", "")]
        match = next((normalized.get(re.sub(r"[^a-z0-9]", "", candidate.lower())) for candidate in candidates if candidate), None)
        if match is not None:
            result[name] = match
    return result


def inspect_import(dataframe, questions, mapping=None):
    """Return a reviewable import report; the input dataframe is not modified."""
    columns = [str(column) for column in dataframe.columns]
    mapping = dict(mapping or suggest_column_mapping(columns, questions))
    expected = [question["variable_name"] for question in questions]
    missing = [name for name in expected if name not in mapping]
    mapped_source = {source for source in mapping.values() if source}
    unexpected = [column for column in columns if column not in mapped_source]
    invalid_mappings = [name for name, source in mapping.items() if source not in columns]
    duplicate_sources = sorted({source for source in mapping.values() if list(mapping.values()).count(source) > 1})
    type_suggestions = {str(column): str(dataframe[column].dtype) for column in dataframe.columns}
    return {
        "row_count": len(dataframe),
        "column_count": len(columns),
        "columns": columns,
        "sample": dataframe.head(5).copy(),
        "mapping": mapping,
        "missing_expected": missing,
        "unexpected_columns": unexpected,
        "invalid_mappings": invalid_mappings,
        "type_suggestions": type_suggestions,
        "duplicate_sources": duplicate_sources,
        "can_import": not invalid_mappings and not duplicate_sources,
    }


def validate_import(dataframe, questions, mapping):
    """Validate mapped values and report row-level errors while preserving data."""
    report = inspect_import(dataframe, questions, mapping)
    errors = []
    mapped = {target: dataframe[source] for target, source in mapping.items() if source in dataframe.columns}
    for index in dataframe.index:
        responses = {target: values.loc[index] for target, values in mapped.items()}
        responses = {key: (None if pd.isna(value) else value) for key, value in responses.items()}
        _, row_errors = validate_responses(questions, responses)
        errors.extend({"row": int(index) + 1, "message": message} for message in row_errors)
    report["errors"] = errors
    report["invalid_row_count"] = len({error["row"] for error in errors})
    report["valid_row_count"] = len(dataframe) - report["invalid_row_count"]
    report["missing_counts"] = {str(column): int(dataframe[column].isna().sum()) for column in dataframe.columns}
    return report


def apply_import_mapping(dataframe, questions, mapping, *, include_unmapped=True):
    """Create an analysis dataframe after explicit mapping review.

    Mapped columns receive questionnaire variable names. Unexpected columns are
    retained with their original names by default so the caller must explicitly
    decide whether to ignore or define them as new variables.
    """
    report = inspect_import(dataframe, questions, mapping)
    if report["invalid_mappings"]:
        raise ValueError("Import mapping contains columns that do not exist.")
    result = pd.DataFrame(index=dataframe.index)
    used = set()
    for target, source in mapping.items():
        if source in dataframe.columns:
            result[target] = dataframe[source]
            used.add(source)
    if include_unmapped:
        for column in dataframe.columns:
            if column not in used:
                result[str(column)] = dataframe[column]
    return result
