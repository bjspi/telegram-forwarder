"""Logging infrastructure and creation of runtime directories."""

from __future__ import annotations
import logging
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from .settings import LOG_RETENTION_DAYS, LOGS_DIR, SESSION_DIR


def ensure_runtime_directories() -> None:
    """Creates directories used by logs and runtime state."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    migrate_legacy_session_files()


def migrate_legacy_session_files() -> None:
    """Moves old root-level Pyrogram session files into the session directory."""
    for pattern in ("*.session", "*.session-journal"):
        for legacy_path in Path.cwd().glob(pattern):
            if not legacy_path.is_file():
                continue
            target_path = SESSION_DIR / legacy_path.name
            if target_path.exists():
                try:
                    if legacy_path.read_bytes() == target_path.read_bytes():
                        legacy_path.unlink()
                except OSError:
                    pass
                continue
            try:
                legacy_path.replace(target_path)
            except OSError as exc:
                raise RuntimeError(
                    f"Legacy session file {legacy_path} could not be moved to {target_path}. "
                    "Is the bot still running in another process?"
                ) from exc


class DailyLogFileHandler(logging.FileHandler):
    """Writes one log file per day and deletes files older than the retention window."""

    def __init__(self, logs_dir: Path, retention_days: int, prefix: str = "bot") -> None:
        self.logs_dir = logs_dir
        self.retention_days = max(0, retention_days)
        self.prefix = prefix
        self.current_date = datetime.now().date()
        super().__init__(self._path_for_date(self.current_date), encoding="utf-8")
        self.cleanup_old_logs()

    def _path_for_date(self, day: date) -> Path:
        """Returns the log file path for one date."""
        return self.logs_dir / f"{self.prefix}_{day:%Y-%m-%d}.log"

    def _extract_log_date(self, path: Path) -> date | None:
        """Extracts the date encoded in bot_YYYY-MM-DD.log filenames."""
        stem_prefix = f"{self.prefix}_"
        if not path.name.startswith(stem_prefix) or path.suffix != ".log":
            return None
        date_text = path.stem[len(stem_prefix):]
        try:
            return datetime.strptime(date_text, "%Y-%m-%d").date()
        except ValueError:
            return None

    def cleanup_old_logs(self) -> None:
        """Deletes daily log files older than the configured retention window."""
        cutoff_date = datetime.now().date() - timedelta(days=self.retention_days)
        for path in self.logs_dir.glob(f"{self.prefix}_*.log"):
            log_date = self._extract_log_date(path)
            if log_date is None or log_date >= cutoff_date:
                continue
            try:
                path.unlink()
            except OSError:
                pass

    def _rollover_if_needed(self) -> None:
        """Switches to today's log file after midnight."""
        today = datetime.now().date()
        if today == self.current_date:
            return
        self.current_date = today
        if self.stream:
            self.stream.close()
            self.stream = None
        self.baseFilename = os.path.abspath(os.fspath(self._path_for_date(today)))
        self.stream = self._open()
        self.cleanup_old_logs()

    def emit(self, record: logging.LogRecord) -> None:
        """Emits a record to the current day's file."""
        self._rollover_if_needed()
        super().emit(record)


def configure_logging() -> None:
    """Initializes application logging to stdout and file."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            DailyLogFileHandler(LOGS_DIR, LOG_RETENTION_DAYS),
        ],
    )
    logging.getLogger("apscheduler").setLevel(logging.WARNING)
