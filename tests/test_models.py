"""Behavior of the shared handoff values exchanged between daemon stages.

The values below are the whole contract between stages: each one must be
constructible from the fields its producer has, immutable once built, and
comparable by value. A stage that cannot rely on those properties cannot
hand anything to the next stage safely.
"""

import dataclasses
import unittest
from datetime import datetime

from dayflow_nudge import detector_distraction, goal_provider, models


class CardSnapshotTest(unittest.TestCase):
    def test_carries_the_fields_mapped_from_a_timeline_card(self):
        card = models.CardSnapshot(
            title="News site",
            summary="Browsing articles",
            category="Distraction",
            start_ts=datetime(2026, 8, 28, 12, 0, 0),
            end_ts=datetime(2026, 8, 28, 12, 5, 0),
            metadata={"app": "Safari"},
        )

        self.assertEqual(card.title, "News site")
        self.assertEqual(card.summary, "Browsing articles")
        self.assertEqual(card.category, "Distraction")
        self.assertEqual(card.start_ts, datetime(2026, 8, 28, 12, 0, 0))
        self.assertEqual(card.end_ts, datetime(2026, 8, 28, 12, 5, 0))
        self.assertEqual(card.metadata, {"app": "Safari"})

    def test_tolerates_missing_timestamps_and_metadata(self):
        card = models.CardSnapshot(title="t", summary="s", category="c")

        self.assertIsNone(card.start_ts)
        self.assertIsNone(card.end_ts)
        self.assertIsNone(card.metadata)

    def test_is_an_immutable_value(self):
        card = models.CardSnapshot(title="t", summary="s", category="c")
        twin = models.CardSnapshot(title="t", summary="s", category="c")

        self.assertEqual(card, twin)
        self.assertEqual(hash(card), hash(twin))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            card.title = "changed"


class GoalSnapshotTest(unittest.TestCase):
    def test_carries_the_day_goal_fields(self):
        goal = models.GoalSnapshot(
            day="2026-08-28",
            focus_target_minutes=240,
            distraction_limit_minutes=45,
            is_skipped=True,
        )

        self.assertEqual(goal.day, "2026-08-28")
        self.assertEqual(goal.focus_target_minutes, 240)
        self.assertEqual(goal.distraction_limit_minutes, 45)
        self.assertTrue(goal.is_skipped)

    def test_defaults_to_an_active_goal_with_unset_minutes(self):
        goal = models.GoalSnapshot(day="2026-08-28")

        self.assertFalse(goal.is_skipped)
        self.assertIsNone(goal.focus_target_minutes)
        self.assertIsNone(goal.distraction_limit_minutes)
        self.assertEqual(goal.distraction_categories, frozenset())

    def test_carries_the_day_s_distraction_category_selection(self):
        goal = models.GoalSnapshot(
            day="2026-08-28", distraction_categories=frozenset({"youtube", "news"})
        )

        self.assertEqual(goal.distraction_categories, frozenset({"youtube", "news"}))

    def test_an_empty_category_selection_is_the_fallback_signal(self):
        # The empty set is not "no goal": it means nothing was selected
        # for today, and the detector answers with its fallback rule.
        goal = models.GoalSnapshot(day="2026-08-28")

        self.assertEqual(goal.distraction_categories, frozenset())


class NormalizeCategoryTest(unittest.TestCase):
    """The one shared rule for reading a category name.

    The strip-and-casefold rule for category names is defined exactly
    once, here beside the values it serves, and both consumers -- the
    goal producer and the distraction detector -- read names through
    that same definition, so no local spelling of the rule can drift
    apart from the rest.
    """

    def shared_rule(self):
        rule = getattr(models, "normalize_category", None)
        self.assertIsNotNone(
            rule, "models must carry the one shared normalize_category")
        return rule

    def test_strips_padding_and_folds_case(self):
        self.assertEqual(self.shared_rule()("  YouTube  "), "youtube")
        self.assertEqual(self.shared_rule()("DISTRACTION"), "distraction")

    def test_a_blank_name_stays_empty_and_a_non_text_value_is_none(self):
        self.assertEqual(self.shared_rule()("   "), "")
        self.assertIsNone(self.shared_rule()(None))

    def test_both_consumers_read_the_one_shared_rule(self):
        shared = self.shared_rule()
        self.assertIs(goal_provider.normalize_category, shared)
        self.assertIs(detector_distraction.normalize_category, shared)

    def test_no_private_twin_of_the_rule_survives(self):
        self.assertFalse(hasattr(goal_provider, "_normalize"))
        self.assertFalse(
            hasattr(detector_distraction, "_normalized_category"))


class RemovedLimitContractsTest(unittest.TestCase):
    """The daily-limit cause is gone end to end, so its shared types are too.

    The module's public surface is pinned exactly: a type that survives
    unused invites a future module to revive the removed cause, and a new
    cross-stage type must land here deliberately, not slip in unnamed.
    """

    def test_the_module_exports_exactly_the_eight_handoff_values(self):
        exported = sorted(
            name for name, value in vars(models).items()
            if isinstance(value, type) and value.__module__ == models.__name__
        )
        self.assertEqual(
            exported,
            ["CardSnapshot", "DeliveryResult", "DetectionState",
             "GoalSnapshot", "NudgeCommand", "Observation",
             "PersistedNudgeState", "Verdict"],
        )


