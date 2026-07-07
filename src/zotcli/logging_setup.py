"""Logging configuration for zotcli.

Sets up a RotatingFileHandler writing to <zotcli-home>/logs/zot.log.

Rules:
- Default level: INFO.  When -v is active, bumped to DEBUG.
- The log directory is created lazily (only on first log line), so unit
  tests that don't enable writes don't pollute disk.
- Console output is never touched here — logging is strictly additive.
"""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

_MAX_BYTES = 1 * 1024 * 1024  # 1 MB
_BACKUP_COUNT = 3
_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"

# Flag to prevent double-initialisation
_handler_installed = False

logger = logging.getLogger("zotcli")


class _LazyRotatingFileHandler(RotatingFileHandler):
    """A RotatingFileHandler that resolves its path + creates its directory
    only on the first emit.

    Uses ``delay=True`` so the parent class never opens the stream during
    construction, then swaps ``baseFilename`` to the real path the first time
    we emit. This avoids re-running ``Handler.__init__`` (which would create a
    fresh ``self.lock`` and break acquire/release pairing inside ``handle()``).
    """

    def __init__(self, log_path_fn, **kwargs) -> None:
        # Construct as a normal RotatingFileHandler with a placeholder path.
        # delay=True guarantees no file is opened during __init__, so the
        # placeholder is never written to.
        super().__init__(
            filename=os.devnull,
            mode=kwargs.pop("mode", "a"),
            maxBytes=kwargs.pop("maxBytes", _MAX_BYTES),
            backupCount=kwargs.pop("backupCount", _BACKUP_COUNT),
            encoding=kwargs.pop("encoding", "utf-8"),
            delay=True,
        )
        self._log_path_fn = log_path_fn
        self._resolved = False

    def _resolve_path(self) -> bool:
        if self._resolved:
            return True
        try:
            log_path: Path = self._log_path_fn()
            log_path.parent.mkdir(parents=True, exist_ok=True)
            self.baseFilename = str(log_path)
            self._resolved = True
            return True
        except Exception:
            # Non-fatal: silently disable file logging if directory is not
            # writable (e.g., a read-only sandbox).
            return False

    def emit(self, record: logging.LogRecord) -> None:
        if not self._resolve_path():
            return
        super().emit(record)


def configure_logging(verbose: bool = False) -> None:
    """Install the rotating file handler on the root 'zotcli' logger.

    Safe to call multiple times — only the first call has an effect.

    Parameters
    ----------
    verbose:
        If True, sets the logger level to DEBUG; otherwise INFO.
    """
    global _handler_installed

    level = logging.DEBUG if verbose else logging.INFO
    logger.setLevel(level)

    if _handler_installed:
        # Just update the level in case verbosity changed
        for h in logger.handlers:
            h.setLevel(level)
        return

    # Lazy handler — does not create the log file/dir at import time
    from zotcli.paths import logs_path  # imported lazily to avoid side-effects

    handler = _LazyRotatingFileHandler(
        logs_path,
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter(_FORMAT))
    logger.addHandler(handler)
    logger.propagate = False
    _handler_installed = True
