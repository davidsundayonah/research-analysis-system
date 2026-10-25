"""Explicit, reversible helpers for importing and protecting qualitative text."""

from pathlib import Path
import re


def import_transcript(path, encoding="utf-8"):
    path = Path(path)
    if path.suffix.lower() not in {".txt", ".md", ".rtf"}:
        raise ValueError("Transcript import supports .txt, .md, and .rtf files.")
    return path.read_text(encoding=encoding)


def anonymize_text(text):
    """Mask common direct identifiers; review is still required before sharing."""
    text = str(text)
    text = re.sub(r"[\w.+-]+@[\w-]+\.[\w.-]+", "[EMAIL REDACTED]", text)
    text = re.sub(r"(?<!\d)(?:\+?\d[\d ()-]{7,}\d)(?!\d)", "[PHONE REDACTED]", text)
    return text

