"""Behavior of the timeline-category distraction detector.

Every test drives the public detection contract end to end -- observations
in, verdicts out -- and obtains the detector the way the daemon does,
through the detector registry. The match reads nothing but the card
category against the day's selected distraction categories, so no wording
in a title, a summary, or a goal can swing a verdict.
"""

import unittest
from datetime import datetime, timedelta

from dayflow_nudge import detector_api, models
from dayflow_nudge.detector_distraction import (
    ACTIVE_WINDOW_MINUTES,
    DistractionDetector,
    VARIANT_ID,
    is_distraction_category,
)

OBSERVED_AT = datetime(2026, 8, 28, 12, 0, 0)


def card_at(category, started_seconds_before, duration_seconds=0,
            title="", summary=""):
    """One timeline card placed by offset against the fixed observation."""
    started = OBSERVED_AT - timedelta(seconds=started_seconds_before)
    ended = started + timedelta(seconds=duration_seconds)
    return models.CardSnapshot(
        title=title,
        summary=summary,
        category=category,
        start_ts=started,
        end_ts=ended,
    )


def observe(*cards, goal=None, observed_at=OBSERVED_AT):
    """One merged observation over the given cards."""
    return models.Observation(
        observed_at=observed_at, cards=cards, goal=goal,
    )


class CategoryMatchingTests(unittest.TestCase):
    """The verdict follows the card category, normalized for case and padding."""

    def test_padded_and_recased_distraction_categories_flag_off_task(self):
        detector = DistractionDetector()
        for category in ("Distraction", "  distraction  ", "DISTRACTION",
                         "Distraction - Social feeds"):
            with self.subTest(category=category):
                verdict = detector.detect(
                    observe(card_at(category, 5 * 60, title="Video spiral")),
                    models.PersistedNudgeState(),
                )
                self.assertEqual(verdict.state, models.DetectionState.OFF_TASK)
                self.assertTrue(verdict.off_task)

    def test_other_or_empty_categories_stay_on_task(self):
        detector = DistractionDetector()
        for category in ("", "Communication", "Coding - deep work"):
            with self.subTest(category=category):
                verdict = detector.detect(
                    observe(card_at(category, 5 * 60)),
                    models.PersistedNudgeState(),
                )
                self.assertEqual(verdict.state, models.DetectionState.ON_TASK)
                self.assertFalse(verdict.off_task)
                self.assertEqual(verdict.evidence, "")

    def test_the_category_rule_is_normalized_containment(self):
        for category in ("Distraction", "  distraction  ", "DISTRACTION",
                         "Distraction - Social feeds"):
            self.assertTrue(is_distraction_category(category), category)
        for category in ("", "Communication", "Focus work", None):
            self.assertFalse(is_distraction_category(category), category)


