import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from app.database.database import Database
from app.reporting import ChapterFourGenerator
from app.ui.qualitative_page import QualitativePage
from app.qualitative_tools import anonymize_text, import_transcript
from app.statistics.academic_statistics import cohens_kappa


@pytest.fixture
def qualitative_context(tmp_path):
    database = Database(tmp_path / "qualitative.db")
    project_id = database.create_project("Mixed methods study")
    yield database, project_id
    database.close()


def test_interview_guide_transcript_code_and_coding_are_persisted(qualitative_context):
    database, project_id = qualitative_context
    guide_id = database.save_interview_guide(
        project_id,
        "Student interview guide",
        "1. What helps you study?\n2. What barriers do you face?",
    )
    transcript_id = database.create_interview_transcript(
        project_id, "P001", "p001.txt", "Transport costs make attendance difficult."
    )
    code_id = database.create_qualitative_code(
        project_id, "transport_barrier", "Access barriers", "Costs or distance affecting attendance."
    )
    coding_id = database.create_transcript_coding(
        project_id, transcript_id, code_id, "Transport costs make attendance difficult.", "Direct barrier statement."
    )

    assert database.get_interview_guide(project_id)["id"] == guide_id
    assert len(database.get_interview_transcripts(project_id)) == 1
    assert database.get_qualitative_codes(project_id)[0]["id"] == code_id
    assert database.get_qualitative_codings(project_id)[0]["id"] == coding_id
    summary = database.get_qualitative_summary(project_id)
    assert summary[0]["theme"] == "Access barriers"
    assert summary[0]["coded_excerpts"] == 1


def test_chapter_four_includes_saved_qualitative_findings(qualitative_context):
    database, project_id = qualitative_context
    transcript_id = database.create_interview_transcript(project_id, "P001", "p001.txt", "Supportive peers help.")
    code_id = database.create_qualitative_code(project_id, "peer_support", "Social support", "Peer encouragement.")
    database.create_transcript_coding(project_id, transcript_id, code_id, "Supportive peers help.")

    report = ChapterFourGenerator(database).generate(project_id)
    section = next(section for section in report.sections if section.title == "Qualitative interview findings")
    text = "\n".join(section.paragraphs)
    assert "Social support" in text
    assert "Supportive peers help." in text
    assert "does not invent themes" in text


def test_qualitative_page_loads_project_context(qualitative_context):
    database, project_id = qualitative_context
    app = QApplication.instance() or QApplication([])
    page = QualitativePage(database)
    page.set_project(project_id)
    assert page.project_id == project_id
    assert page.save_guide_button.isEnabled()
    page.deleteLater()
    app.processEvents()


def test_qualitative_versions_audit_coders_and_anonymisation(qualitative_context, tmp_path):
    database, project_id = qualitative_context
    database.save_interview_guide(project_id, "Guide", "Q1\nQ2\nQ3")
    database.save_interview_guide(project_id, "Guide", "Q1\nQ2\nQ3\nQ4")
    transcript_id = database.create_interview_transcript(project_id, "P1", "one.txt", "Email me at person@example.com")
    code_id = database.create_qualitative_code(project_id, "support", "Support")
    database.create_transcript_coding(project_id, transcript_id, code_id, "Support", coder="coder-a")
    assert database.get_interview_guide(project_id)["version"] == 2
    assert database.get_codebook_versions(project_id)
    assert any(row["entity"] == "transcript_coding" for row in database.get_qualitative_audit_log(project_id))
    assert database.get_qualitative_codings(project_id)[0]["coder"] == "coder-a"
    assert anonymize_text("person@example.com") == "[EMAIL REDACTED]"
    source = tmp_path / "transcript.txt"
    source.write_text("hello", encoding="utf-8")
    assert import_transcript(source) == "hello"
    assert cohens_kappa(["a", "b", "a"], ["a", "b", "b"]) == pytest.approx(0.4)
