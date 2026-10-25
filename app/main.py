import sys

from PySide6.QtWidgets import QApplication

from app.logging_config import configure_logging, install_exception_hook
from app.ui.main_window import MainWindow


def main():
    logger = configure_logging()
    install_exception_hook(logger)
    app = QApplication(sys.argv)

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