class TriggerSetTests(unittest.TestCase):
    """Today's selected categories decide; the substring rule is the fallback.

    One effective predicate governs each check: membership in the day's
    distraction-category set when the set is armed, the legacy normalized
    substring rule otherwise. The same predicate picks the deciding card
    and judges it, so a boundary tie can never be preferred by one rule
    and labeled by the other.
    """

    def goal_with(self, *categories):
        return models.GoalSnapshot(
            day="2026-08-28",
            distraction_categories=frozenset(categories),
        )

    def test_a_card_in_the_day_s_selection_flags_off_task(self):
        detector = DistractionDetector()
        verdict = detector.detect(
            observe(card_at("YouTube", 5 * 60, title="Video spiral"),
                    goal=self.goal_with("youtube")),
            models.PersistedNudgeState(),
        )
        self.assertEqual(verdict.state, models.DetectionState.OFF_TASK)
        self.assertTrue(verdict.off_task)
        self.assertEqual(verdict.evidence, "Video spiral")

    def test_one_member_of_a_multi_category_selection_decides_the_match(self):
        # Several categories may be selected at once; matching any one of
        # them flags the card, and a sibling category outside the set does
        # not, under the same armed selection.
        detector = DistractionDetector()
        selection = self.goal_with("youtube", "news", "games")
        member = detector.detect(
            observe(card_at("News", 5 * 60), goal=selection),
            models.PersistedNudgeState(),
        )
        self.assertEqual(member.state, models.DetectionState.OFF_TASK)
        self.assertTrue(member.off_task)
        non_member = detector.detect(
            observe(card_at("Coding", 5 * 60), goal=selection),
            models.PersistedNudgeState(),
        )
        self.assertEqual(non_member.state, models.DetectionState.ON_TASK)
        self.assertFalse(non_member.off_task)

    def test_membership_is_judged_on_the_normalized_card_category(self):
        detector = DistractionDetector()
        for category in ("YouTube", "  youtube  ", "YOUTUBE"):
            with self.subTest(category=category):
                verdict = detector.detect(
                    observe(card_at(category, 5 * 60),
                            goal=self.goal_with("youtube")),
                    models.PersistedNudgeState(),
                )
                self.assertEqual(verdict.state, models.DetectionState.OFF_TASK)

    def test_an_armed_selection_replaces_the_substring_rule(self):
        detector = DistractionDetector()
        verdict = detector.detect(
            observe(card_at("Distraction - social feeds", 5 * 60),
                    goal=self.goal_with("news")),
            models.PersistedNudgeState(),
        )
        self.assertEqual(verdict.state, models.DetectionState.ON_TASK)
        self.assertFalse(verdict.off_task)
        self.assertEqual(verdict.evidence, "")

    def test_an_empty_selection_falls_back_to_the_substring_rule(self):
        detector = DistractionDetector()
        verdict = detector.detect(
            observe(card_at("Distraction", 5 * 60),
                    goal=self.goal_with()),
            models.PersistedNudgeState(),
        )
        self.assertEqual(verdict.state, models.DetectionState.OFF_TASK)

    def test_an_absent_goal_reduces_to_the_empty_selection(self):
        detector = DistractionDetector()
        by_substring = detector.detect(
            observe(card_at("Distraction", 5 * 60), goal=None),
            models.PersistedNudgeState(),
        )
        self.assertEqual(by_substring.state, models.DetectionState.OFF_TASK)

        unselected = detector.detect(
            observe(card_at("YouTube", 5 * 60), goal=None),
            models.PersistedNudgeState(),
        )
        self.assertEqual(unselected.state, models.DetectionState.ON_TASK)

    def test_the_selection_governs_which_card_decides_the_window(self):
        # The newest card decides, and the armed set judges it: a card
        # the substring rule would call off task stays on task because
        # the day's selection says so -- one rule picks and labels.
        detector = DistractionDetector()
        member_card = card_at("Admin", 14 * 60, title="Older admin card")
        substring_card = card_at("Distraction", 5 * 60)
        verdict = detector.detect(
            observe(member_card, substring_card, goal=self.goal_with("admin")),
            models.PersistedNudgeState(),
        )
        self.assertEqual(verdict.state, models.DetectionState.ON_TASK)
        self.assertEqual(verdict.evidence, "")

        newest_member = card_at("Admin", 5 * 60, title="Newest admin card")
        older_non_member = card_at("Coding", 14 * 60)
        verdict = detector.detect(
            observe(newest_member, older_non_member,
                    goal=self.goal_with("admin")),
            models.PersistedNudgeState(),
        )
        self.assertEqual(verdict.state, models.DetectionState.OFF_TASK)
        self.assertEqual(verdict.evidence, "Newest admin card")

    def test_a_tied_start_still_resolves_toward_on_task_under_the_set(self):
        detector = DistractionDetector()
        member = card_at("YouTube", 5 * 60)
        non_member = card_at("Coding", 5 * 60)
        for cards in ((member, non_member), (non_member, member)):
            with self.subTest(cards=cards):
                verdict = detector.detect(
                    observe(*cards, goal=self.goal_with("youtube")),
                    models.PersistedNudgeState(),
                )
                self.assertEqual(verdict.state, models.DetectionState.ON_TASK)
                self.assertFalse(verdict.off_task)


