"""Behavior of the pluggable detection seam.

The seam must let a detection variant be written, registered, and run
without any change to the surrounding daemon, and it must refuse every
way of bending the contract (abstract contract instances, non-detector
classes, duplicate or blank ids, unregistered ids).
"""

import unittest
from datetime import datetime

from dayflow_nudge import detector_api, models


STUB_ID = "seam-test-variant"
SECOND_STUB_ID = "seam-test-second-variant"


class WindowCategoryDetector(detector_api.Detector):
    """A stand-in variant: classifies the newest card by its category."""

    def detect(self, observation, state):
        if not observation.cards:
            return models.Verdict(
                state=models.DetectionState.UNKNOWN, off_task=False
            )
        newest = observation.cards[-1]
        off_task = "distraction" in newest.category.strip().casefold()
        return models.Verdict(
            state=(
                models.DetectionState.OFF_TASK
                if off_task
                else models.DetectionState.ON_TASK
            ),
            off_task=off_task,
            evidence=newest.title,
        )


class AlwaysOnTaskDetector(detector_api.Detector):
    """A second stand-in used to prove ids stay independent."""

    def detect(self, observation, state):
        return models.Verdict(state=models.DetectionState.ON_TASK, off_task=False)


def _forget_stub_variants():
    for variant_id in (STUB_ID, SECOND_STUB_ID):
        try:
            detector_api.unregister(variant_id)
        except ValueError:
            pass


class DetectorSeamTest(unittest.TestCase):
    def setUp(self):
        detector_api.register(STUB_ID, WindowCategoryDetector)
        self.addCleanup(_forget_stub_variants)

    def test_registered_variant_returns_a_typed_verdict(self):
        detector = detector_api.create_detector(STUB_ID)
        observation = models.Observation(
            observed_at=datetime(2026, 8, 28, 12, 10, 0),
            cards=(
                models.CardSnapshot(
                    title="Video rabbit hole",
                    summary="Watching",
                    category="Distraction",
                ),
            ),
            goal=None,
        )

        verdict = detector.detect(observation, models.PersistedNudgeState())

        self.assertEqual(verdict.state, models.DetectionState.OFF_TASK)
        self.assertTrue(verdict.off_task)
        self.assertEqual(verdict.evidence, "Video rabbit hole")

    def test_registered_variant_can_report_an_unknown_window(self):
        detector = detector_api.create_detector(STUB_ID)

        verdict = detector.detect(
            models.Observation(), models.PersistedNudgeState()
        )

        self.assertEqual(verdict.state, models.DetectionState.UNKNOWN)
        self.assertFalse(verdict.off_task)
        self.assertEqual(verdict.evidence, "")

    def test_a_new_variant_plugs_in_without_changing_the_seam(self):
        detector_api.register(SECOND_STUB_ID, AlwaysOnTaskDetector)

        registered = detector_api.registered_variants()

        self.assertIn(STUB_ID, registered)
        self.assertIn(SECOND_STUB_ID, registered)
        self.assertIsInstance(
            detector_api.create_detector(SECOND_STUB_ID), AlwaysOnTaskDetector
        )

    def test_the_contract_cannot_be_instantiated_directly(self):
        with self.assertRaises(TypeError):
            detector_api.Detector()

    def test_registration_rejects_classes_outside_the_contract(self):
        with self.assertRaises(ValueError):
            detector_api.register("not-a-variant", object)

    def test_registration_rejects_a_duplicate_variant_id(self):
        with self.assertRaises(ValueError):
            detector_api.register(STUB_ID, AlwaysOnTaskDetector)

    def test_registration_rejects_a_blank_variant_id(self):
        with self.assertRaises(ValueError):
            detector_api.register("", AlwaysOnTaskDetector)

    def test_creation_rejects_an_unregistered_variant(self):
        with self.assertRaises(ValueError):
            detector_api.create_detector("never-registered")

    def test_unregistering_retires_a_variant(self):
        detector_api.unregister(STUB_ID)

        self.assertNotIn(STUB_ID, detector_api.registered_variants())
        with self.assertRaises(ValueError):
            detector_api.create_detector(STUB_ID)


if __name__ == "__main__":
    unittest.main()
