"""Runtime configuration read from the environment.

Configuration is environment variables only -- no config files, no
command-line flags. Exactly four variables are consulted, on every cycle,
and every missing or malformed value falls back to a sane default so a
broken environment can never crash a tick.
"""

from __future__ import annotations

import dataclasses
import os
from collections.abc import Mapping

__all__ = ["Config", "load_config"]

ENV_DISABLE = "DFN_DISABLE"
ENV_NOTIFIER = "DFN_NOTIFIER"
ENV_POLL_SECONDS = "DFN_POLL_SECONDS"
ENV_STYLE = "DFN_STYLE"

DISABLED_TOKEN = "1"
NOTIFIER_APPLET = "applet"
NOTIFIER_OSASCRIPT = "osascript"
# The environment token selecting the fallback channel is the short
# spelling; the Config value is the channel name the notifier compares.
NOTIFIER_FALLBACK_TOKEN = "oscript"
POLL_SECONDS = 60
STYLE_WINDOW = "window"
STYLE_NOTIFICATION = "notification"


@dataclasses.dataclass(frozen=True)
class Config:
    """One cycle's runtime configuration, re-read from scratch every tick.

    An immutable value: nothing downstream can cache or bend a cycle's
    settings, because the next cycle simply loads a fresh one.
    """

    disable: bool = False
    notifier: str = NOTIFIER_APPLET
    poll_seconds: int = POLL_SECONDS
    style: str = STYLE_WINDOW


def load_config(environ: Mapping[str, str] | None = None) -> Config:
    """Read the four DFN_* variables into a typed Config.

    The kill switch arms only on the exact token "1", so a malformed value
    can only ever leave nudging on. The notifier variable accepts the
    applet channel or the fallback token; anything else means the default
    channel. The poll must parse as a positive integer or the default poll
    wins, so the loop can never spin on a zero-second tick. The style
    selects the nudge surface: the centered self-dismissing window (the
    default) or a standard notification; anything malformed means the
    default window.
    """
    source = os.environ if environ is None else environ
    return Config(
        disable=source.get(ENV_DISABLE) == DISABLED_TOKEN,
        notifier=_notifier_channel(source.get(ENV_NOTIFIER)),
        poll_seconds=_poll_seconds(source.get(ENV_POLL_SECONDS)),
        style=_style(source.get(ENV_STYLE)),
    )


def _style(raw) -> str:
    token = (raw or "").strip().casefold()
    if token == STYLE_NOTIFICATION:
        return STYLE_NOTIFICATION
    return STYLE_WINDOW


def _notifier_channel(raw) -> str:
    token = (raw or "").strip().casefold()
    if token == NOTIFIER_FALLBACK_TOKEN:
        return NOTIFIER_OSASCRIPT
    return NOTIFIER_APPLET


def _poll_seconds(raw) -> int:
    try:
        seconds = int(str(raw).strip())
    except (TypeError, ValueError):
        return POLL_SECONDS
    return seconds if seconds > 0 else POLL_SECONDS