class ObservationTest(unittest.TestCase):
    def test_merges_the_card_window_and_goal_into_one_input(self):
        card = models.CardSnapshot(title="t", summary="s", category="Distraction")
        goal = models.GoalSnapshot(day="2026-08-28")
        observed_at = datetime(2026, 8, 28, 12, 10, 0)

        observation = models.Observation(
            observed_at=observed_at, cards=(card,), goal=goal
        )

        self.assertEqual(observation.observed_at, observed_at)
        self.assertEqual(observation.cards, (card,))
        self.assertEqual(observation.goal, goal)

    def test_defaults_to_an_empty_window(self):
        observation = models.Observation()

        self.assertIsNone(observation.observed_at)
        self.assertEqual(observation.cards, ())
        self.assertIsNone(observation.goal)


class DetectionStateTest(unittest.TestCase):
    def test_exposes_exactly_the_three_verdict_states(self):
        self.assertEqual(
            {member.name for member in models.DetectionState},
            {"ON_TASK", "OFF_TASK", "UNKNOWN"},
        )

    def test_compares_with_its_persisted_text_form(self):
        self.assertEqual(models.DetectionState.ON_TASK, "ON_TASK")
        self.assertEqual(models.DetectionState.OFF_TASK, "OFF_TASK")
        self.assertEqual(models.DetectionState.UNKNOWN, "UNKNOWN")


class VerdictTest(unittest.TestCase):
    def test_carries_the_detection_result(self):
        verdict = models.Verdict(
            state=models.DetectionState.OFF_TASK,
            off_task=True,
            evidence="News site",
            latency=42.0,
        )

        self.assertIs(verdict.state, models.DetectionState.OFF_TASK)
        self.assertTrue(verdict.off_task)
        self.assertEqual(verdict.evidence, "News site")
        self.assertEqual(verdict.latency, 42.0)

    def test_defaults_to_no_evidence_and_zero_latency(self):
        verdict = models.Verdict(
            state=models.DetectionState.UNKNOWN, off_task=False
        )

        self.assertEqual(verdict.evidence, "")
        self.assertEqual(verdict.latency, 0.0)

    def test_is_an_immutable_value(self):
        verdict = models.Verdict(
            state=models.DetectionState.ON_TASK, off_task=False
        )

        with self.assertRaises(dataclasses.FrozenInstanceError):
            verdict.off_task = True


class NudgeCommandTest(unittest.TestCase):
    def test_carries_title_body_and_sound(self):
        command = models.NudgeCommand(
            title="Distraction noticed", body="Back to focus?", sound=True
        )

        self.assertEqual(command.title, "Distraction noticed")
        self.assertEqual(command.body, "Back to focus?")
        self.assertTrue(command.sound)

    def test_is_silent_by_default(self):
        command = models.NudgeCommand(title="t", body="b")

        self.assertFalse(command.sound)


class DeliveryResultTest(unittest.TestCase):
    def test_exposes_exactly_sent_and_failed(self):
        self.assertEqual(
            {member.name for member in models.DeliveryResult},
            {"SENT", "FAILED"},
        )

    def test_compares_with_its_persisted_text_form(self):
        self.assertEqual(models.DeliveryResult.SENT, "SENT")
        self.assertEqual(models.DeliveryResult.FAILED, "FAILED")


class PersistedNudgeStateTest(unittest.TestCase):
    def test_defaults_to_a_fresh_anti_spam_state(self):
        state = models.PersistedNudgeState()

        self.assertEqual(state.schema_version, 2)
        self.assertEqual(state.streak, 0)
        self.assertIsNone(state.last_nudge_epoch)
        self.assertEqual(state.escalation_level, 0)
        self.assertEqual(state.day_key, "")

    def test_round_trips_the_five_persisted_keys(self):
        state = models.PersistedNudgeState(
            schema_version=2,
            streak=2,
            last_nudge_epoch=1770000000.0,
            escalation_level=1,
            day_key="2026-08-28",
        )

        self.assertEqual(state.schema_version, 2)
        self.assertEqual(state.streak, 2)
        self.assertEqual(state.last_nudge_epoch, 1770000000.0)
        self.assertEqual(state.escalation_level, 1)
        self.assertEqual(state.day_key, "2026-08-28")

    def test_carries_no_fired_threshold_field(self):
        # The limit-threshold marks went with the limit cause; a stale key
        # in an old file is the store's affair, never the record's.
        self.assertFalse(hasattr(models.PersistedNudgeState(), "fired_thresholds"))

    def test_updates_functionally_without_mutation(self):
        state = models.PersistedNudgeState(streak=1)

        advanced = dataclasses.replace(state, streak=2)

        self.assertEqual(state.streak, 1)
        self.assertEqual(advanced.streak, 2)


if __name__ == "__main__":
    unittest.main()
