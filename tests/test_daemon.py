"""Behavior of one daemon tick.

A tick is driven through injected collaborators (capture, detector,
policy, settle, store, notifier) on top of the real configuration and
freshness modules, so the orchestration contract -- stage order, silence
rules, containment, and state threading across cycles -- is observed without
sleeping and without touching the live store. The goal-minutes pin below
goes further and runs whole ticks over a real fixture store through the
package's own capture, detection, policy, and persistence: the day's
recorded minutes stay visible on the goal row yet never change what a
cycle does.
"""

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace

from dayflow_nudge.daemon import CycleOutcome, run_cycle
from dayflow_nudge.nudge_policy import FOCUS_TITLE
from tests import fixtures

NOON = datetime(2026, 8, 28, 12, 0, 0)
DAY_KEY = "2026-08-28"
ABSENT_DB = "/nonexistent/chunks.sqlite"


def _card(age_minutes, category="Distraction", title="Reddit scroll"):
    ended = NOON - timedelta(minutes=age_minutes)
    return SimpleNamespace(
        title=title,
        summary="a long scroll",
        category=category,
        start_ts=ended - timedelta(minutes=5),
        end_ts=ended,
        metadata={},
    )


class _FileStateStore:
    """Persistence double writing the five-key state schema to a JSON file."""

    def __init__(self, path):
        self.path = path

    def load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                return json.load(handle)
        except FileNotFoundError:
            return {
                "schema_version": 2,
                "streak": 0,
                "last_nudge_epoch": None,
                "escalation_level": 0,
                "day_key": DAY_KEY,
            }

    def save(self, state):
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump(state, handle)


class _RecordingNotifier:
    """Delivery double that records every command it is handed."""

    def __init__(self, result="SENT"):
        self.commands = []
        self.result = result

    def deliver(self, command):
        self.commands.append(command)
        return self.result


class _OffTaskDetector:
    """Detection double: every observation is off task."""

    def __init__(self):
        self.observations = []

    def detect(self, observation, state):
        self.observations.append(observation)
        return SimpleNamespace(
            off_task=True, state="OFF_TASK", evidence="Reddit scroll"
        )


def _action_name(raw):
    """An action in one spelling, whether it arrives as enum or string."""
    return str(getattr(raw, "value", raw)).strip().upper()


def _streak_policy(state, verdict, now):
    """Policy double: two consecutive off-task checks, then one nudge.

    The command carries the amended content contract -- the offending
    card's title as the headline, an empty body -- so the orchestration
    assertions observe the notification exactly as the real policy
    shapes it.
    """
    streak = state.get("streak", 0) + 1
    updated = dict(state, streak=streak)
    if streak < 2:
        return SimpleNamespace(action="SILENT", command=None, state=updated)
    updated = dict(updated, last_nudge_epoch=now.isoformat())
    what = getattr(verdict, "evidence", "") or "Distraction noticed"
    return SimpleNamespace(
        action="NUDGE",
        command=SimpleNamespace(
            title="Please focus on your main task",
            body="Instead of your main task, you are currently on: " + what,
            sound=state.get("escalation_level", 0) >= 1,
        ),
        state=updated,
    )


def _settle_on_delivery(decision, result, now):
    """Settle double: escalation advances only on a verified delivery."""
    delivered = str(getattr(result, "value", result)) == "SENT"
    nudged = _action_name(decision.action) in _NUDGE_ACTIONS
    state = decision.state
    if not (delivered and nudged):
        return state
    return dict(state, escalation_level=state.get("escalation_level", 0) + 1)


_NUDGE_ACTIONS = ("NUDGE", "NUDGE_ESCALATED", "NUDGED_ESCALATED")


def _cycle_kwargs(state_path, notifier, age_minutes=5):
    """Collaborator set for one deterministic tick over a fresh timeline."""
    return dict(
        capture=lambda db_path, now: ([_card(age_minutes)], None),
        detector=_OffTaskDetector(),
        decide=_streak_policy,
        settle=_settle_on_delivery,
        store=_FileStateStore(state_path),
        notifier=notifier,
    )


