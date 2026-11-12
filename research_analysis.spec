
# PyInstaller configuration for the PySide6 desktop application.
from PyInstaller.utils.hooks import collect_submodules, collect_dynamic_libs

datas = [("README.md", ".")]
binaries = []

# Collect dynamically imported NumPy 2.x core modules.
numpy_hiddenimports = collect_submodules("numpy._core")

# Collect SciPy Python submodules.
scipy_hiddenimports = collect_submodules("scipy")

# SciPy's vendored array-api compatibility package is not discovered when
# collecting from the top-level scipy package, but scipy.linalg imports the
# NumPy FFT adapter during startup.
scipy_array_api_hiddenimports = collect_submodules(
    "scipy._external.array_api_compat.numpy"
)

# Explicitly include the compiled SciPy modules required at startup.
hiddenimports = [
    "matplotlib.backends.backend_qtagg",
    "scipy._cyutility",
    "scipy._lib._ccallback_c",
    *numpy_hiddenimports,
    *scipy_hiddenimports,
    *scipy_array_api_hiddenimports,
]

# Collect SciPy's compiled extension modules and associated libraries.
scipy_binaries = collect_dynamic_libs("scipy")
binaries.extend(scipy_binaries)

a = Analysis(
    ["app/main.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="ResearchAnalysis",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)
