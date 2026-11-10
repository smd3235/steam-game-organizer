"""Structured, component-tagged logging with size-based rotation.

AppLogger writes one line per call with a UTC timestamp, level, component tag,
and a correlation id so a single run's log can be followed end to end across
discovery, organize, rollback and audit. All writes are locked so threads do
not interleave, and a failed write is swallowed so logging never kills the run.

Logs rotate by size: when the active file exceeds MAX_BYTES it is renamed to
.1 (and .1 to .2, etc.) up to MAX_FILES, so a long-running PC never accumulates
an unbounded log file. A level threshold can be raised above DEBUG to suppress
noise in normal operation while keeping troubleshooting detail available.
"""

from pathlib import Path
from datetime import datetime, timezone
from contextlib import contextmanager
import threading
import uuid
import traceback
import sys
import json

LEVELS = {"DEBUG": 0, "INFO": 1, "WARN": 2, "ERROR": 3}


class AppLogger:
    MAX_BYTES = 5 * 1024 * 1024  # 5 MB per file
    MAX_FILES = 3  # active + 2 rotated

    def __init__(self, path: Path, level: str = "DEBUG", console: bool = False, json_format: bool = False):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._local = threading.local()
        self.level = LEVELS.get(level.upper(), LEVELS["DEBUG"])
        self.console = console
        self.json_format = json_format
        # Approximate bytes written since the last rotate check. _rotate() stats the file on every call,
        # which is wasteful during high-frequency logging (a scan emits hundreds of progress lines).
        # Track in memory and only stat when we might be near the size limit.
        self._bytes_since_rotate_check = 0

    def correlation_id(self):
        return uuid.uuid4().hex[:10].upper()

    @contextmanager
    def context(self, correlation_id):
        previous = getattr(self._local, "correlation_id", "")
        self._local.correlation_id = correlation_id
        try:
            yield correlation_id
        finally:
            self._local.correlation_id = previous

    def set_level(self, level: str):
        self.level = LEVELS.get(level.upper(), self.level)

    def _should_log(self, level: str) -> bool:
        return LEVELS.get(level.upper(), 0) >= self.level

    def _rotate(self):
        if not self.path.exists():
            return
        try:
            if self.path.stat().st_size < self.MAX_BYTES:
                return
        except OSError:
            return
        oldest = Path(f"{self.path}.{self.MAX_FILES}")
        try:
            oldest.unlink()
        except OSError:
            pass
        for n in range(self.MAX_FILES - 1, 0, -1):
            src = Path(f"{self.path}.{n}")
            dst = Path(f"{self.path}.{n + 1}")
            try:
                src.replace(dst)
            except OSError:
                pass
        try:
            self.path.replace(Path(f"{self.path}.1"))
        except OSError:
            pass

    def write(self, level, component, message, correlation_id=""):
        if not self._should_log(level):
            return
        correlation_id = correlation_id or getattr(self._local, "correlation_id", "")
        if self.json_format:
            entry = {
                "ts": datetime.now(timezone.utc).isoformat(),
                "level": level,
                "component": component,
                "corr": correlation_id or "-",
                "msg": message,
            }
            line = json.dumps(entry) + "\n"
        else:
            line = f"{datetime.now(timezone.utc).astimezone():%Y-%m-%d %H:%M:%S%z} [{level:<5}] [{component:<11}] [{correlation_id or '-'}] {message}\n"
        if self.console:
            try:
                print(line, end="")
            except OSError:
                pass
        # Track approximate bytes so _rotate() only stats the file periodically,
        # not on every write. A scan emitting hundreds of progress lines otherwise
        # stats the log file once per line for no benefit.
        line_bytes = len(line.encode("utf-8"))
        self._bytes_since_rotate_check += line_bytes
        if self._bytes_since_rotate_check >= self.MAX_BYTES // 10:
            self._rotate()
            self._bytes_since_rotate_check = 0
        with self._lock:
            try:
                with self.path.open("a", encoding="utf-8") as f:
                    f.write(line)
            except OSError:
                pass

    def debug(self, c, m, i=""):
        self.write("DEBUG", c, m, i)

    def info(self, c, m, i=""):
        self.write("INFO", c, m, i)

    def warning(self, c, m, i=""):
        self.write("WARN", c, m, i)

    def error(self, c, m, i=""):
        self.write("ERROR", c, m, i)

    def exception(self, c, m, exc, i=""):
        self.write("ERROR", c, f"{m} type={type(exc).__name__}: {exc}\n{traceback.format_exc()}", i)

    def install_excepthook(self):
        """Route uncaught exceptions through this logger instead of a default traceback."""
        previous = sys.excepthook

        def hooked(exc_type, exc_value, exc_traceback):
            self.error("EXCEPT", f"unhandled {exc_type.__name__}: {exc_value}\n{''.join(traceback.format_exception(exc_type, exc_value, exc_traceback))}")
            previous(exc_type, exc_value, exc_traceback)

        sys.excepthook = hooked
        return previous