class _CycleTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.state_path = os.path.join(tmp.name, "state.json")

    def _read_state(self):
        with open(self.state_path, "r", encoding="utf-8") as handle:
            return json.load(handle)


class KillSwitchTest(_CycleTestCase):
    def test_disabled_cycle_idles_without_touching_persisted_state(self):
        notifier = _RecordingNotifier()

        def _capture_must_not_run(db_path, now):
            raise AssertionError("a disabled cycle must not read the store")

        outcome = run_cycle(
            lambda: NOON,
            {"DFN_DISABLE": "1"},
            ABSENT_DB,
            self.state_path,
            detector=None,
            notifier=notifier,
            capture=_capture_must_not_run,
        )

        self.assertIs(outcome, CycleOutcome.IDLE)
        self.assertEqual(notifier.commands, [])
        self.assertFalse(os.path.exists(self.state_path))

    def test_the_flag_is_reread_every_cycle(self):
        environ = {"DFN_DISABLE": "1"}
        first = run_cycle(
            lambda: NOON,
            environ,
            ABSENT_DB,
            self.state_path,
            detector=_OffTaskDetector(),
            notifier=_RecordingNotifier(),
            capture=lambda db_path, now: ([], None),
            store=_FileStateStore(self.state_path),
        )
        self.assertIs(first, CycleOutcome.IDLE)

        del environ["DFN_DISABLE"]
        second = run_cycle(
            lambda: NOON,
            environ,
            ABSENT_DB,
            self.state_path,
            detector=_OffTaskDetector(),
            notifier=_RecordingNotifier(),
            capture=lambda db_path, now: ([_card(age_minutes=30)], None),
            store=_FileStateStore(self.state_path),
        )
        self.assertIsNot(second, CycleOutcome.IDLE)


class FreshnessSilenceTest(_CycleTestCase):
    def test_stale_card_keeps_the_cycle_silent(self):
        notifier = _RecordingNotifier()
        outcome = run_cycle(
            lambda: NOON,
            {},
            ABSENT_DB,
            self.state_path,
            detector=_OffTaskDetector(),
            notifier=notifier,
            capture=lambda db_path, now: ([_card(age_minutes=30)], None),
            decide=_streak_policy,
            settle=_settle_on_delivery,
            store=_FileStateStore(self.state_path),
        )
        self.assertIs(outcome, CycleOutcome.SILENT)
        self.assertEqual(notifier.commands, [])
        self.assertFalse(os.path.exists(self.state_path))

    def test_empty_window_keeps_the_cycle_silent(self):
        notifier = _RecordingNotifier()
        outcome = run_cycle(
            lambda: NOON,
            {},
            ABSENT_DB,
            self.state_path,
            detector=_OffTaskDetector(),
            notifier=notifier,
            capture=lambda db_path, now: ([], None),
            store=_FileStateStore(self.state_path),
        )
        self.assertIs(outcome, CycleOutcome.SILENT)
        self.assertEqual(notifier.commands, [])


class TwoStrikeFlowTest(_CycleTestCase):
    def test_second_consecutive_check_delivers_one_command_and_persists_state(self):
        notifier = _RecordingNotifier()
        first_kwargs = _cycle_kwargs(self.state_path, notifier)

        first = run_cycle(
            lambda: NOON, {}, ABSENT_DB, self.state_path, **first_kwargs,
        )
        self.assertIs(first, CycleOutcome.SILENT)
        self.assertEqual(notifier.commands, [])
        self.assertEqual(self._read_state()["streak"], 1)
        observation = first_kwargs["detector"].observations[0]
        self.assertEqual(observation.cards[0].title, "Reddit scroll")
        self.assertEqual(observation.observed_at, NOON)
        self.assertIsNone(observation.goal)

        second = run_cycle(
            lambda: NOON, {}, ABSENT_DB, self.state_path,
            **_cycle_kwargs(self.state_path, notifier),
        )
        self.assertIs(second, CycleOutcome.NUDGED)
        self.assertEqual(len(notifier.commands), 1)
        command = notifier.commands[0]
        # the standing focus headline carries the card's name in the body
        self.assertEqual(command.title, FOCUS_TITLE)
        self.assertIn("Reddit scroll", command.body)
        self.assertFalse(command.sound)
        state = self._read_state()
        self.assertEqual(state["streak"], 2)
        self.assertIsNotNone(state["last_nudge_epoch"])


