import copy
from pathlib import Path
import tempfile
import unittest
import yaml
from agent_retry_rodeo.engine import load_scenario, World, run, RecoveryAgent

ROOT = Path(__file__).resolve().parents[1]


class FaultPlanTests(unittest.TestCase):
    def fixture(self):
        return load_scenario(ROOT / 'examples/custom-faults/repeated-outage.yaml')

    def load(self, data):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'case.yaml'
            path.write_text(yaml.safe_dump(data))
            return load_scenario(path)

    def test_before_failure_does_not_commit_and_after_failure_does(self):
        world = World(self.fixture(), 42)
        initial = copy.deepcopy(world.state)
        result = world.call('set_status', status='resolved', expected_version=1)
        self.assertFalse(result.ok)
        self.assertEqual(world.state, initial)
        result = world.call('append_comment', text='x')
        self.assertFalse(result.ok)
        self.assertEqual(result.result['committed'], 'unknown')
        self.assertIn('x', world.state['comments'])
        self.assertEqual(world.state['version'], 2)
        self.assertIn('Custom after fault', world.events[-1]['fault'])

    def test_repeat_rules_fire_at_exact_occurrences(self):
        world = World(self.fixture(), 42)
        for _ in range(2):
            self.assertFalse(world.call('set_status', status='resolved', expected_version=1).ok)
        self.assertTrue(world.call('set_status', status='resolved', expected_version=1).ok)
        self.assertEqual(world.state['status'], 'resolved')

    def test_no_fault_rule_fires_for_other_action(self):
        world = World(self.fixture(), 42)
        self.assertTrue(world.call('read_ticket').ok)
        self.assertFalse(world.fault_used)

    def test_read_failures_can_be_scheduled(self):
        data = self.fixture()
        data['fault_plan'] = [dict(action='read_ticket', occurrence=1, timing='before', error='unavailable')]
        world = World(self.load(data), 42)
        self.assertFalse(world.call('read_ticket').ok)
        self.assertTrue(world.call('read_ticket').ok)

    def test_invalid_tool_input_does_not_consume_rule_occurrence(self):
        world = World(self.fixture(), 42)
        with self.assertRaises(ValueError):
            world.call('append_comment', text=[])
        self.assertFalse(world.call('append_comment', text='valid').ok)

    def test_rule_changes_invalidate_comparison_fingerprint(self):
        data = self.fixture()
        before = run(data, RecoveryAgent())
        data['fault_plan'][0]['error'] = 'different_error'
        after = run(data, RecoveryAgent())
        self.assertNotEqual(before['scenario_sha256'], after['scenario_sha256'])

    def test_invalid_rules_rejected(self):
        changes = [{'action': 'delete_everything'}, {'action': []}, {'occurrence': True},
                   {'occurrence': 0}, {'occurrence': 10001}, {'timing': 'during'},
                   {'error': ''}, {'error': '  '}, {'error': 'x' * 201}, {'extra': 1}]
        for change in changes:
            with self.subTest(change=change):
                data = self.fixture()
                data['fault_plan'][0].update(change)
                with self.assertRaises(ValueError):
                    self.load(data)

    def test_empty_duplicate_missing_and_oversize_plans_rejected(self):
        base = self.fixture()
        rule = base['fault_plan'][0]
        for plan in ([], {}, [rule, rule], [rule] * 65):
            data = self.fixture()
            data['fault_plan'] = plan
            with self.assertRaises(ValueError):
                self.load(data)
        data = self.fixture()
        del data['fault_plan']
        with self.assertRaises(ValueError):
            self.load(data)

    def test_old_schema_and_builtin_fault_cannot_smuggle_plan(self):
        for version, fault in ((1, 'custom'), (2, 'lost_ack'), (1, 'lost_ack'), (3, 'custom')):
            data = self.fixture()
            data.update(schema_version=version, fault=fault)
            with self.assertRaises(ValueError):
                self.load(data)

    def test_plan_recorded_in_evidence_and_reproducible(self):
        # Full custom schedule is needed to interpret/reproduce exported evidence.
        result = run(self.fixture(), RecoveryAgent())
        self.assertEqual(result, run(self.fixture(), RecoveryAgent()))
        self.assertEqual(result['fault_plan'], self.fixture()['fault_plan'])
