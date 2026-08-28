"""Behavior of the kill switch.

Setting the disable variable to exactly "1" stops all nudging. The check
reads the per-cycle environment mapping every time it is asked, so arming
and disarming take effect on the very next tick, and it never touches any
persisted counter -- disarming resumes exactly where the counters left off.
"""

import unittest

from dayflow_nudge.kill_switch import ARMED_VALUE, DFN_DISABLE, is_armed
from dayflow_nudge.nudge_policy import should_suppress_for_kill_switch


class KillSwitchArmingTest(unittest.TestCase):
    def test_exactly_one_arms_the_switch(self):
        self.assertTrue(is_armed({DFN_DISABLE: "1"}))

    def test_an_unset_variable_leaves_the_switch_disarmed(self):
        self.assertFalse(is_armed({}))

    def test_any_other_value_leaves_the_switch_disarmed(self):
        for value in ("", "0", "true", "yes", " 1", "1 ", "01"):
            with self.subTest(value=value):
                self.assertFalse(is_armed({DFN_DISABLE: value}))

    def test_the_armed_value_is_pinned_to_one(self):
        self.assertEqual(ARMED_VALUE, "1")


class KillSwitchFreshnessTest(unittest.TestCase):
    def test_the_flag_is_reread_on_every_call(self):
        # nothing is cached between cycles: one live mapping flips as the
        # user flips the variable, in both directions
        environment = {DFN_DISABLE: "0"}
        self.assertFalse(is_armed(environment))
        environment[DFN_DISABLE] = ARMED_VALUE
        self.assertTrue(is_armed(environment))
        del environment[DFN_DISABLE]
        self.assertFalse(is_armed(environment))

    def test_the_check_takes_no_state_and_changes_nothing(self):
        # the switch owns no counters: it answers from the environment alone,
        # so the same question asked twice keeps answering the same way
        environment = {DFN_DISABLE: ARMED_VALUE}
        self.assertTrue(is_armed(environment))
        self.assertTrue(is_armed(environment))
        self.assertEqual(environment, {DFN_DISABLE: ARMED_VALUE})


class KillSwitchThroughThePolicyTest(unittest.TestCase):
    def test_the_decision_core_exposes_the_same_switch(self):
        self.assertTrue(should_suppress_for_kill_switch({DFN_DISABLE: "1"}))
        self.assertFalse(should_suppress_for_kill_switch({}))

    def test_the_policy_switch_follows_the_environment_not_memory(self):
        environment = {}
        self.assertFalse(should_suppress_for_kill_switch(environment))
        environment[DFN_DISABLE] = ARMED_VALUE
        self.assertTrue(should_suppress_for_kill_switch(environment))


if __name__ == "__main__":
    unittest.main()