class DeliveryFailureTest(_CycleTestCase):
    def test_failed_delivery_holds_escalation_and_logs_one_line(self):
        notifier = _RecordingNotifier(result="FAILED")

        run_cycle(
            lambda: NOON, {}, ABSENT_DB, self.state_path,
            **_cycle_kwargs(self.state_path, notifier),
        )

        with self.assertLogs("dayflow_nudge", level="WARNING") as captured:
            second = run_cycle(
                lambda: NOON, {}, ABSENT_DB, self.state_path,
                **_cycle_kwargs(self.state_path, notifier),
            )

        self.assertIs(second, CycleOutcome.DELIVERY_FAILED)
        self.assertEqual(len(notifier.commands), 1)
        self.assertEqual(len(captured.records), 1)
        self.assertIn("delivery_failed", captured.records[0].getMessage())
        state = self._read_state()
        self.assertEqual(state["escalation_level"], 0)
        self.assertEqual(state["streak"], 2)


class GoalMinutesNeverNudgeTest(_CycleTestCase):
    """Whole ticks over real fixture stores through the package's own
    capture, detection, policy, and persistence.

    The day's goal minutes stay on the snapshot yet are causally inert:
    a store whose recorded card minutes tower over a one-minute daily
    limit behaves exactly like the same store with no goal row at all,
    because only the moment a category rule catches -- never the day's
    accumulated minutes -- can notify.
    """

    def _heavy_minutes_cards(self, store, now_epoch):
        """Fresh on-task cards totalling hours of recorded minutes.

        Every category is neither a member of the day's selection nor a
        distraction word, the spans end moments ago (fresh) while lasting
        hours (heavy minutes), and one short card decides the window so
        the check lands squarely on task.
        """
        store.add_card(title="Work marathon", category="Work", day=DAY_KEY,
                       start_ts=fixtures.minutes_ago(now_epoch, 185),
                       end_ts=fixtures.minutes_ago(now_epoch, 2))
        store.add_card(title="Admin backlog", category="Admin", day=DAY_KEY,
                       start_ts=fixtures.minutes_ago(now_epoch, 170),
                       end_ts=fixtures.minutes_ago(now_epoch, 50))
        store.add_card(title="Planned review", category="Work", day=DAY_KEY,
                       start_ts=fixtures.minutes_ago(now_epoch, 8),
                       end_ts=fixtures.minutes_ago(now_epoch, 3))

    def _run_real_tick(self, store, notifier):
        return run_cycle(
            lambda: NOON, {}, store.path, self.state_path,
            notifier=notifier,
        )

    def test_heavy_minutes_against_a_one_minute_limit_never_notify(self):
        now_epoch = int(NOON.timestamp())
        with fixtures.fixture_store() as store:
            fixtures.persona_goal_active(
                store, DAY_KEY, focus_target_minutes=240,
                distraction_limit_minutes=1)
            store.add_goal_category(day=DAY_KEY, category_name="YouTube")
            self._heavy_minutes_cards(store, now_epoch)

            notifier = _RecordingNotifier()
            outcome = self._run_real_tick(store, notifier)

            self.assertIs(outcome, CycleOutcome.SILENT)
            self.assertEqual(notifier.commands, [])
            state = self._read_state()
            self.assertEqual(state["streak"], 0)
            self.assertEqual(state["escalation_level"], 0)

    def test_the_goal_row_with_its_minutes_changes_nothing(self):
        now_epoch = int(NOON.timestamp())
        outcomes = []
        with fixtures.fixture_store() as with_goal:
            fixtures.persona_goal_active(
                store=with_goal, day=DAY_KEY, distraction_limit_minutes=1)
            with_goal.add_goal_category(day=DAY_KEY, category_name="YouTube")
            self._heavy_minutes_cards(with_goal, now_epoch)
            notifier = _RecordingNotifier()
            outcomes.append(
                (self._run_real_tick(with_goal, notifier),
                 list(notifier.commands), dict(self._read_state())))
        with fixtures.fixture_store() as without_goal:
            self._heavy_minutes_cards(without_goal, now_epoch)
            notifier = _RecordingNotifier()
            outcomes.append(
                (self._run_real_tick(without_goal, notifier),
                 list(notifier.commands), dict(self._read_state())))

        self.assertEqual(outcomes[0], outcomes[1])
        self.assertEqual(outcomes[0][0], CycleOutcome.SILENT)
        self.assertEqual(outcomes[0][1], [])
        self.assertEqual(outcomes[0][2]["streak"], 0)

    def test_a_card_in_the_day_s_selection_still_nudges_over_the_same_path(self):
        # the silence above must come from the minute columns being inert,
        # never from a broken path: a category the day selected nudges
        # through this very wiring, with the card's own title as the
        # whole notification
        now_epoch = int(NOON.timestamp())
        with fixtures.fixture_store() as store:
            fixtures.persona_goal_active(store, DAY_KEY,
                                         distraction_limit_minutes=1)
            store.add_goal_category(day=DAY_KEY, category_name="YouTube")
            store.add_card(title="YouTube deep dive", category="YouTube",
                           day=DAY_KEY,
                           start_ts=fixtures.minutes_ago(now_epoch, 8),
                           end_ts=fixtures.minutes_ago(now_epoch, 3))

            notifier = _RecordingNotifier()
            first = self._run_real_tick(store, notifier)
            second = self._run_real_tick(store, notifier)

            self.assertIs(first, CycleOutcome.SILENT)
            self.assertIs(second, CycleOutcome.NUDGED)
            self.assertEqual(len(notifier.commands), 1)
            self.assertEqual(
                notifier.commands[0].title, FOCUS_TITLE)
            self.assertIn("YouTube deep dive", notifier.commands[0].body)


