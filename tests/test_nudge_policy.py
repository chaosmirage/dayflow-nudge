"""Behavior of the nudge decision core.

Everything drives the public seam: decide() turns the persisted state, one
detector verdict, and the cycle clock into at most one notification per
cycle, and confirm_delivery() applies the bookkeeping only after the
caller reports the notification actually went out. The clock and the
calendar are fixed constants, so every boundary below is exact.

A nudge requires two consecutive off-task checks; the 15-minute cooldown
is one window every nudge shares; the first nudge of an episode is silent
and only the second carries sound; quiet hours suppress everything
without spending anything -- the episode keeps counting until the window
opens. The distraction streak is the only cause that can notify.
"""

from __future__ import annotations

import dataclasses
import datetime
import inspect
import unittest

from dayflow_nudge.models import DetectionState, PersistedNudgeState, Verdict
from dayflow_nudge.nudge_policy import (
    COOLDOWN_MINUTES,
    NUDGE_STRIKES_REQUIRED,
    NudgeAction,
    NudgeCause,
    confirm_delivery,
    decide,
    should_suppress_for_kill_switch,
)

MIDDAY = datetime.datetime(2026, 8, 28, 12, 0, 0)
ONE_MINUTE = datetime.timedelta(minutes=1)
FIVE_MINUTES = datetime.timedelta(minutes=5)


def fresh_state(**changes):
    return dataclasses.replace(PersistedNudgeState(), **changes)


def off_task(evidence="News feed"):
    return Verdict(state=DetectionState.OFF_TASK, off_task=True, evidence=evidence)


def on_task():
    return Verdict(state=DetectionState.ON_TASK, off_task=False)


def unknown():
    return Verdict(state=DetectionState.UNKNOWN, off_task=False)


def minutes(count):
    return datetime.timedelta(minutes=count)


def deliver_two_strike_episode(start):
    """Run the silent first episode nudge and return the confirmed state."""
    first_check = decide(fresh_state(), off_task(), start)
    second_check = decide(first_check.state, off_task(), start + ONE_MINUTE)
    return confirm_delivery(second_check, start + ONE_MINUTE)


class TwoStrikeConfirmationTest(unittest.TestCase):
    def test_a_single_off_task_check_stays_silent(self):
        decision = decide(fresh_state(), off_task(), MIDDAY)
        self.assertIs(decision.action, NudgeAction.SILENT)
        self.assertIsNone(decision.command)
        self.assertEqual(decision.state.streak, 1)

    def test_the_second_consecutive_check_fires_one_silent_nudge(self):
        first = decide(fresh_state(), off_task(), MIDDAY)
        second = decide(first.state, off_task(), MIDDAY + ONE_MINUTE)
        self.assertIs(second.action, NudgeAction.NUDGE)
        self.assertIs(second.cause, NudgeCause.DISTRACTION)
        self.assertFalse(second.command.sound)
        self.assertEqual(second.state.streak, 2)
        # deciding alone starts no cooldown window: only a confirmed
        # delivery anchors one
        self.assertIsNone(second.state.last_nudge_epoch)

    def test_an_on_task_check_resets_streak_and_escalation_memory(self):
        mid_episode = fresh_state(streak=3, escalation_level=1)
        decision = decide(mid_episode, on_task(), MIDDAY)
        self.assertIs(decision.action, NudgeAction.SILENT)
        self.assertEqual(decision.state.streak, 0)
        self.assertEqual(decision.state.escalation_level, 0)

    def test_an_unknown_observation_resets_streak_and_escalation_memory(self):
        mid_episode = fresh_state(streak=3, escalation_level=1)
        decision = decide(mid_episode, unknown(), MIDDAY)
        self.assertIs(decision.action, NudgeAction.SILENT)
        self.assertEqual(decision.state.streak, 0)
        self.assertEqual(decision.state.escalation_level, 0)

    def test_an_unknown_observation_blocks_the_nudge(self):
        # unreadable or stale cycle data must silence the cycle, not
        # guess an episode into existence
        mid_episode = fresh_state(streak=5)
        decision = decide(mid_episode, unknown(), MIDDAY)
        self.assertIs(decision.action, NudgeAction.SILENT)
        self.assertIsNone(decision.command)
        self.assertEqual(decision.state.streak, 0)


