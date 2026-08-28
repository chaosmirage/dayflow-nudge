"""The kill switch: one environment value stops every nudge instantly.

The switch is armed exactly when the disable variable holds "1"; nothing
else arms it, so a malformed value can only ever leave nudging on. The
check reads the per-cycle environment mapping every time it is asked and
caches nothing, so arming or disarming takes effect on the very next
tick, and it touches no persisted counter -- disarming resumes the
counters exactly where they were.
"""

from collections.abc import Mapping

DFN_DISABLE = "DFN_DISABLE"
ARMED_VALUE = "1"


def is_armed(environ):
    """Whether the disable flag is armed in this cycle's environment."""
    if not isinstance(environ, Mapping):
        raise TypeError(
            "the kill switch reads an environment mapping, got {!r}".format(
                type(environ).__name__
            )
        )
    return environ.get(DFN_DISABLE) == ARMED_VALUE