class SelectionPickupTest(_CycleTestCase):
    """Whole ticks over one real store as the day's selection changes.

    The selection is re-read from the store every cycle, so a change the
    owner makes in Dayflow's Daily tab governs the very next tick: with
    nothing selected the category-word fallback fires; the moment a
    selection exists it alone decides, silencing a card the fallback would
    have caught; and a later card in a selected category fires through
    membership alone -- all without a restart, with the counters threading
    truthfully across the transition.
    """

    def _tick(self, store, notifier, moment):
        return run_cycle(
            lambda: moment, {}, store.path, self.state_path,
            notifier=notifier,
        )

    def test_a_selection_change_governs_the_very_next_cycle(self):
        now_epoch = int(NOON.timestamp())
        with fixtures.fixture_store() as store:
            fixtures.persona_goal_active(store, DAY_KEY)
            store.add_card(title="Feed spiral",
                           category="Distraction - social feeds", day=DAY_KEY,
                           start_ts=fixtures.minutes_ago(now_epoch, 6),
                           end_ts=fixtures.minutes_ago(now_epoch, 1))

            notifier = _RecordingNotifier()
            first = self._tick(store, notifier, NOON)
            self.assertIs(first, CycleOutcome.SILENT)
            self.assertEqual(notifier.commands, [])
            self.assertEqual(self._read_state()["streak"], 1)

            second = self._tick(
                store, notifier, NOON + timedelta(minutes=2))
            self.assertIs(second, CycleOutcome.NUDGED)
            self.assertEqual(
                [command.title for command in notifier.commands],
                [FOCUS_TITLE])
            self.assertIn("Feed spiral", notifier.commands[0].body)

            # The owner selects YouTube for the day; the same card, judged
            # on the immediately following cycle, is now on task.
            store.add_goal_category(day=DAY_KEY, category_name="YouTube")
            third = self._tick(
                store, notifier, NOON + timedelta(minutes=4))
            self.assertIs(third, CycleOutcome.SILENT)
            self.assertEqual(len(notifier.commands), 1)
            self.assertEqual(self._read_state()["streak"], 0)

            # A fresh card in the selected category -- whose name carries
            # no distraction wording at all -- fires through membership.
            store.add_card(title="Video rabbit hole", category="YouTube",
                           day=DAY_KEY,
                           start_ts=now_epoch + 12 * 60,
                           end_ts=now_epoch + 17 * 60)
            fourth = self._tick(
                store, notifier, NOON + timedelta(minutes=18))
            self.assertIs(fourth, CycleOutcome.SILENT)
            self.assertEqual(self._read_state()["streak"], 1)

            fifth = self._tick(
                store, notifier, NOON + timedelta(minutes=20))
            self.assertIs(fifth, CycleOutcome.NUDGED)
            self.assertEqual(
                [command.title for command in notifier.commands],
                [FOCUS_TITLE, FOCUS_TITLE])
            self.assertIn("Video rabbit hole", notifier.commands[1].body)


