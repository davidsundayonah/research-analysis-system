from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
from docx import Document
from docx.enum.section import WD_ORIENT
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches, Pt, RGBColor
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from app.statistics.descriptive_statistics import DescriptiveStatistics
from app.statistics.interpretation_engine import InterpretationEngine
from app.statistics.statistical_workflow import StatisticalWorkflow
from app.statistics.table_generator import (
    GeneratedTable,
    TableGenerator,
    TableNumberingContext,
)


@dataclass
class ReportSection:
    title: str
    paragraphs: list[str] = field(default_factory=list)
    tables: list[GeneratedTable] = field(default_factory=list)
    source_question_id: int | None = None


@dataclass
class ChapterFourReport:
    project_id: int
    project_name: str
    title: str
    sections: list[ReportSection]
    source_analysis_ids: list[int] = field(default_factory=list)
    source_dataset_ids: list[int] = field(default_factory=list)
    source_schema_ids: list[int] = field(default_factory=list)
    qualitative_response_ids: list[int] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def preview_text(self):
        parts = [self.title]
        for section in self.sections:
            parts.append(f"\n{section.title}")
            parts.extend(section.paragraphs)
            for table in section.tables:
                parts.append(table.display_title)
                parts.append(" | ".join(table.columns))
                parts.extend(" | ".join(row) for row in table.rows)
                parts.extend(table.footnotes)
        if self.warnings:
            parts.append("\nReport warnings")
            parts.extend(f"- {warning}" for warning in self.warnings)
        return "\n".join(parts)


