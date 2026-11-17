import sys
import os
import tempfile
import traceback
from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from app.logging_config import configure_logging, install_exception_hook
from app.ui.main_window import MainWindow


def _run_packaging_self_test() -> int:
    """Exercise bundled numerical, Qt, and charting runtimes on demand."""
    application = None
    diagnostic_file = None
    if sys.stdout is None or sys.stderr is None:
        diagnostic_path = Path(os.environ.get(
            "RESEARCH_ANALYSIS_SELF_TEST_LOG",
            Path(tempfile.gettempdir()) / "ResearchAnalysis-packaging-self-test.log",
        ))
        diagnostic_file = diagnostic_path.open("w", encoding="utf-8")
        sys.stdout = diagnostic_file
        sys.stderr = diagnostic_file
    try:
        with tempfile.TemporaryDirectory(prefix="ResearchAnalysis-SelfTest-") as isolated:
            os.environ["APPDATA"] = isolated
            from app.database.database import Database
            import numpy as np
            from scipy import stats
            from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
            from matplotlib.figure import Figure

            print("[PASS] NumPy imported", flush=True)
            if not np.array_equal(np.array([[1, 2], [3, 4]]) @ np.array([[1, 2], [3, 4]]), [[7, 10], [15, 22]]):
                raise RuntimeError("NumPy numerical operation failed")
            print("[PASS] NumPy numerical operation", flush=True)
            result = stats.ttest_1samp([1., 2., 3., 4., 5.], popmean=3.)
            if not np.isfinite(result.statistic) or not np.isfinite(result.pvalue):
                raise RuntimeError("SciPy representative calculation failed")
            print("[PASS] SciPy calculation", flush=True)
            application = QApplication([])
            print(f"[PASS] Qt initialized; platform={application.platformName()}", flush=True)
            if application.platformName().lower() != "windows":
                raise RuntimeError("Qt Windows platform plugin was not selected")
            figure = Figure()
            figure.subplots().plot([1, 2, 3], [2, 4, 3])
            canvas = FigureCanvasQTAgg(figure)
            canvas.draw()
            if canvas.width() <= 0 or canvas.height() <= 0:
                raise RuntimeError("Matplotlib Qt chart rendering returned an empty canvas")
            print("[PASS] Matplotlib Qt chart rendered", flush=True)
            icon = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1])) / "research_analysis.ico"
            if not icon.is_file():
                raise RuntimeError(f"Application icon resource is missing: {icon.name}")
            print("[PASS] Application icon resource", flush=True)
            database = Database()
            try:
                database.connection.execute("SELECT 1").fetchone()
                if not database.database_path.is_relative_to(Path(isolated).resolve()):
                    raise RuntimeError("Self-test database escaped its isolated temporary directory")
            finally:
                database.close()
            print("[PASS] Isolated database initialization", flush=True)
        return 0
    except Exception as error:
        print(f"[FAIL] {type(error).__name__}: {error}", file=sys.stderr, flush=True)
        traceback.print_exc()
        return 1
    finally:
        if application is not None:
            application.quit()
        if diagnostic_file is not None:
            diagnostic_file.close()


def _run_installer_smoke_test(action: str, token: str) -> int:
    """Exercise the installed app's real database and QSettings locations."""
    diagnostic_file = None
    if sys.stdout is None or sys.stderr is None:
        diagnostic_path = Path(os.environ.get(
            "RESEARCH_ANALYSIS_SELF_TEST_LOG",
            Path(tempfile.gettempdir()) / "ResearchAnalysis-installer-smoke-test.log",
        ))
        diagnostic_file = diagnostic_path.open("w", encoding="utf-8")
        sys.stdout = diagnostic_file
        sys.stderr = diagnostic_file
    try:
        if not token or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-" for character in token):
            raise ValueError("Installer smoke-test token contains unsupported characters")
        app_data = os.environ.get("APPDATA")
        if not app_data:
            raise RuntimeError("APPDATA is not available to the installed application")
        app_data_root = Path(app_data).resolve()
        from app.database.database import Database

        database = Database()
        try:
            database.connection.execute("SELECT 1").fetchone()
            expected_database = app_data_root / "ResearchAnalysis" / "research_analysis.db"
            if database.database_path != expected_database:
                raise RuntimeError(f"Database path is outside the expected user data directory: {database.database_path}")
        finally:
            database.close()
        print(f"[PASS] Database initialized under APPDATA: {expected_database}", flush=True)

        settings = QSettings("ResearchAnalysis", "ResearchAnalysis")
        key = f"installer-smoke/{token}"
        if action == "write":
            settings.setValue(key, "1.0.2-user-settings-survive-upgrade")
            settings.sync()
            if settings.status() != QSettings.NoError or settings.value(key) != "1.0.2-user-settings-survive-upgrade":
                raise RuntimeError("The application could not persist an installer smoke-test setting")
            print("[PASS] Application QSettings value persisted", flush=True)
        elif action == "verify":
            settings.sync()
            if settings.status() != QSettings.NoError or settings.value(key) != "1.0.2-user-settings-survive-upgrade":
                raise RuntimeError("Application settings did not survive the upgrade")
            print("[PASS] Application QSettings value survived upgrade", flush=True)
        elif action == "cleanup":
            settings.remove(key)
            settings.sync()
            if settings.status() != QSettings.NoError or settings.contains(key):
                raise RuntimeError("Could not remove the temporary installer smoke-test setting")
            print("[PASS] Temporary QSettings value removed", flush=True)
        else:
            raise ValueError(f"Unknown installer smoke-test action: {action}")
        return 0
    except Exception as error:
        print(f"[FAIL] {type(error).__name__}: {error}", file=sys.stderr, flush=True)
        traceback.print_exc()
        return 1
    finally:
        if diagnostic_file is not None:
            diagnostic_file.close()


def main():
    if "--packaging-self-test" in sys.argv:
        return _run_packaging_self_test()
    if "--installer-smoke-test" in sys.argv:
        index = sys.argv.index("--installer-smoke-test")
        if len(sys.argv) != index + 3:
            return _run_installer_smoke_test("invalid-arguments", "")
        return _run_installer_smoke_test(sys.argv[index + 1], sys.argv[index + 2])

    logger = configure_logging()
    install_exception_hook(logger)
    app = QApplication(sys.argv)

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    sys.exit(main())
