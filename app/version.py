"""Read the application version from the project metadata."""

from __future__ import annotations

from pathlib import Path
import sys
import tomllib


def get_application_version() -> str:
    """Return the version from pyproject.toml in source and frozen builds."""
    if getattr(sys, "frozen", False):
        project_root = Path(sys._MEIPASS)
    else:
        project_root = Path(__file__).resolve().parents[1]
    metadata_path = project_root / "pyproject.toml"
    with metadata_path.open("rb") as metadata_file:
        return str(tomllib.load(metadata_file)["project"]["version"])
