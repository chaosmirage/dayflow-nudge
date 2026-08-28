"""The tick orchestrator for the nudge daemon.

One cycle runs the pinned stage order -- kill switch, clock, read,
freshness, state load, detect, policy, notify, settle, persist --
with per-stage containment: any stage exception produces exactly one
warning line and a silent cycle, and the process keeps running. Nothing
here owns a nudge rule; each stage delegates to the module that owns it,
and every collaborator is injectable so a single tick is deterministic
under test.
"""

from __future__ import annotations

import dataclasses
import os
import time
from datetime import datetime
from enum import Enum
from types import SimpleNamespace

from dayflow_nudge.config import load_config
from dayflow_nudge.logging import log_event, setup

__all__ = ["CycleOutcome", "default_db_path", "default_state_path", "main", "run_cycle"]

NUDGE_ACTIONS = ("NUDGE", "NUDGE_ESCALATED", "NUDGED_ESCALATED")
SENT = "SENT"

FALLBACK_DB_PATH = os.path.expanduser(
    "~/Library/Application Support/Dayflow/chunks.sqlite")
FALLBACK_STATE_PATH = os.path.expanduser(
    "~/Library/Application Support/dayflow-nudge/state.json")


class CycleOutcome(Enum):
    """What one tick did, as the loop and the tests observe it."""

    IDLE = "IDLE"
    SILENT = "SILENT"
    NUDGED = "NUDGED"
    DELIVERY_FAILED = "DELIVERY_FAILED"


@dataclasses.dataclass(frozen=True)
class StageResult:
    """One stage's outcome; ok=False means the cycle ends silently here."""

    ok: bool
    value: object = None


class _SilentStage(Exception):
    """A stage that already logged its own line and asks only for silence."""


def run_cycle(clock, environ, db_path, state_path, detector=None, notifier=None,
              *, capture=None, freshness=None, decide=None,
              settle=None, store=None) -> CycleOutcome:
    """Run exactly one tick and report what it did.

    The kill switch is consulted before anything else and re-read from the
    environment every call, so arming or disarming takes effect on the very
    next tick without touching any persisted counter. Collaborators are
    injectable so a tick is fully deterministic under test; the defaults
    bind the package's real modules, resolved lazily so a partially
    assembled package still imports and runs silent rather than crashing:

    - capture(db_path, now) -> (cards, goal)
    - freshness(newest_end_ts, now) -> truthy when the window is fresh
    - decide(state, verdict, now) -> decision with action/command/state
    - settle(decision, result, now) -> state to persist after delivery
    - store.load() / store.save(state)
    - detector.detect(observation, state) -> verdict
    - notifier.deliver(command) -> delivery result
    """
    config = load_config(environ)

    gated = _stage("kill_switch", lambda: _kill_switch_armed(environ, config))
    if not gated.ok:
        return CycleOutcome.SILENT
    if gated.value:
        log_event("cycle_idle", reason="kill_switch")
        return CycleOutcome.IDLE

    sensed = _sense(clock, db_path, capture, freshness)
    if sensed is None:
        return CycleOutcome.SILENT
    now, cards, goal = sensed

    opened = _stage("state", lambda: _open_state(state_path, store, clock))
    if not opened.ok:
        return CycleOutcome.SILENT
    store_obj, state = opened.value

    detected = _stage("detect", lambda: _detect(detector, cards, goal, state, now))
    if not detected.ok:
        return CycleOutcome.SILENT

    decided = _stage(
        "policy", lambda: _decide(decide, state, detected.value, now))
    if not decided.ok:
        return CycleOutcome.SILENT
    decision = decided.value

    if not _is_nudge(decision):
        log_event("cycle_silent", reason="no_nudge", streak=_streak_of(decision.state))
        _stage("persist", lambda: store_obj.save(decision.state))
        return CycleOutcome.SILENT

    delivered = _stage("notify", lambda: _deliver(notifier, decision.command, config))
    if not delivered.ok:
        return CycleOutcome.SILENT
    result = delivered.value
    sent = _result_value(result) == SENT
    _log_delivery(decision, sent, result)
    settled = _stage("settle", lambda: _settle_state(settle, decision, result, now))
    final_state = settled.value if settled.ok else decision.state
    _stage("persist", lambda: store_obj.save(final_state))
    return CycleOutcome.NUDGED if sent else CycleOutcome.DELIVERY_FAILED


