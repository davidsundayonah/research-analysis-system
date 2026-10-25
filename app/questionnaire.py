"""Reusable questionnaire, codebook, validation, and template helpers.

The helpers in this module are intentionally independent of Qt so they can be
used by the desktop UI, imports, and tests alike.
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd


QUESTION_TYPES = {
    "short_text", "long_text", "integer", "decimal", "date", "datetime",
    "yes_no", "single_choice", "multiple_choice", "likert", "ordinal",
    "nominal", "identifier",
}
MEASURES = {"nominal", "ordinal", "scale", "identifier", "datetime", "text"}
DATA_TYPES = {"text", "integer", "decimal", "date", "datetime", "boolean"}


def safe_variable_name(value: str, existing: set[str] | None = None) -> str:
    """Return a stable machine-friendly name, adding a suffix on collision."""
    base = re.sub(r"[^A-Za-z0-9_]+", "_", str(value or "").strip()).strip("_") or "variable"
    if base[0].isdigit():
        base = f"v_{base}"
    existing = {str(name) for name in (existing or set())}
    candidate, counter = base, 2
    while candidate in existing:
        candidate = f"{base}_{counter}"
        counter += 1
    return candidate


def validate_question_definition(variable_name, question_type, data_type, measure, options):
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(variable_name or "")):
        raise ValueError("Variable name must start with a letter or underscore and contain only letters, numbers, and underscores.")
    if question_type not in QUESTION_TYPES:
        raise ValueError(f"Unsupported question type: {question_type}")
    if data_type not in DATA_TYPES:
        raise ValueError(f"Unsupported data type: {data_type}")
    if measure not in MEASURES:
        raise ValueError(f"Unsupported measurement level: {measure}")
    if question_type in {"single_choice", "multiple_choice", "likert", "ordinal", "nominal", "yes_no"} and not options:
        raise ValueError("Choice questions require at least one allowed option.")
    if question_type == "multiple_choice" and data_type != "text":
        raise ValueError("Multiple-choice responses are stored as a list of selected values and use text data type.")


def _question_dict(question):
    row = dict(question)
    import json
    for field in ("options_json", "missing_values_json"):
        row[field.removesuffix("_json")] = json.loads(row.get(field) or "[]")
    return row


def validate_responses(questions, responses):
    """Validate a partial respondent record without rejecting unanswered items."""
    cleaned, errors = {}, []
    by_name = {question["variable_name"]: _question_dict(question) for question in questions}
    unknown = set(responses) - set(by_name)
    errors.extend(f"Unknown variable: {name}" for name in sorted(unknown))
    for name, question in by_name.items():
        value = responses.get(name)
        if value is None or value == "":
            cleaned[name] = value
            continue
        options = question["options"]
        values = value if question["question_type"] == "multiple_choice" and isinstance(value, list) else [value]
        if options and any(str(item) not in {str(option.get("value", option)) for option in options} for item in values):
            errors.append(f"{name}: value is not an allowed response.")
            cleaned[name] = value
            continue
        try:
            if question["data_type"] == "integer":
                cleaned[name] = int(value)
            elif question["data_type"] == "decimal":
                cleaned[name] = float(value)
            elif question["data_type"] == "boolean":
                if isinstance(value, bool):
                    cleaned[name] = value
                elif str(value).strip().lower() in {"yes", "true", "1"}:
                    cleaned[name] = True
                elif str(value).strip().lower() in {"no", "false", "0"}:
                    cleaned[name] = False
                else:
                    raise ValueError
            elif question["question_type"] == "multiple_choice":
                cleaned[name] = list(value) if isinstance(value, list) else [value]
            else:
                cleaned[name] = str(value)
        except (TypeError, ValueError):
            errors.append(f"{name}: invalid {question['data_type']} value.")
            cleaned[name] = value
    return cleaned, errors


def blank_template_dataframe(questions, expected_sample_size=None, include_identifier=True):
    names = [question["variable_name"] for question in questions]
    if include_identifier and "Respondent_ID" not in names:
        names.insert(0, "Respondent_ID")
    rows = int(expected_sample_size or 0)
    return pd.DataFrame([[None] * len(names) for _ in range(rows)], columns=names)


def generate_blank_template(questions, output_path, expected_sample_size=None, include_identifier=True):
    """Write a blank CSV/XLSX template and return its path.

    XLSX templates include a Codebook sheet; CSV cannot carry metadata, so the
    caller can use :func:`codebook_dataframe` to export it separately.
    """
    output = Path(output_path)
    dataframe = blank_template_dataframe(questions, expected_sample_size, include_identifier)
    if output.suffix.lower() == ".csv":
        dataframe.to_csv(output, index=False)
    elif output.suffix.lower() == ".xlsx":
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            dataframe.to_excel(writer, index=False, sheet_name="Responses")
            codebook_dataframe(questions).to_excel(writer, index=False, sheet_name="Codebook")
    else:
        raise ValueError("Template format must be .csv or .xlsx.")
    return output


def codebook_dataframe(questions):
    import json
    records = []
    for question in questions:
        row = _question_dict(question)
        records.append({
            "variable_name": row["variable_name"], "label": row.get("label") or row["prompt"],
            "question_number": row.get("question_number", ""), "section": row.get("section", ""),
            "question_type": row["question_type"], "data_type": row["data_type"],
            "measure": row["measure"], "required": bool(row["required"]),
            "allowed_values": json.dumps(row["options"], ensure_ascii=False),
            "missing_values": json.dumps(row["missing_values"], ensure_ascii=False),
            "prompt": row["prompt"], "notes": row.get("notes", ""),
        })
    return pd.DataFrame(records)
