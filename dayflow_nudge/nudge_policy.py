"""The nudge decision core: one pure arbiter between attention and silence.

decide() turns the persisted counters, one detector verdict, and the
cycle clock into at most one notification. The gates run in a fixed
order -- the two-strike streak confirmation, then the fifteen-minute
cooldown window, then quiet hours -- and every gate must pass before any
notification content exists. The distraction streak is the single cause
that can notify; the day's goal minutes are visible upstream yet carry
no nudge meaning. When the streak does notify, the offending card's own
title is the whole notification -- the headline carries the card name
and the body stays empty.

Escalation (sound on the second consecutive delivered nudge of an
episode) advances only after the caller confirms the notification
actually went out, so a swallowed delivery never earns a sound and never
anchors a cooldown window. decide() therefore returns the intended
command with the streak already counted, and the caller applies
confirm_delivery() only on a verified send.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import Enum

from dayflow_nudge import kill_switch
from dayflow_nudge.models import NudgeCommand, PersistedNudgeState, Verdict
from dayflow_nudge.quiet_hours import is_quiet

NUDGE_STRIKES_REQUIRED = 2
COOLDOWN_MINUTES = 15
COOLDOWN_SECONDS = COOLDOWN_MINUTES * 60
ESCALATION_MAX_LEVEL = 1

ON_TASK = "ON_TASK"
OFF_TASK = "OFF_TASK"
UNKNOWN = "UNKNOWN"

STANDING_TITLE = "Distraction noticed"
# The standing headline of every nudge surface (window or notification):
# the architect's fixed reminder, with the actual drift carried in the body.
FOCUS_TITLE = "Please focus on your main task"


class NudgeAction(Enum):
    """What the cycle owes the user: nothing, a silent nudge, or a sound one."""

    SILENT = "silent"
    NUDGE = "nudge"
    NUDGE_ESCALATED = "nudge_escalated"


class NudgeCause(Enum):
    """Which trigger earned the cycle's single nudge.

    One member, on purpose: the decision type keeps its cause field so
    the settle and log paths never thread a bare string, and a second
    cause cannot reappear without breaking the pin that guards it.
    """

    DISTRACTION = "distraction"


@dataclass(frozen=True)
class NudgeDecision:
    """One cycle's verdict plus the state the verdict leaves behind.

    ``command`` is the intended notification and is present only when the
    action is not SILENT. ``state`` always carries the freshly counted
    streak, but the delivery bookkeeping -- the cooldown anchor and the
    escalation level -- changes only through confirm_delivery().
    """

    action: NudgeAction
    state: PersistedNudgeState
    command: NudgeCommand | None = None
    cause: NudgeCause | None = None


def decide(
    state: PersistedNudgeState,
    verdict: Verdict,
    now: datetime,
) -> NudgeDecision:
    """Arbitrate one cycle: at most one nudge for the distraction streak.

    The streak is counted first because every later gate reads the
    episode through it. An unknown observation silences the whole cycle
    -- the cause may not notify on unreadable data -- and breaks the
    consecutive chain together with the escalation memory.
    """
    observation = _observation_state(verdict)
    if observation == UNKNOWN:
        return NudgeDecision(action=NudgeAction.SILENT, state=_break_episode(state))
    counted = _count_strike(state, observation)
    if observation != OFF_TASK or counted.streak < NUDGE_STRIKES_REQUIRED:
        return NudgeDecision(action=NudgeAction.SILENT, state=counted)
    if _within_cooldown(counted.last_nudge_epoch, now):
        # the episode waits behind the window; it is not spent
        return NudgeDecision(action=NudgeAction.SILENT, state=counted)
    if is_quiet(now):
        # nothing suppressed at night is held back for the morning: the
        # episode simply keeps counting until the window opens
        return NudgeDecision(action=NudgeAction.SILENT, state=counted)
    return _fire(counted, verdict)


def confirm_delivery(decision: NudgeDecision, now: datetime) -> PersistedNudgeState:
    """Apply a verified delivery to the counters.

    Only a delivery the notifier confirmed may anchor the cooldown
    window or move the escalation level -- and the level stops at its
    single sound step, so no further escalation exists to reach.
    """
    if decision.action is NudgeAction.SILENT:
        raise ValueError("only a fired decision can be confirmed as delivered")
    return replace(
        decision.state,
        last_nudge_epoch=now.timestamp(),
        escalation_level=min(
            decision.state.escalation_level + 1, ESCALATION_MAX_LEVEL),
    )


def should_suppress_for_kill_switch(config) -> bool:
    """Whether the kill switch silences this cycle.

    ``config`` is the per-cycle environment surface (the DFN_* mapping)
    the caller re-reads every tick; the policy exposes the check so the
    decision path and the loop can never disagree about what "disabled"
    means.
    """
    return kill_switch.is_armed(config)


def _observation_state(verdict: Verdict) -> str:
    """The verdict's three-way outcome in this module's vocabulary.

    The verdict may carry its state as an enumeration member or as the
    plain value; both spell the same three words, and anything else is
    a contract violation that must fail loudly rather than guess.
    """
    value = getattr(verdict, "state", None)
    if value is None:
        raise ValueError("a verdict must carry a detection state")
    name = getattr(value, "name", None)
    text = (name if name is not None else str(value)).upper()
    if text not in (ON_TASK, OFF_TASK, UNKNOWN):
        raise ValueError("unrecognized detection state: {!r}".format(value))
    return text


def _count_strike(state: PersistedNudgeState, observation: str) -> PersistedNudgeState:
    """Fold one observation into the streak.

    An on-task check breaks the consecutive chain and clears the
    escalation memory with it, so every episode starts silent again.
    """
    if observation == OFF_TASK:
        return replace(state, streak=state.streak + 1)
    return _break_episode(state)


def _break_episode(state: PersistedNudgeState) -> PersistedNudgeState:
    return replace(state, streak=0, escalation_level=0)


def _within_cooldown(last_nudge_epoch, now: datetime) -> bool:
    """Whether the window anchored at the last confirmed nudge still holds.

    A nudge that was never confirmed as delivered anchors nothing, so a
    failed delivery is retried on the next cycle rather than muted.
    """
    if last_nudge_epoch is None:
        return False
    return (now.timestamp() - last_nudge_epoch) < COOLDOWN_SECONDS


def _fire(state: PersistedNudgeState, verdict: Verdict) -> NudgeDecision:
    """Build the cycle's single intended notification.

    The offending card's own name is the whole notification: it headlines
    the title and the body stays empty. The standing line stands in only
    for a title that strips to empty, so a degenerate card can never
    yield an invisible notification. The sound belongs to the episode,
    not to the check: the episode's second confirmed nudge carries it.
    """
    escalated = state.escalation_level >= ESCALATION_MAX_LEVEL
    action = NudgeAction.NUDGE_ESCALATED if escalated else NudgeAction.NUDGE
    command = NudgeCommand(
        title=FOCUS_TITLE,
        body=_drift_detail(verdict),
        sound=escalated)
    return NudgeDecision(
        action=action, state=state, command=command,
        cause=NudgeCause.DISTRACTION)


def _drift_detail(verdict):
    """Say what the drift actually is: the offending card's name, aged in
    minutes when the detector reported its latency. Empty evidence falls
    back to the standing line so the body is never blank."""
    what = (getattr(verdict, "evidence", "") or "").strip() or STANDING_TITLE
    detail = "Instead of your main task, you are currently on: " + what
    latency = getattr(verdict, "latency", 0) or 0
    minutes = int(latency) // 60
    if minutes > 0:
        detail += " ({} min)".format(minutes)
    return detail
