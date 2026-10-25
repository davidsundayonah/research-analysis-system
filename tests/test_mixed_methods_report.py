import pandas as pd

from app.database.database import Database
from app.reporting import ChapterFourGenerator, ChapterFourExporter


def test_mixed_methods_report_uses_saved_sources_and_real_open_ended_evidence(tmp_path):
    database = Database(tmp_path / "mixed.db")
    project = database.create_project("Mixed methods study", research_title="Service experience")
    csv_path = tmp_path / "responses.csv"
    pd.DataFrame({"Satisfaction": [3, 4, 5], "Group": ["A", "A", "B"]}).to_csv(csv_path, index=False)
    dataset = database.create_dataset(project, "responses.csv", str(csv_path), "csv", 3, 2)
    schema = database.create_questionnaire_schema(project, "Service form", expected_sample_size=3)
    database.add_questionnaire_question(schema, "Satisfaction", "Satisfaction", question_type="likert", data_type="integer", measure="ordinal", options=[{"value": 1}, {"value": 5}])
    record = database.create_paper_entry_record(project, schema, "R001")
    database.create_open_ended_response(project, "R001", "Comments", "The service was quick and clear", schema, record)
    database.create_qualitative_theme(project, "Clarity", "Participants described clear service communication.", approved=True)

    report = ChapterFourGenerator(database).generate(project)
    preview = report.preview_text()
    assert "The service was quick and clear" in preview
    assert "Mixed-methods integration" in preview
    assert report.source_dataset_ids == [dataset]
    assert report.source_schema_ids == [schema]
    assert report.qualitative_response_ids

    docx = tmp_path / "chapter-four.docx"
    xlsx = tmp_path / "chapter-four.xlsx"
    exporter = ChapterFourExporter()
    exporter.export_docx(report, docx)
    exporter.export_xlsx(report, xlsx)
    assert docx.is_file() and xlsx.is_file()