class WordingIndependenceTests(unittest.TestCase):
    """Titles, summaries, goals, and counters never influence the verdict."""

    def test_distraction_wording_in_a_title_or_summary_does_not_flag(self):
        detector = DistractionDetector()
        card = card_at("Coding", 5 * 60,
                       title="distraction everywhere",
                       summary="totally distracted")
        verdict = detector.detect(observe(card), models.PersistedNudgeState())
        self.assertEqual(verdict.state, models.DetectionState.ON_TASK)
        self.assertFalse(verdict.off_task)
        self.assertEqual(verdict.evidence, "")

    def test_goal_minutes_never_change_the_verdict(self):
        # The goal's minute columns are visible on the snapshot yet carry
        # no match meaning; only the category selection does.
        detector = DistractionDetector()
        cards = (card_at("Distraction", 5 * 60),)
        without_goal = detector.detect(
            observe(*cards), models.PersistedNudgeState())
        with_goal = detector.detect(
            observe(*cards, goal=models.GoalSnapshot(
                day="2026-08-28",
                focus_target_minutes=1,
                distraction_limit_minutes=1,
            )),
            models.PersistedNudgeState(),
        )
        self.assertEqual(without_goal.state, with_goal.state)
        self.assertEqual(without_goal.off_task, with_goal.off_task)

    def test_the_persisted_state_argument_leaves_the_verdict_unchanged(self):
        detector = DistractionDetector()
        observation = observe(card_at("Distraction", 5 * 60))
        baseline = detector.detect(observation, models.PersistedNudgeState())
        loaded = detector.detect(
            observation,
            models.PersistedNudgeState(
                streak=7,
                last_nudge_epoch=1_800_000_000.0,
                escalation_level=1,
                day_key="2026-08-28",
            ),
        )
        self.assertEqual(baseline.state, loaded.state)
        self.assertEqual(baseline.off_task, loaded.off_task)


class EvidenceTests(unittest.TestCase):
    """An off-task verdict shows the offending card, nothing else."""

    def test_off_task_verdict_carries_the_offending_title(self):
        detector = DistractionDetector()
        verdict = detector.detect(
            observe(card_at("Distraction", 5 * 60, title="  Short video spiral  ")),
            models.PersistedNudgeState(),
        )
        self.assertEqual(verdict.evidence, "Short video spiral")

    def test_off_task_verdict_without_a_title_has_empty_evidence(self):
        detector = DistractionDetector()
        verdict = detector.detect(
            observe(card_at("Distraction", 5 * 60, title="")),
            models.PersistedNudgeState(),
        )
        self.assertEqual(verdict.evidence, "")

    def test_off_task_latency_is_the_age_of_the_evidence(self):
        detector = DistractionDetector()
        verdict = detector.detect(
            observe(card_at("Distraction", 5 * 60)),
            models.PersistedNudgeState(),
        )
        self.assertEqual(verdict.latency, 5 * 60.0)


