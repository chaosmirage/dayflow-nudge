"""One structured log line per decision or event, on stderr.

The module keeps the package's own module name while every piece of logging
machinery comes from the standard library: Python 3 absolute imports
resolve ``import logging`` inside this file to the standard library module,
never to this file, because the package directory itself is never placed
on ``sys.path`` (the daemon runs as ``python3 -m dayflow_nudge`` from the
installation root).
"""

from __future__ import annotations

import logging
import sys

__all__ = ["log_event", "setup"]

LOGGER_NAME = "dayflow_nudge"

_LINE_FORMAT = "%(asctime)s %(levelname)s %(message)s"
_LEVELS = {"info": logging.INFO, "warning": logging.WARNING, "error": logging.ERROR}
_MISSING_VALUE = "-"


def setup() -> logging.Logger:
    """Configure the daemon's logging once at boot.

    Records go to stderr -- where the per-user agent definition collects
    them -- one line each, never a card body. Booting twice must not
    duplicate lines, so an already-configured logger is left as it is.
    """
    logger = logging.getLogger(LOGGER_NAME)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter(_LINE_FORMAT))
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger


def log_event(event: str, level: str = "info", **fields) -> None:
    """Emit exactly one structured line: ``event=<name> key=value ...``."""
    logger = logging.getLogger(LOGGER_NAME)
    logger.log(_LEVELS.get(level, logging.INFO), "event=%s%s", event, _render(fields))


def _render(fields: dict) -> str:
    if not fields:
        return ""
    rendered = " ".join(f"{name}={_format(value)}" for name, value in sorted(fields.items()))
    return " " + rendered


def _format(value) -> str:
    """One predictable spelling per value kind, safe on a single line."""
    if value is None:
        return _MISSING_VALUE
    if value is True:
        return "true"
    if value is False:
        return "false"
    text = str(value)
    if any(character.isspace() for character in text):
        return '"' + text.replace('"', "'") + '"'
    return text