class SharedCooldownTest(unittest.TestCase):
    def test_a_nudge_inside_the_window_is_suppressed(self):
        delivered = deliver_two_strike_episode(MIDDAY)
        inside = MIDDAY + ONE_MINUTE + minutes(COOLDOWN_MINUTES - 1)
        decision = decide(delivered, off_task(), inside)
        self.assertIs(decision.action, NudgeAction.SILENT)
        self.assertIsNone(decision.command)
        # suppression never stops counting the consecutive checks
        self.assertEqual(decision.state.streak, 3)

    def test_the_window_elapses_exactly_at_fifteen_minutes(self):
        delivered = deliver_two_strike_episode(MIDDAY)
        anchored = MIDDAY + ONE_MINUTE
        just_before = anchored + minutes(COOLDOWN_MINUTES) - datetime.timedelta(seconds=1)
        at_edge = anchored + minutes(COOLDOWN_MINUTES)
        self.assertIs(decide(delivered, off_task(), just_before).action, NudgeAction.SILENT)
        self.assertIsNot(decide(delivered, off_task(), at_edge).action, NudgeAction.SILENT)


class EscalationTest(unittest.TestCase):
    def test_the_second_consecutive_nudge_carries_sound(self):
        delivered = deliver_two_strike_episode(MIDDAY)
        later = MIDDAY + ONE_MINUTE + minutes(COOLDOWN_MINUTES) + ONE_MINUTE
        second = decide(delivered, off_task(), later)
        self.assertIs(second.action, NudgeAction.NUDGE_ESCALATED)
        self.assertTrue(second.command.sound)

    def test_no_third_escalation_level_exists(self):
        delivered = deliver_two_strike_episode(MIDDAY)
        later = MIDDAY + ONE_MINUTE + minutes(COOLDOWN_MINUTES) + ONE_MINUTE
        second = decide(delivered, off_task(), later)
        twice_delivered = confirm_delivery(second, later)
        self.assertEqual(twice_delivered.escalation_level, delivered.escalation_level)
        third = decide(twice_delivered, off_task(), later + minutes(COOLDOWN_MINUTES) + ONE_MINUTE)
        self.assertIs(third.action, NudgeAction.NUDGE_ESCALATED)
        self.assertTrue(third.command.sound)

    def test_escalation_advances_only_on_a_confirmed_delivery(self):
        fired = decide(fresh_state(streak=1), off_task(), MIDDAY)
        # the delivery is never confirmed, as if posting it failed
        retry = decide(fired.state, off_task(), MIDDAY + ONE_MINUTE)
        self.assertIs(retry.action, NudgeAction.NUDGE)
        self.assertFalse(retry.command.sound)
        self.assertIsNone(retry.state.last_nudge_epoch)
        self.assertEqual(retry.state.escalation_level, 0)

    def test_escalation_resets_with_the_streak(self):
        delivered = deliver_two_strike_episode(MIDDAY)
        back_on_task = decide(delivered, on_task(), MIDDAY + FIVE_MINUTES)
        self.assertEqual(back_on_task.state.escalation_level, 0)
        # the earlier delivery's cooldown window still holds -- a streak
        # reset never shortens it -- so the next episode plays out after it
        later = MIDDAY + ONE_MINUTE + minutes(COOLDOWN_MINUTES) + FIVE_MINUTES
        next_check = decide(back_on_task.state, off_task(), later)
        second_check = decide(next_check.state, off_task(), later + ONE_MINUTE)
        self.assertIs(second_check.action, NudgeAction.NUDGE)
        self.assertFalse(second_check.command.sound)

    def test_confirming_a_silent_decision_is_rejected(self):
        silent = decide(fresh_state(), off_task(), MIDDAY)
        with self.assertRaises(ValueError):
            confirm_delivery(silent, MIDDAY)

    def test_confirmation_records_the_bookkeeping(self):
        fired = decide(fresh_state(streak=1), off_task(), MIDDAY)
        confirmed = confirm_delivery(fired, MIDDAY)
        self.assertAlmostEqual(confirmed.last_nudge_epoch, MIDDAY.timestamp())
        self.assertEqual(confirmed.escalation_level, 1)
        self.assertEqual(confirmed.streak, 2)
        # the day key belongs to the store's rollover, not the delivery
        self.assertEqual(confirmed.day_key, fired.state.day_key)


