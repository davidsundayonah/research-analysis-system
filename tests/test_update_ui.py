import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QDesktopServices
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QMessageBox

from app.database.database import Database
from app.ui.main_window import MainWindow


@pytest.fixture
def update_window(tmp_path):
    app = QApplication.instance() or QApplication([])
    database = Database(tmp_path / "updates-ui.db")
    window = MainWindow(database)
    yield app, window
    window.close()
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    app.processEvents()
    database.close()


def test_update_checker_reports_no_new_stable_release(update_window, monkeypatch):
    _, window = update_window
    shown = []
    monkeypatch.setattr("app.ui.main_window.latest_release", lambda: {"available": False})
    monkeypatch.setattr(QMessageBox, "information", lambda *args: shown.append(args[2]))

    window.check_for_updates()

    assert shown == ["You are using the latest stable version."]


def test_update_download_and_launch_require_two_user_confirmations(update_window, monkeypatch, tmp_path):
    _, window = update_window
    answers = iter((QMessageBox.Yes, QMessageBox.No))
    prompts = []
    opened = []
    installer = tmp_path / "verified.exe"
    installer.write_bytes(b"verified test installer")
    monkeypatch.setattr("app.ui.main_window.latest_release", lambda: {"available": True, "version": "2.0.0", "notes": "Notes"})
    monkeypatch.setattr("app.ui.main_window.download_verified_installer", lambda *_args: installer)
    monkeypatch.setattr(QMessageBox, "question", lambda *args: (prompts.append(args[1]) or next(answers)))
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: opened.append(url))

    window.check_for_updates()

    assert prompts == ["Update available", "Installer verified"]
    assert opened == []


def test_update_checker_opens_only_after_explicit_launch_confirmation(update_window, monkeypatch, tmp_path):
    _, window = update_window
    answers = iter((QMessageBox.Yes, QMessageBox.Yes))
    opened = []
    installer = tmp_path / "verified.exe"
    installer.write_bytes(b"verified test installer")
    monkeypatch.setattr("app.ui.main_window.latest_release", lambda: {"available": True, "version": "2.0.0", "notes": "Notes"})
    monkeypatch.setattr("app.ui.main_window.download_verified_installer", lambda *_args: installer)
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: next(answers))
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: opened.append(url.toLocalFile()))

    window.check_for_updates()

    assert opened == [installer.resolve().as_posix()]


def test_update_network_errors_are_shown_without_launching(update_window, monkeypatch):
    _, window = update_window
    warnings = []
    opened = []
    monkeypatch.setattr("app.ui.main_window.latest_release", lambda: (_ for _ in ()).throw(TimeoutError("offline")))
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args[2]))
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: opened.append(url))

    window.check_for_updates()

    assert warnings and "offline" in warnings[0]
    assert opened == []