class FocusOnlySelectionTest(_CycleTestCase):
    """A day whose only selections are focus kind never arms the trigger.

    Focus rows describe what the owner aims to do, not what to interrupt,
    so even a focus row naming the active card's own category leaves the
    cycle silent: the trigger set stays empty and the card's category
    carries no distraction wording.
    """

    def test_a_card_in_a_focus_named_category_never_nudges(self):
        now_epoch = int(NOON.timestamp())
        with fixtures.fixture_store() as store:
            fixtures.persona_goal_focus_only(store, DAY_KEY)
            store.add_card(title="Deep work block", category="Deep Work",
                           day=DAY_KEY,
                           start_ts=fixtures.minutes_ago(now_epoch, 6),
                           end_ts=fixtures.minutes_ago(now_epoch, 1))

            notifier = _RecordingNotifier()
            first = run_cycle(
                lambda: NOON, {}, store.path, self.state_path,
                notifier=notifier,
            )
            second = run_cycle(
                lambda: NOON + timedelta(minutes=2), {}, store.path,
                self.state_path, notifier=notifier,
            )

            self.assertIs(first, CycleOutcome.SILENT)
            self.assertIs(second, CycleOutcome.SILENT)
            self.assertEqual(notifier.commands, [])
            self.assertEqual(self._read_state()["streak"], 0)


class ContainmentTest(_CycleTestCase):
    def test_stage_exception_logs_one_line_and_ends_the_cycle_silently(self):
        def _broken_capture(db_path, now):
            raise RuntimeError("store exploded")

        with self.assertLogs("dayflow_nudge", level="WARNING") as captured:
            outcome = run_cycle(
                lambda: NOON,
                {},
                ABSENT_DB,
                self.state_path,
                detector=_OffTaskDetector(),
                notifier=_RecordingNotifier(),
                capture=_broken_capture,
                    decide=_streak_policy,
                settle=_settle_on_delivery,
                store=_FileStateStore(self.state_path),
            )

        self.assertIs(outcome, CycleOutcome.SILENT)
        self.assertEqual(len(captured.records), 1)
        message = captured.records[0].getMessage()
        self.assertIn("stage_failed", message)
        self.assertIn("read", message)
        self.assertFalse(os.path.exists(self.state_path))

    def test_the_loop_keeps_running_after_a_failed_stage(self):
        def _broken_capture(db_path, now):
            raise RuntimeError("store exploded")

        with self.assertLogs("dayflow_nudge", level="WARNING"):
            run_cycle(
                lambda: NOON,
                {},
                ABSENT_DB,
                self.state_path,
                detector=_OffTaskDetector(),
                notifier=_RecordingNotifier(),
                capture=_broken_capture,
                    decide=_streak_policy,
                settle=_settle_on_delivery,
                store=_FileStateStore(self.state_path),
            )

        outcome = run_cycle(
            lambda: NOON, {}, ABSENT_DB, self.state_path,
            **_cycle_kwargs(self.state_path, _RecordingNotifier()),
        )
        self.assertIs(outcome, CycleOutcome.SILENT)
        self.assertEqual(self._read_state()["streak"], 1)


if __name__ == "__main__":
    unittest.main()
