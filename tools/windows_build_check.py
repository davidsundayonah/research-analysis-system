"""Preflight checks for the Windows onedir build script."""

import importlib.util
import struct
import sys
import tomllib
from pathlib import Path


if sys.platform != "win32" or struct.calcsize("P") != 8:
    raise SystemExit("Build must run with 64-bit Windows Python to produce a Windows x64 application.")

required = ("PyInstaller", "PySide6", "numpy", "scipy", "matplotlib")
missing = [name for name in required if importlib.util.find_spec(name) is None]
if missing:
    raise SystemExit(
        "Missing build dependencies: "
        + ", ".join(missing)
        + ". Install requirements.txt and requirements-build.txt."
    )

metadata = tomllib.loads((Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8"))
print(metadata["project"]["version"])
