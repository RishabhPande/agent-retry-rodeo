"""Status writes must use real version integers, before any fault is consumed."""
import copy
from pathlib import Path
import unittest

from agent_retry_rodeo.engine import World, load_scenario, run

ROOT = Path(__file__).resolve().parents[1]

class VersionContractTests(unittest.TestCase):
    def world(self, fixture='01-lost-ack.yaml'):
        return World(load_scenario(ROOT / 'scenarios' / fixture), 42)

    def test_boolean_and_float_versions_cannot_authorize_writes(self):
        for value in (True, False, 1.0, '1', None, [], {}, 0, -1):
            with self.subTest(value=value):
                world = self.world()
                initial = copy.deepcopy(world.state)
                with self.assertRaisesRegex(ValueError, 'positive integer'):
                    world.call('set_status', status='resolved', expected_version=value)
                self.assertEqual(world.state, initial)
                self.assertEqual(world.events, [])
                self.assertEqual(world.action_counts, {})
                self.assertFalse(world.fault_used)
                self.assertEqual(world.tool_calls, 1)

    def test_missing_version_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'positive integer'):
            self.world().call('set_status', status='resolved')

    def test_malformed_version_does_not_trigger_concurrent_write(self):
        world = self.world('03-stale-version.yaml')
        initial = copy.deepcopy(world.state)
        with self.assertRaises(ValueError):
            world.call('set_status', status='resolved', expected_version=[])
        self.assertEqual(world.state, initial)
        self.assertFalse(world.fault_used)
        result = world.call('set_status', status='resolved', expected_version=1)
        self.assertEqual(result.result['error'], 'version_conflict')
        self.assertTrue(world.fault_used)
        self.assertEqual(world.action_counts['set_status'], 1)

    def test_malformed_version_preserves_custom_rule_occurrence(self):
        world = World(load_scenario(ROOT / 'examples/custom-faults/repeated-outage.yaml'), 42)
        with self.assertRaises(ValueError):
            world.call('set_status', status='resolved', expected_version=True)
        self.assertFalse(world.fault_used)
        self.assertEqual(world.action_counts, {})
        self.assertFalse(world.call('set_status', status='resolved', expected_version=1).ok)
        self.assertTrue(world.fault_used)
        self.assertEqual(world.action_counts['set_status'], 1)

    def test_real_stale_integer_remains_a_tool_conflict(self):
        world = self.world()
        world.call('append_comment', text='note')
        initial = copy.deepcopy(world.state)
        result = world.call('set_status', status='resolved', expected_version=1)
        self.assertEqual(result.result, {'error': 'version_conflict'})
        self.assertEqual(world.state, initial)
        self.assertTrue(world.call('set_status', status='resolved', expected_version=2).ok)

    def test_adapter_error_keeps_earlier_write_evidence(self):
        class BadVersionAgent:
            name = 'bad version'
            def run(self, call, goal):
                call('append_comment', text=goal['comment'])
                call('set_status', status=goal['status'], expected_version=2.0)
                return True
        result = run(load_scenario(ROOT / 'scenarios/01-lost-ack.yaml'), BadVersionAgent())
        self.assertFalse(result['success'])
        self.assertEqual(result['error']['type'], 'ValueError')
        self.assertEqual(len(result['events']), 1)
        self.assertEqual(result['final_state']['status'], 'open')
        self.assertEqual(result['final_state']['comments'],
                         [load_scenario(ROOT / 'scenarios/01-lost-ack.yaml')['goal']['comment']])
