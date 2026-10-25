from pathlib import Path

import pytest

from app.document_extraction import extract_question_candidates, extract_questionnaire


def test_text_questionnaire_extraction_preserves_wording_and_warns_when_uncertain(tmp_path):
    path = tmp_path / "blank.txt"
    path.write_text("DEMOGRAPHICS\n1. What is your age?\n2. Select your sex: Male, Female, Prefer not to answer\n", encoding="utf-8")
    result = extract_questionnaire(path)
    assert result["source_type"] == "text"
    assert [question["prompt"] for question in result["questions"]] == ["What is your age?", "Select your sex"]
    assert result["questions"][0]["warning"]
    assert len(result["questions"][1]["options"]) == 3


def test_extraction_does_not_invent_questions(tmp_path):
    path = tmp_path / "instructions.txt"
    path.write_text("Please answer all questions honestly.", encoding="utf-8")
    with pytest.raises(ValueError, match="no questions were invented"):
        extract_questionnaire(path)


def test_candidate_extraction_is_empty_for_unstructured_text():
    assert extract_question_candidates("Title\nInstructions only") == []
