"""Conservative extraction of questionnaire text into reviewable candidates."""

from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
import re


@dataclass
class ExtractedQuestion:
    prompt: str
    question_number: str = ""
    section: str = ""
    options: list[dict] | None = None
    confidence: float = 0.5
    warning: str = ""

    def as_dict(self):
        return asdict(self)


def read_document_text(path):
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"Questionnaire document does not exist: {path}")
    suffix = path.suffix.lower()
    if suffix == ".txt":
        return path.read_text(encoding="utf-8"), "text"
    if suffix == ".docx":
        from docx import Document
        return "\n".join(paragraph.text for paragraph in Document(path).paragraphs), "docx"
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError as error:
            raise ValueError("PDF extraction requires the optional pypdf package; no text was invented.") from error
        return "\n".join(page.extract_text() or "" for page in PdfReader(path).pages), "pdf"
    if suffix in {".jpg", ".jpeg", ".png"}:
        try:
            import pytesseract
            from PIL import Image
        except ImportError as error:
            raise ValueError("Image OCR requires optional pytesseract and Pillow packages; no text was invented.") from error
        return pytesseract.image_to_string(Image.open(path)), "ocr"
    raise ValueError("Supported questionnaire documents are TXT, DOCX, PDF, JPG, JPEG, and PNG.")


def extract_question_candidates(text):
    """Extract only text that resembles a numbered question; never invent wording."""
    candidates = []
    current_section = ""
    lines = [re.sub(r"\s+", " ", line).strip() for line in str(text).splitlines()]
    for line in lines:
        if not line:
            continue
        number = re.match(r"^(?:Q(?:uestion)?\s*)?(\d{1,3})[.)]:?\s+(.+)$", line, re.I)
        if number:
            prompt = number.group(2).strip()
            options = []
            if ":" in prompt and any(token in prompt.lower() for token in ("select", "choose", "tick", "rate")):
                prompt, option_text = prompt.split(":", 1)
                options = [{"value": option.strip(), "label": option.strip()} for option in re.split(r"[,;|]", option_text) if option.strip()]
            candidates.append(ExtractedQuestion(prompt, number.group(1), current_section, options or None, 0.9 if options else 0.75, "" if options else "Review question type and response choices."))
            continue
        if len(line) < 80 and not re.search(r"[?.]$", line) and line.isupper():
            current_section = line
    return candidates


def extract_questionnaire(path):
    text, source_type = read_document_text(path)
    questions = extract_question_candidates(text)
    if not questions:
        raise ValueError("No numbered question candidates were extracted. Create the questionnaire manually; no questions were invented.")
    return {"source_type": source_type, "questions": [question.as_dict() for question in questions], "raw_text": text}
