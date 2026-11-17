# PyInstaller onedir configuration for the PySide6 desktop application.
from pathlib import Path
import tomllib

from PyInstaller.utils.hooks import collect_dynamic_libs, collect_submodules
from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo,
    StringFileInfo,
    StringStruct,
    StringTable,
    VarFileInfo,
    VarStruct,
    VSVersionInfo,
)


ROOT = Path(SPECPATH).resolve()
ICON = ROOT / "assets" / "research_analysis.ico"
APP_VERSION = tuple(int(part) for part in tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"].split("."))
if len(APP_VERSION) != 3:
    raise ValueError("pyproject.toml project.version must use MAJOR.MINOR.PATCH")
VERSION_FILE = ROOT / "build" / "research-analysis-version.txt"
VERSION_FILE.parent.mkdir(parents=True, exist_ok=True)
version_info = VSVersionInfo(
    ffi=FixedFileInfo(filevers=(*APP_VERSION, 0), prodvers=(*APP_VERSION, 0)),
    kids=[
        StringFileInfo([
            StringTable("040904B0", [
                StringStruct("CompanyName", "David Sunday Onah"),
                StringStruct("FileDescription", "Research Analysis System"),
                StringStruct("FileVersion", ".".join(map(str, APP_VERSION))),
                StringStruct("InternalName", "ResearchAnalysis"),
                StringStruct("OriginalFilename", "ResearchAnalysis.exe"),
                StringStruct("ProductName", "Research Analysis System"),
                StringStruct("ProductVersion", ".".join(map(str, APP_VERSION))),
            ])
        ]),
        VarFileInfo([VarStruct("Translation", [1033, 1200])]),
    ],
)
VERSION_FILE.write_text(str(version_info), encoding="utf-8")


def _runtime_module(module_name: str) -> bool:
    """Keep runtime modules, excluding dependency-owned test suites."""
    parts = module_name.split(".")
    return not any(
        part == "tests"
        or part == "testing"
        or part == "conftest"
        or part.startswith(("test_", "_test"))
        or part.endswith("_tests")
        for part in parts
    )


# Keep NumPy's dynamically imported core modules while omitting its test helpers.
numpy_hiddenimports = collect_submodules(
    "numpy._core",
    filter=_runtime_module,
)

# SciPy uses lazy imports extensively. Collect its runtime modules and compiled
# libraries, but do not put the third-party SciPy test suite in the installer.
scipy_hiddenimports = collect_submodules(
    "scipy",
    filter=_runtime_module,
)
scipy_array_api_hiddenimports = collect_submodules(
    "scipy._external.array_api_compat.numpy",
    filter=_runtime_module,
)

hiddenimports = [
    # The source tree uses an implicit namespace package (no app/__init__.py).
    # Explicitly include the updater module imported by the Help menu so the
    # installed build cannot lose update-checking functionality.
    "app.updates",
    "app.version",
    "matplotlib.backends.backend_qtagg",
    "scipy._cyutility",
    "scipy._lib._ccallback_c",
    *numpy_hiddenimports,
    *scipy_hiddenimports,
    *scipy_array_api_hiddenimports,
]

# PyInstaller's PySide6 and NumPy hooks collect their Qt plugins and numerical
# DLLs; SciPy's compiled DLLs are included explicitly for its lazy imports.
binaries = collect_dynamic_libs("scipy")
datas = [
    (str(ROOT / "README.md"), "."),
    (str(ROOT / "pyproject.toml"), "."),
    (str(ICON), "."),
]

a = Analysis(
    [str(ROOT / "app" / "main.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(ROOT / "runtime_hooks" / "windows_runtime.py")],
    excludes=[
        "pytest",
        "_pytest",
        "httpx",
        "fastapi",
        "starlette",
        "uvicorn",
        "multipart",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ResearchAnalysis",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=str(ICON),
    version=str(VERSION_FILE),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="ResearchAnalysis",
)