class ChapterFourGenerator:
    def __init__(self, database, table_generator=None, interpretation_engine=None):
        self.database = database
        self.table_generator = table_generator or TableGenerator()
        self.interpretation_engine = interpretation_engine or InterpretationEngine()

    def generate(self, project_id):
        project = self.database.get_project(project_id)
        if project is None:
            raise ValueError("Project does not exist.")

        datasets = self.database.get_project_datasets(project_id)
        data_by_id = {}
        dataset_warnings = {}
        for dataset in datasets:
            try:
                data_by_id[dataset["id"]] = self._read_dataset(dataset["file_path"])
            except (OSError, ValueError, ImportError, pd.errors.ParserError) as error:
                dataset_warnings[dataset["id"]] = (
                    f"Dataset '{dataset['filename']}' could not be loaded; freshness of analyses using it cannot be verified ({error})."
                )

        title = (
            project["research_title"].strip()
            if project["research_title"] and project["research_title"].strip()
            else project["name"]
        )
        sections = [ReportSection(
            title="Introduction",
            paragraphs=[
                f"This chapter presents findings for the research project '{project['name']}'.",
                f"Research title: {title}.",
                f"Researcher: {project['researcher'] or 'Not specified'}. Institution: {project['institution'] or 'Not specified'}. Department: {project['department'] or 'Not specified'}.",
                f"The configured significance level is {self._format_alpha(project['significance_level'])}.",
            ],
        )]
        warnings = list(dataset_warnings.values())
        numbering = TableNumberingContext(f"chapter-four:{project_id}")

        descriptive_section = ReportSection(
            title="Descriptive and demographic analysis",
        )
        current_dataset = (
            next((dataset for dataset in datasets if dataset["is_active"]), None)
            if datasets
            else None
        ) or (datasets[0] if datasets else None)
        current_dataframe = (
            data_by_id.get(current_dataset["id"])
            if current_dataset is not None
            else None
        )
        if current_dataframe is None:
            descriptive_section.paragraphs.append(
                "Descriptive and demographic tables are unavailable because no project dataset could be loaded."
            )
            if not datasets:
                warnings.append("No dataset is registered for this project.")
        else:
            report = DescriptiveStatistics(current_dataframe).full_report()
            report_id = f"project-{project_id}-dataset-{current_dataset['id']}"
            descriptive_section.tables.extend(
                self.table_generator.from_descriptive_report(
                    report,
                    report_id=report_id,
                    numbering=numbering,
                )
            )
            duplicate_rows = int(current_dataframe.duplicated().sum())
            missing_cells = int(current_dataframe.isna().sum().sum())
            invalid_numeric_values = int(
                report["numeric_summary"].get("Invalid", pd.Series(dtype="int64")).sum()
            )
            revision = current_dataset["revision_number"] or 1
            descriptive_section.paragraphs.append(
                f"Tables summarize dataset {current_dataset['id']} revision {revision}, the active immutable dataset snapshot. Frequency tables include categorical and low-cardinality variables; variable labels and substantive demographic meaning come from the source-column names."
            )
            if duplicate_rows:
                descriptive_section.paragraphs.append(
                    f"Data-quality review: {duplicate_rows} exact duplicate row(s) were detected. They were retained as observations and should be reviewed before interpretation."
                )
            if missing_cells:
                descriptive_section.paragraphs.append(
                    f"Data-quality review: {missing_cells} missing cell(s) were detected; each saved analysis records its own missing-data handling."
                )
            if invalid_numeric_values:
                descriptive_section.paragraphs.append(
                    f"Data-quality review: {invalid_numeric_values} non-missing value(s) could not be converted to numeric form and were excluded from numeric summaries. Review the Invalid column before publication."
                )
        sections.append(descriptive_section)

        questions = self.database.get_project_research_questions(project_id)
        source_analysis_ids = []
        for question in questions:
            section = ReportSection(
                title=f"Research question findings: {question['code']}",
                source_question_id=question["id"],
            )
            section.paragraphs.append(question["question"])
            section.paragraphs.append(
                f"Research design: {question['design_type']}. Proposed test: {question['proposed_test'] or 'Not specified'}."
            )

            hypotheses = self.database.get_research_question_hypotheses(
                project_id,
                question["id"],
            )
            if hypotheses:
                for hypothesis in hypotheses:
                    section.paragraphs.append(
                        f"H0: {hypothesis['null_hypothesis'].strip() or 'Unavailable'} H1: {hypothesis['alternative_hypothesis'].strip() or 'Unavailable'} Direction: {hypothesis['directionality']}."
                    )
            else:
                section.paragraphs.append("No hypothesis is linked to this research question.")

            runs = self.database.get_question_analysis_runs(project_id, question["id"])
            if not runs:
                section.paragraphs.append(
                    "No saved analysis is available for this research question; statistical findings are unavailable."
                )
                warnings.append(f"{question['code']} has no saved analysis runs.")
            for row in reversed(runs):
                run = self.database.decode_analysis_run(row)
                source_analysis_ids.append(run["id"])
                snapshot_warning = self._snapshot_warning(
                    run,
                    data_by_id,
                    dataset_warnings,
                )
                if current_dataset is not None and run["dataset_id"] != current_dataset["id"]:
                    revision_warning = (
                        f"Analysis run {run['id']} uses dataset {run['dataset_id']}, "
                        f"while the descriptive section uses active dataset {current_dataset['id']}. "
                        "Review revision alignment before publication."
                    )
                    warnings.append(revision_warning)
                    section.paragraphs.append(f"Revision warning: {revision_warning}")
                if snapshot_warning:
                    warnings.append(snapshot_warning)
                    section.paragraphs.append(
                        f"Historical analysis run {run['id']}: {snapshot_warning}"
                    )

                hypothesis_text = self._hypothesis_text(
                    hypotheses,
                    run.get("hypothesis_id"),
                )
                interpretation = self.interpretation_engine.interpret(
                    run,
                    hypothesis_text=hypothesis_text,
                )
                section.paragraphs.extend([
                    f"Analysis run {run['id']} ({run['actual_test']}, saved {run['created_at']}): {interpretation.finding}",
                    f"Research conclusion: {interpretation.conclusion}",
                ])
                section.paragraphs.extend(
                    f"Caveat: {caveat}"
                    for caveat in interpretation.caveats
                )
                section.tables.append(
                    self.table_generator.from_saved_run(
                        run,
                        numbering=numbering,
                    )
                )
            sections.append(section)

        guide = self.database.get_interview_guide(project_id)
        transcripts = self.database.get_interview_transcripts(project_id)
        qualitative_summary = self.database.get_qualitative_summary(project_id)
        codings = self.database.get_qualitative_codings(project_id)
        if guide or transcripts or qualitative_summary or codings:
            qualitative_section = ReportSection(title="Qualitative interview findings")
            qualitative_section.paragraphs.append(
                "This section presents manually stored and coded interview material. "
                "Themes and interpretations are based only on the analyst's saved codebook and excerpts; the software does not invent themes or claim automatic meaning."
            )
            if guide:
                qualitative_section.paragraphs.append(
                    f"Interview guide: {guide['title']}. The guide is stored with this project."
                )
            qualitative_section.paragraphs.append(
                f"Interview transcripts stored: {len(transcripts)}; coded excerpts stored: {len(codings)}."
            )
            for row in qualitative_summary:
                qualitative_section.paragraphs.append(
                    f"Theme '{row['theme']}', code '{row['code']}': {row['description'] or 'No description supplied'}. Coded excerpts: {row['coded_excerpts']}."
                )
                excerpts = [coding for coding in codings if coding['code'] == row['code']]
                for coding in excerpts[:3]:
                    qualitative_section.paragraphs.append(
                        f"Illustrative excerpt ({coding['participant_id']}): {coding['excerpt']}"
                    )
            sections.append(qualitative_section)

        open_ended = self.database.get_open_ended_responses(project_id)
        if open_ended:
            open_section = ReportSection(title="Open-ended questionnaire findings")
            open_section.paragraphs.append(
                "These responses are reproduced from saved paper-entry records. "
                "They are qualitative evidence and are not treated as statistically significant results."
            )
            for response in open_ended:
                open_section.paragraphs.append(
                    f"Response {response['respondent_id']} / {response['question_variable']} "
                    f"(source record {response['source_record_id'] or 'not specified'}): {response['response_text']}"
                )
            sections.append(open_section)

        themes = self.database.get_qualitative_themes(project_id, approved_only=True)
        if themes and (questions or current_dataframe is not None):
            integration = ReportSection(title="Mixed-methods integration")
            integration.paragraphs.append(
                "Approved qualitative themes are presented alongside quantitative findings. "
                "The relationship is descriptive and interpretive; quotations are not substitutes for numerical results."
            )
            for theme in themes:
                integration.paragraphs.append(
                    f"Theme '{theme['name']}': {theme['description'] or 'No description supplied'}"
                )
            sections.append(integration)

        summary_paragraphs = [
            f"The chapter includes {len(questions)} research question(s) and {len(source_analysis_ids)} saved analysis run(s).",
            "Statistical findings and interpretations are reproduced from saved analysis results. No historical analysis was recalculated or modified.",
        ]
        if warnings:
            summary_paragraphs.append(
                f"{len(set(warnings))} data or analysis availability warning(s) are listed for review."
            )
        sections.append(ReportSection("Summary of findings", summary_paragraphs))
        return ChapterFourReport(
            project_id=project_id,
            project_name=project["name"],
            title=title,
            sections=sections,
            source_analysis_ids=source_analysis_ids,
            source_dataset_ids=[dataset["id"] for dataset in datasets],
            source_schema_ids=[schema["id"] for schema in self.database.get_project_questionnaire_schemas(project_id)],
            qualitative_response_ids=[response["id"] for response in open_ended],
            warnings=list(dict.fromkeys(warnings)),
        )

    @staticmethod
    def _read_dataset(file_path):
        path = Path(file_path)
        extension = path.suffix.lower()
        if extension == ".csv":
            return pd.read_csv(path)
        if extension in {".xlsx", ".xls"}:
            return pd.read_excel(path)
        raise ValueError(f"Unsupported dataset extension '{extension}'.")

    @staticmethod
    def _hypothesis_text(hypotheses, hypothesis_id):
        for hypothesis in hypotheses:
            if hypothesis["id"] == hypothesis_id:
                null_text = hypothesis["null_hypothesis"].strip()
                alternative = hypothesis["alternative_hypothesis"].strip()
                return f"H0: {null_text or 'Unavailable'} H1: {alternative or 'Unavailable'}"
        return None

    @staticmethod
    def _snapshot_warning(run, data_by_id, dataset_warnings):
        dataset_id = run["dataset_id"]
        if dataset_id not in data_by_id:
            return dataset_warnings.get(
                dataset_id,
                f"Source dataset {dataset_id} is not registered in this project; the saved result is retained as historical.",
            )
        current_signature = StatisticalWorkflow.dataset_signature(
            data_by_id[dataset_id]
        )
        if current_signature != run["dataset_signature"]:
            return (
                f"Source dataset {dataset_id} no longer matches the saved analysis snapshot; "
                "the stored result and interpretation are unchanged."
            )
        return None

    @staticmethod
    def _format_alpha(alpha):
        return f"{alpha:g}" if alpha is not None else "unavailable"