def main() -> int:
    """Boot and run forever: one tick, then one configured poll of sleep."""
    setup()
    clock = datetime.now
    db_path = default_db_path()
    state_path = default_state_path()
    try:
        while True:
            run_cycle(clock, os.environ, db_path, state_path)
            time.sleep(load_config(os.environ).poll_seconds)
    except KeyboardInterrupt:
        return 0


# --- stage plumbing -----------------------------------------------------------


def _stage(name, operation) -> StageResult:
    """Run one stage under containment: one warning line, then silence.

    A failing stage must cost the daemon a silent cycle, never the
    process: the loop lives on and tries again on the next tick.
    """
    try:
        return StageResult(ok=True, value=operation())
    except _SilentStage:
        return StageResult(ok=False)
    except Exception as error:
        log_event(
            "stage_failed", level="warning", stage=name, error=type(error).__name__)
        return StageResult(ok=False)


def _sense(clock, db_path, capture, freshness):
    """Clock, read, and freshness stages; None ends the cycle silently."""
    clocked = _stage("clock", clock)
    if not clocked.ok:
        return None
    now = clocked.value

    read = _stage("read", lambda: _capture(capture, db_path, now))
    if not read.ok:
        return None
    cards, goal = _as_capture(read.value)

    fresh = _stage("freshness", lambda: _is_fresh(freshness, _newest_end(cards), now))
    if not fresh.ok:
        return None
    if not fresh.value:
        # stale or missing data is never acted on, whatever the causes offer
        log_event("cycle_silent", reason="stale_data")
        return None
    return now, cards, goal


def _as_capture(raw):
    """The cycle's window as (cards, goal), from a pair or a carrying object."""
    if isinstance(raw, tuple):
        return raw[0], raw[1]
    return raw.cards, raw.goal


def _newest_end(cards):
    """The latest card end in the window; an empty window has none."""
    present = [end for end in (getattr(card, "end_ts", None) for card in cards)
               if end is not None]
    return max(present) if present else None


def _log_delivery(decision, sent, result):
    """One line for the delivery outcome; the notifier adds its own detail."""
    title = getattr(decision.command, "title", None)
    if sent:
        log_event(
            "nudge_sent", title=title, sound=getattr(decision.command, "sound", None))
    else:
        log_event(
            "delivery_failed", level="warning", title=title,
            result=_result_value(result))


def _kill_switch_armed(environ, config) -> bool:
    """The suppression gate's own answer, with the config flag as fallback."""
    try:
        from dayflow_nudge import kill_switch

        return kill_switch.is_armed(environ)
    except ImportError:
        return config.disable


# --- collaborator bindings ------------------------------------------------------


def _capture(capture_fn, db_path, now):
    if capture_fn is not None:
        return capture_fn(db_path, now)
    return _default_capture(db_path, now)


def _is_fresh(freshness_fn, newest_end_ts, now):
    if freshness_fn is not None:
        return freshness_fn(newest_end_ts, now)
    from dayflow_nudge.freshness_guard import Freshness, evaluate_freshness

    return evaluate_freshness(newest_end_ts, now) is Freshness.FRESH


def _open_state(state_path, store, clock):
    """Open the counter store and load the state this cycle starts from."""
    store_obj = store if store is not None else _default_store(state_path, clock)
    return store_obj, store_obj.load()


def _detect(detector_obj, cards, goal, state, now):
    detector = detector_obj if detector_obj is not None else _default_detector()
    return detector.detect(_observation(cards, goal, now), state)


