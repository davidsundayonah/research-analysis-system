import pandas as pd
import pytest

from app.statistics.data_cleaner import DataCleaner
from app.ui.data_page import DataPage


def test_range_parser_accepts_inclusive_age_bands():
    assert DataPage.parse_ranges("1-10=1, 11-20=2") == [
        (1.0, 10.0, "1"),
        (11.0, 20.0, "2"),
    ]


def test_range_groups_preserve_source_and_label_new_variable():
    data = pd.DataFrame({"Age": [1, 10, 11, 20, 21, None]})
    cleaner = DataCleaner(data)
    result = cleaner.create_range_groups(
        "Age",
        [(1, 10, "1-10"), (11, 20, "11-20")],
        "Age_Group",
    )

    assert result["Age"].iloc[:5].tolist() == [1.0, 10.0, 11.0, 20.0, 21.0]
    assert result["Age"].iloc[5:].isna().all()
    assert result["Age_Group"].iloc[:4].tolist() == ["1-10", "1-10", "11-20", "11-20"]
    assert result["Age_Group"].iloc[4:].isna().all()


def test_range_groups_reject_overlap_and_invalid_syntax():
    with pytest.raises(ValueError, match="overlap"):
        DataCleaner(pd.DataFrame({"Age": [1]})).create_range_groups(
            "Age", [(1, 10, "A"), (10, 20, "B")], "Age_Group"
        )
    with pytest.raises(ValueError, match="Invalid range"):
        DataPage.parse_ranges("1 to 10=1")
