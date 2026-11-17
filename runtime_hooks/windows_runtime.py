"""Keep writable caches in the user's profile and avoid external Qt plugins."""

from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile


if getattr(sys, "frozen", False):
    bundle_dir = Path(sys._MEIPASS)
    if "--packaging-self-test" in sys.argv:
        # The self-test must never initialize Matplotlib in the real profile.
        _self_test_temp = tempfile.TemporaryDirectory(prefix="ResearchAnalysis-SelfTest-Profile-")
        app_data = Path(_self_test_temp.name)
        os.environ["APPDATA"] = str(app_data)
    else:
        app_data = Path(os.environ.get("APPDATA", Path.home())) / "ResearchAnalysis"
    mpl_config = app_data / "matplotlib"
    mpl_config.mkdir(parents=True, exist_ok=True)
    os.environ["MPLCONFIGDIR"] = str(mpl_config)

    # Do not let another Python/Qt installation selected on the build machine
    # override the Qt libraries and plugins collected beside this executable.
    os.environ.pop("QT_PLUGIN_PATH", None)
    os.environ.pop("QT_QPA_PLATFORM_PLUGIN_PATH", None)
    os.environ.pop("PYTHONHOME", None)
    os.environ.pop("PYTHONPATH", None)

    system_root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    os.environ["PATH"] = os.pathsep.join(
        str(path)
        for path in (bundle_dir, system_root / "System32", system_root)
        if path.exists()
    )

    if hasattr(os, "add_dll_directory"):
        os.add_dll_directory(str(bundle_dir))
