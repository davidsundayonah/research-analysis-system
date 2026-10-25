import logging
import os
import sys
from pathlib import Path


def configure_logging(database_path=None):
    if database_path is not None:
        log_dir = Path(database_path).parent / "logs"
    else:
        log_dir = Path(os.environ.get("APPDATA", Path.home() / ".local" / "share")) / "ResearchAnalysis" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[
            logging.FileHandler(log_dir / "research_analysis.log", encoding="utf-8"),
            logging.StreamHandler(sys.stderr),
        ],
        force=True,
    )
    return logging.getLogger("research_analysis")


def install_exception_hook(logger):
    def handle_exception(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        logger.critical("Unhandled application error", exc_info=(exc_type, exc_value, exc_traceback))

    sys.excepthook = handle_exception