class ChapterFourExporter:
    def export_docx(self, report, output_path):
        document = Document()
        for section in document.sections:
            section.orientation = WD_ORIENT.LANDSCAPE
            section.page_width, section.page_height = section.page_height, section.page_width
            section.top_margin = Inches(0.65)
            section.bottom_margin = Inches(0.65)
            section.left_margin = Inches(0.7)
            section.right_margin = Inches(0.7)

        normal = document.styles["Normal"]
        normal.font.name = "Calibri"
        normal.font.size = Pt(10)
        normal.font.color.rgb = RGBColor(35, 42, 52)

        heading = document.add_heading("CHAPTER FOUR: RESULTS AND DISCUSSION", level=0)
        heading.alignment = WD_ALIGN_PARAGRAPH.CENTER
        document.add_paragraph(report.title, style="Subtitle")
        document.add_paragraph(f"Project: {report.project_name} (ID {report.project_id})")

        for section in report.sections:
            document.add_heading(section.title, level=1)
            for paragraph in section.paragraphs:
                document.add_paragraph(paragraph)
            for table in section.tables:
                caption = document.add_paragraph(style="Caption")
                caption.add_run(table.display_title).bold = True
                word_table = document.add_table(rows=1, cols=len(table.columns))
                word_table.style = "Light Shading Accent 1"
                word_table.autofit = True
                for column_index, column in enumerate(table.columns):
                    cell = word_table.rows[0].cells[column_index]
                    cell.text = str(column)
                    cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
                    for run in cell.paragraphs[0].runs:
                        run.bold = True
                for row in table.rows:
                    cells = word_table.add_row().cells
                    for column_index, value in enumerate(row):
                        cells[column_index].text = str(value)
                        cells[column_index].vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
                for footnote in table.footnotes:
                    note = document.add_paragraph(footnote)
                    for run in note.runs:
                        run.italic = True
                        run.font.size = Pt(9)
                source_text = self._source_text(table)
                if source_text:
                    note = document.add_paragraph(source_text)
                    for run in note.runs:
                        run.italic = True
                        run.font.size = Pt(8)

        if report.warnings:
            document.add_heading("Data and interpretation warnings", level=1)
            for warning in report.warnings:
                document.add_paragraph(warning, style="List Bullet")
        document.core_properties.title = f"Chapter Four - {report.project_name}"
        document.core_properties.subject = "Research results and discussion"
        document.save(output_path)
        return Path(output_path)

    def export_xlsx(self, report, output_path):
        workbook = Workbook()
        overview = workbook.active
        overview.title = "Overview"
        overview.append(["Chapter Four", report.title])
        overview.append(["Project", report.project_name])
        overview.append(["Project ID", report.project_id])
        overview.append(["Saved analysis run IDs", ", ".join(map(str, report.source_analysis_ids)) or "None"])
        overview.append(["Data integrity", "Saved statistical results are not recalculated or modified."])
        self._style_sheet(overview)

        section_sheets = {
            "Descriptive and demographic analysis": "Descriptive",
            "Summary of findings": "Summary",
        }
        question_sheet_names = {}
        for index, section in enumerate(report.sections, start=1):
            if section.source_question_id is not None:
                question_sheet_names[section.source_question_id] = self._unique_sheet_name(
                    workbook,
                    f"RQ{index - 2}",
                )

        for section in report.sections:
            sheet_name = (
                question_sheet_names[section.source_question_id]
                if section.source_question_id is not None
                else section_sheets.get(section.title, self._unique_sheet_name(workbook, section.title))
            )
            sheet = workbook.create_sheet(sheet_name)
            sheet.append([section.title])
            for paragraph in section.paragraphs:
                sheet.append([paragraph])
            if section.tables:
                sheet.append([])
            for table in section.tables:
                sheet.append([table.display_title])
                source_text = self._source_text(table)
                if source_text:
                    sheet.append([source_text])
                sheet.append(table.columns)
                for row in table.rows:
                    sheet.append([self._excel_value(value) for value in row])
                for footnote in table.footnotes:
                    sheet.append([f"Note: {footnote}"])
                sheet.append([])
            self._style_sheet(sheet)

        if report.warnings:
            warnings = workbook.create_sheet("Warnings")
            warnings.append(["Report warnings"])
            for warning in report.warnings:
                warnings.append([warning])
            self._style_sheet(warnings)

        workbook.properties.title = f"Chapter Four - {report.project_name}"
        workbook.properties.subject = "Traceable research results and tables"
        workbook.save(output_path)
        return Path(output_path)

    @staticmethod
    def _source_text(table):
        source = table.source
        if source.get("type") == "analysis_run":
            return (
                f"Source run {source.get('run_id')}; project {source.get('project_id')}; "
                f"question {source.get('question_id')}; hypothesis {source.get('hypothesis_id')}; "
                f"dataset {source.get('dataset_id')}; signature {source.get('dataset_signature')}"
            )
        return "; ".join(f"{key}: {value}" for key, value in source.items())

    @staticmethod
    def _excel_value(value):
        if value == "Not available":
            return value
        return value

    @staticmethod
    def _unique_sheet_name(workbook, requested):
        cleaned = "".join(character for character in requested if character not in "[]:*?/\\")[:31] or "Sheet"
        base = cleaned
        counter = 2
        while cleaned in workbook.sheetnames:
            suffix = f"_{counter}"
            cleaned = f"{base[:31 - len(suffix)]}{suffix}"
            counter += 1
        return cleaned

    @staticmethod
    def _style_sheet(sheet):
        sheet.freeze_panes = "A2"
        sheet.sheet_view.showGridLines = False
        header_fill = PatternFill("solid", fgColor="1F4E78")
        for cell in sheet[1]:
            cell.font = Font(color="FFFFFF", bold=True)
            cell.fill = header_fill
            cell.alignment = Alignment(vertical="center", wrap_text=True)
        for column_cells in sheet.columns:
            column_letter = get_column_letter(column_cells[0].column)
            max_length = max(
                (len(str(cell.value)) for cell in column_cells if cell.value is not None),
                default=10,
            )
            sheet.column_dimensions[column_letter].width = min(max(max_length + 2, 12), 60)
        for row in sheet.iter_rows():
            for cell in row:
                cell.alignment = Alignment(vertical="top", wrap_text=True)