class ActiveWindowTests(unittest.TestCase):
    """Only the card with the latest END inside the active window decides.

    Membership is judged by end_ts -- the last known moment of the
    activity -- so long merged cards stay visible however old their
    start is (a start-based window was structurally blind to them)."""

    def test_no_card_in_the_window_reports_unknown(self):
        detector = DistractionDetector()
        # started 40 min ago, ran 10 -> ended 30 min ago: outside.
        ended_long_ago = card_at("Distraction", 40 * 60,
                                 duration_seconds=10 * 60)
        for cards in ((), (ended_long_ago,)):
            with self.subTest(cards=cards):
                verdict = detector.detect(
                    observe(*cards), models.PersistedNudgeState())
                self.assertEqual(verdict.state, models.DetectionState.UNKNOWN)
                self.assertFalse(verdict.off_task)
                self.assertEqual(verdict.evidence, "")

    def test_the_card_with_the_latest_end_decides(self):
        detector = DistractionDetector()
        # stale work ended 30 min ago; fresh distraction ended 5 min ago.
        stale_work = card_at("Coding", 40 * 60, duration_seconds=10 * 60)
        fresh_distraction = card_at("Distraction", 20 * 60,
                                    duration_seconds=15 * 60)
        verdict = detector.detect(
            observe(stale_work, fresh_distraction),
            models.PersistedNudgeState())
        self.assertEqual(verdict.state, models.DetectionState.OFF_TASK)

        older_distraction = card_at("Distraction", 30 * 60,
                                    duration_seconds=5 * 60)
        newest_work = card_at("Coding", 20 * 60, duration_seconds=15 * 60)
        verdict = detector.detect(
            observe(older_distraction, newest_work),
            models.PersistedNudgeState())
        self.assertEqual(verdict.state, models.DetectionState.ON_TASK)

    def test_a_long_merged_card_is_judged_by_its_end(self):
        # Incident 2026-08-29: the generator merged 30 minutes of
        # contiguous distraction into ONE card. Its start is older than
        # any start-window could ever be, but its end -- the last known
        # moment of the activity -- is fresh. The detector must see it.
        detector = DistractionDetector()
        long_card = card_at("Distraction", 40 * 60,
                            duration_seconds=30 * 60)
        verdict = detector.detect(
            observe(long_card), models.PersistedNudgeState())
        self.assertEqual(verdict.state, models.DetectionState.OFF_TASK)
        self.assertTrue(verdict.off_task)

    def test_cards_barely_outside_the_window_are_ignored(self):
        detector = DistractionDetector()
        edge = ACTIVE_WINDOW_MINUTES * 60
        # ends exactly at the window edge -> still counts.
        at_the_edge = detector.detect(
            observe(card_at("Distraction", edge + 10 * 60,
                            duration_seconds=10 * 60)),
            models.PersistedNudgeState(),
        )
        self.assertEqual(at_the_edge.state, models.DetectionState.OFF_TASK)

        # ends one second past the edge -> ignored.
        past_the_edge = detector.detect(
            observe(card_at("Distraction", edge + 10 * 60 + 1,
                            duration_seconds=10 * 60)),
            models.PersistedNudgeState(),
        )
        self.assertEqual(past_the_edge.state, models.DetectionState.UNKNOWN)

    def test_a_card_dated_in_the_future_is_ignored(self):
        detector = DistractionDetector()
        verdict = detector.detect(
            observe(card_at("Distraction", -5 * 60)),
            models.PersistedNudgeState())
        self.assertEqual(verdict.state, models.DetectionState.UNKNOWN)

    def test_tied_ends_resolve_toward_on_task(self):
        detector = DistractionDetector()
        distraction = card_at("Distraction", 10 * 60,
                              duration_seconds=5 * 60)
        work = card_at("Coding", 10 * 60, duration_seconds=5 * 60)
        for cards in ((distraction, work), (work, distraction)):
            with self.subTest(cards=cards):
                verdict = detector.detect(
                    observe(*cards), models.PersistedNudgeState())
                self.assertEqual(
                    verdict.state, models.DetectionState.ON_TASK)


class PinnedContract(unittest.TestCase):
    """Published tuning values; a silent change must fail the suite."""

    def test_a_card_that_just_landed_after_pipeline_lag_still_counts(self):
        # Production lag scenario (incident 2026-08-29): a 15-minute batch
        # closes, then ~3 minutes of transcription pass before the card
        # exists. At landing its start is already 18 minutes old -- the
        # active window must still see it, or the detector is blind to
        # every real distraction card (the window was 15 and never fired).
        card = card_at("Distraction", started_seconds_before=18 * 60,
                       duration_seconds=15 * 60, title="Reddit scroll")
        verdict = DistractionDetector().detect(observe(card), models.PersistedNudgeState())
        self.assertTrue(verdict.off_task)

    def test_the_active_window_exceeds_batch_length_plus_processing(self):
        # The invariant the incident taught: batch windows are 15 minutes
        # and processing adds minutes, so a window at or below 15 can never
        # see a freshly landed card.
        self.assertGreater(ACTIVE_WINDOW_MINUTES, 15)

    def test_active_window_is_pinned_at_fifteen_minutes(self):
        self.assertEqual(ACTIVE_WINDOW_MINUTES, 25)


class RegistryTests(unittest.TestCase):
    """The daemon reaches this variant through the registry alone."""

    def test_the_detector_is_created_through_the_registry(self):
        detector = detector_api.create_detector(VARIANT_ID)
        self.assertIsInstance(detector, DistractionDetector)

        verdict = detector.detect(
            observe(card_at("Distraction", 5 * 60, title="Registry check")),
            models.PersistedNudgeState(),
        )
        self.assertEqual(verdict.state, models.DetectionState.OFF_TASK)
        self.assertEqual(verdict.evidence, "Registry check")

    def test_the_variant_is_registered_under_its_stable_id(self):
        self.assertIn("distraction", detector_api.registered_variants())
        self.assertEqual(VARIANT_ID, "distraction")


if __name__ == "__main__":
    unittest.main()
