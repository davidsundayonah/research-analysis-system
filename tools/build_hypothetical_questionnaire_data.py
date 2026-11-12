"""Build respondent-level practice data from the supplied aggregate questionnaire counts."""

from pathlib import Path

import pandas as pd


def expand_counts(counts: list[int]) -> list[int]:
    """Expand Strongly Agree, Agree, Disagree, Strongly Disagree counts to 4..1."""
    return [value for response, count in zip((4, 3, 2, 1), counts) for value in [response] * count]


def main() -> None:
    rows = 200
    age = [1] * 35 + [2] * 100 + [3] * 45 + [4] * 20
    gender = [1] * 90 + [2] * 110
    level = [1] * 45 + [2] * 50 + [3] * 40 + [4] * 35 + [5] * 30
    item_counts = {
        "B1": [120, 60, 15, 5],
        "B2": [100, 70, 20, 10],
        "B3": [110, 65, 20, 5],
        "B4": [105, 70, 20, 5],
        "B5": [105, 70, 20, 5],
        "C1": [90, 75, 25, 10],
        "C2": [60, 70, 45, 25],
        "C3": [85, 80, 25, 10],
        "C4": [95, 70, 25, 10],
        "C5": [80, 85, 25, 10],
        "D1": [110, 70, 15, 5],
        "D2": [65, 75, 40, 20],
        "D3": [100, 75, 20, 5],
        "D4": [90, 65, 25, 20],
        "D5": [130, 55, 10, 5],
    }
    data = {"RespondentID": range(1, rows + 1), "AgeGroup": age, "Gender": gender, "StudyLevel": level}
    data.update({name: expand_counts(counts) for name, counts in item_counts.items()})
    dataframe = pd.DataFrame(data)
    output = Path(__file__).resolve().parents[1] / "hypothetical_hypertension_questionnaire.csv"
    dataframe.to_csv(output, index=False)
    print(f"Created {output} with {len(dataframe)} respondents and {len(dataframe.columns)} variables.")


if __name__ == "__main__":
    main()