class QuietHoursInsideTheDecisionTest(unittest.TestCase):
    def test_a_candidate_during_quiet_hours_stays_silent_and_keeps_counting(self):
        night = datetime.datetime(2026, 8, 28, 23, 30)
        first = decide(fresh_state(), off_task(), night)
        second = decide(first.state, off_task(), night + ONE_MINUTE)
        self.assertIs(second.action, NudgeAction.SILENT)
        self.assertIsNone(second.command)
        self.assertEqual(second.state.streak, 2)
        # a suppressed nudge anchors no cooldown window
        self.assertIsNone(second.state.last_nudge_epoch)

    def test_a_distraction_nudge_resumes_after_quiet_hours(self):
        night = datetime.datetime(2026, 8, 28, 23, 30)
        first = decide(fresh_state(), off_task(), night)
        suppressed = decide(first.state, off_task(), night + ONE_MINUTE)
        morning = datetime.datetime(2026, 8, 29, 9, 5)
        resumed = decide(suppressed.state, off_task(), morning)
        self.assertIs(resumed.action, NudgeAction.NUDGE)
        # nothing was delivered overnight, so the resumed nudge is still the
        # episode's silent first
        self.assertFalse(resumed.command.sound)
        # the streak survived the night
        self.assertEqual(resumed.state.streak, 3)


class OneNudgePerCycleAndSwitchTest(unittest.TestCase):
    def test_one_nudge_per_cycle_with_a_single_command(self):
        one_strike_from_an_episode = fresh_state(streak=NUDGE_STRIKES_REQUIRED - 1)
        decision = decide(one_strike_from_an_episode, off_task(), MIDDAY)
        self.assertIs(decision.action, NudgeAction.NUDGE)
        self.assertIsNotNone(decision.command)
        self.assertIs(decision.cause, NudgeCause.DISTRACTION)

    def test_distraction_is_the_only_nudge_cause(self):
        # the decision type exposes exactly one cause, so no second
        # trigger can be reintroduced without breaking this pin
        self.assertEqual(
            {member.name for member in NudgeCause}, {"DISTRACTION"}
        )

    def test_decide_takes_no_limit_argument(self):
        # a limit-progress feed can only come back through the signature;
        # pinning the whole parameter list keeps the decision core
        # single-cause
        self.assertEqual(
            list(inspect.signature(decide).parameters),
            ["state", "verdict", "now"],
        )


class TitleOnlyNotificationTest(unittest.TestCase):
    """The offending card's own name is the whole notification.

    The title is the card title and the body stays empty; the fixed
    standing line stands in only for a title that strips to empty, so a
    degenerate empty card can never produce an invisible notification.
    """

    def test_the_card_title_is_the_headline_and_the_body_stays_empty(self):
        decision = decide(
            fresh_state(streak=NUDGE_STRIKES_REQUIRED - 1),
            off_task(evidence="Reddit scroll"), MIDDAY)
        self.assertEqual(decision.command.title, "Reddit scroll")
        self.assertEqual(decision.command.body, "")

    def test_a_title_that_strips_to_empty_falls_back_to_the_standing_line(self):
        decision = decide(
            fresh_state(streak=NUDGE_STRIKES_REQUIRED - 1),
            off_task(evidence="   "), MIDDAY)
        self.assertEqual(decision.command.title, "Distraction noticed")
        self.assertEqual(decision.command.body, "")

    def test_the_decision_core_exposes_the_kill_switch(self):
        self.assertTrue(should_suppress_for_kill_switch({"DFN_DISABLE": "1"}))
        self.assertFalse(should_suppress_for_kill_switch({}))

    def test_the_rule_constants_are_pinned(self):
        self.assertEqual(NUDGE_STRIKES_REQUIRED, 2)
        self.assertEqual(COOLDOWN_MINUTES, 15)


if __name__ == "__main__":
    unittest.main()