def _observation(cards, goal, now):
    """The merged detector input; the typed contract whenever models exists."""
    try:
        from dayflow_nudge.models import Observation

        return Observation(observed_at=now, cards=tuple(cards), goal=goal)
    except ImportError:
        return SimpleNamespace(observed_at=now, cards=tuple(cards), goal=goal)


def _decide(decide_fn, state, verdict, now):
    if decide_fn is not None:
        return decide_fn(state, verdict, now)
    from dayflow_nudge import nudge_policy

    return nudge_policy.decide(state, verdict, now)


def _deliver(notifier_obj, command, config):
    if notifier_obj is not None:
        if hasattr(notifier_obj, "deliver"):
            return notifier_obj.deliver(command)
        return notifier_obj(command)
    from dayflow_nudge import notifier

    return notifier.deliver(
        command, preferred_channel=config.notifier, style=config.style)


def _settle_state(settle_fn, decision, result, now):
    """Fold the delivery outcome into the state the cycle persists.

    The policy owns what a delivery earns; on a failed delivery nothing
    advances -- not the escalation level, not the cooldown anchor.
    """
    if settle_fn is not None:
        return settle_fn(decision, result, now)
    if _result_value(result) != SENT:
        return decision.state
    from dayflow_nudge import nudge_policy

    return nudge_policy.confirm_delivery(decision, now)


def _default_capture(db_path, now):
    """Assemble the cycle's window through the read-only store seam."""
    from dayflow_nudge import card_provider, db_reader, goal_provider

    attachment = db_reader.attach_store(db_path)
    try:
        if attachment.state is not db_reader.AttachmentState.OPEN:
            # the attachment already logged its single warning line
            raise _SilentStage(attachment.detail or "store attachment unknown")
        connection = attachment.connection
        return (
            card_provider.load_card_snapshots(connection, int(now.timestamp())),
            goal_provider.load_goal_snapshot(connection, now.date().isoformat()),
        )
    finally:
        attachment.close()


_DEFAULT_DETECTOR = None


def _default_detector():
    """The single registered variant, instantiated once and never switched."""
    global _DEFAULT_DETECTOR
    if _DEFAULT_DETECTOR is None:
        # Importing the variant module is what registers variant A.
        from dayflow_nudge import detector_api, detector_distraction

        variant_ids = detector_api.registered_variants()
        if len(variant_ids) != 1:
            raise RuntimeError(
                "exactly one detector variant must be registered, found: "
                + ", ".join(variant_ids))
        _DEFAULT_DETECTOR = detector_api.create_detector(variant_ids[0])
        log_event("detector_selected", variant=variant_ids[0])
    return _DEFAULT_DETECTOR


def _default_store(state_path, clock):
    from dayflow_nudge import state_store

    return state_store.StateStore(state_path, clock=clock)


# --- small normalizers ------------------------------------------------------------


def _is_nudge(decision) -> bool:
    return _action(getattr(decision, "action", "SILENT")) in NUDGE_ACTIONS


def _action(raw) -> str:
    """An action in one spelling, whether it arrives as enum or string."""
    return str(getattr(raw, "value", raw)).strip().upper()


def _result_value(result) -> str:
    return str(getattr(result, "value", result)).strip().upper()


def _streak_of(state):
    if isinstance(state, dict):
        return state.get("streak")
    return getattr(state, "streak", None)


# --- default paths --------------------------------------------------------------


def default_db_path() -> str:
    """The store path, preferring the module that owns it when present."""
    try:
        from dayflow_nudge import db_reader

        return str(db_reader.DEFAULT_DB_PATH)
    except ImportError:
        return FALLBACK_DB_PATH


def default_state_path() -> str:
    try:
        from dayflow_nudge import state_store

        return state_store.DEFAULT_STATE_PATH
    except ImportError:
        return FALLBACK_STATE_PATH
