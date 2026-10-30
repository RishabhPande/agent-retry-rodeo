"""Regression tests for contributor inputs, state evidence and CLI artifacts."""
import copy
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from agent_retry_rodeo.engine import load_scenario, run, World, RecoveryAgent
from agent_retry_rodeo.report import render

ROOT = Path(__file__).resolve().parents[1]

class ScenarioContracts(unittest.TestCase):
    def setUp(self):
        self.scenario = load_scenario(ROOT / 'scenarios/01-lost-ack.yaml')

    def reject(self, data):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'case.yaml'
            path.write_text(json.dumps(data), encoding='utf-8')
            with self.assertRaises(ValueError):
                load_scenario(path)

    def test_schema_version_is_integer_not_boolean_or_float(self):
        for value in [True, 1.0, '1', 2, None]:
            with self.subTest(value=value):
                data = copy.deepcopy(self.scenario)
                data['schema_version'] = value
                self.reject(data)

    def test_expected_count_is_integer_not_boolean_or_float(self):
        for value in [True, 1.0, '1', 0, 2]:
            with self.subTest(value=value):
                data = copy.deepcopy(self.scenario)
                data['expected']['goal_comment_count'] = value
                self.reject(data)

    def test_preservation_must_be_boolean_true(self):
        for value in [1, 'true', False, None]:
            with self.subTest(value=value):
                data = copy.deepcopy(self.scenario)
                data['expected']['preserve_existing_comments'] = value
                self.reject(data)

    def test_unknown_fault_shapes_raise_validation_error(self):
        for value in [[], {}, None, 'unknown']:
            with self.subTest(value=value):
                data = copy.deepcopy(self.scenario)
                data['fault'] = value
                self.reject(data)

    def test_top_level_and_nested_contracts(self):
        for field, value in [('initial', []), ('goal', None), ('expected', []), ('title', ' '), ('id', '')]:
            with self.subTest(field=field):
                data = copy.deepcopy(self.scenario)
                data[field] = value
                self.reject(data)
        for field in ['initial', 'goal', 'expected']:
            data = copy.deepcopy(self.scenario)
            data[field]['extra'] = 'unsupported'
            self.reject(data)

    def test_goal_whitespace_and_existing_comment_rejected(self):
        for key, value in [('comment', '  '), ('status', '\t'), ('comment', 'existing')]:
            data = copy.deepcopy(self.scenario)
            data['initial']['comments'] = ['existing']
            data['goal'][key] = value
            self.reject(data)

    def test_initial_version_and_comments_types(self):
        for key, value in [('version', True), ('version', 0), ('version', 1.0), ('comments', [1]), ('comments', 'text')]:
            data = copy.deepcopy(self.scenario)
            data['initial'][key] = value
            self.reject(data)

    def test_duplicate_yaml_keys_rejected_at_all_levels(self):
        import yaml
        base = yaml.safe_dump(self.scenario)
        samples = [base + 'title: overwritten\n', base.replace('goal:\n', 'goal:\n  status: overwritten\n')]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'duplicate.yaml'
            for text in samples:
                path.write_text(text)
                with self.assertRaisesRegex(ValueError, 'Duplicate scenario key'):
                    load_scenario(path)

    def test_oversized_scenario_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'large.yaml'
            path.write_text('x' * 64001)
            with self.assertRaisesRegex(ValueError, '64 KB'):
                load_scenario(path)

    def test_empty_and_nonmapping_documents_rejected(self):
        for data in [None, [], 'text', 1]:
            self.reject(data)

class EvidenceContracts(unittest.TestCase):
    def scenario(self):
        return load_scenario(ROOT / 'scenarios/01-lost-ack.yaml')

    def test_agent_claim_cannot_replace_persisted_state(self):
        class ConfidentNoop:
            name = 'Confident noop'
            def run(self, call, goal):
                return True
        result = run(self.scenario(), ConfidentNoop())
        self.assertTrue(result['claimed_complete'])
        self.assertFalse(result['success'])
        self.assertTrue(result['false_completion'])
        self.assertEqual(result['events'], [])
        self.assertEqual(result['uncompleted_steps'], 2)

    def test_honest_incompletion_not_false_completion(self):
        class HonestNoop:
            name = 'Honest noop'
            def run(self, call, goal):
                return False
        result = run(self.scenario(), HonestNoop())
        self.assertFalse(result['success'])
        self.assertFalse(result['false_completion'])

    def test_duplicate_existing_comments_preserved_with_multiplicity(self):
        scenario = self.scenario()
        scenario['initial']['comments'] = ['keep', 'keep']
        result = run(scenario, RecoveryAgent())
        proof = next(a for a in result['assertions'] if a['id'] == 'preserve_comments')
        self.assertEqual(proof['expected'], {'keep': 2})
        self.assertTrue(proof['pass'])

    def test_tool_observations_and_history_are_snapshots(self):
        world = World(self.scenario(), 42)
        observation = world.call('read_ticket')
        observation.result['comments'].append('not persisted')
        self.assertNotIn('not persisted', world.state['comments'])
        world.call('append_comment', text='later')
        self.assertEqual(world.events[0]['after']['comments'], [])
        self.assertEqual(world.events[1]['before']['comments'], [])

    def test_recovery_retry_budget_is_finite(self):
        calls = []
        from agent_retry_rodeo.engine import Observation
        def unavailable(action, **params):
            calls.append(action)
            return Observation(False, {'status': 'open', 'version': 1, 'comments': []})
        self.assertFalse(RecoveryAgent().run(unavailable, {'status': 'closed', 'comment': 'target'}))
        self.assertEqual(len(calls), 12)

    def test_report_embedded_evidence_roundtrips(self):
        result = run(self.scenario(), RecoveryAgent())
        result['title'] = '</script><script>alert("x")</script> & <tag>'
        page = render([result])
        payload = re.search(r'<script type="application/json" id="data">(.*?)</script>', page, re.S).group(1)
        self.assertEqual(json.loads(payload), [result])
        self.assertNotIn('</script>', payload)

class CliContracts(unittest.TestCase):
    def invoke(self, *args):
        return subprocess.run([sys.executable, '-m', 'agent_retry_rodeo.cli', *map(str, args)], cwd=ROOT, capture_output=True, text=True)

    def test_demo_exports_six_runs_and_replay(self):
        with tempfile.TemporaryDirectory() as folder:
            result = self.invoke('demo', '--output', folder)
            self.assertEqual(result.returncode, 0, result.stderr)
            runs = json.loads((Path(folder) / 'results.json').read_text())
            self.assertEqual(len(runs), 6)
            self.assertEqual(sum(r['success'] for r in runs), 3)
            self.assertIn('scripted baselines', result.stdout)
            self.assertIn('<!doctype html>', (Path(folder) / 'index.html').read_text())

    def test_validate_does_not_create_output(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'not-created'
            result = self.invoke('validate', '--output', output)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(output.exists())

    def test_empty_pack_is_clear_error(self):
        with tempfile.TemporaryDirectory() as folder:
            result = self.invoke('validate', '--scenarios', folder)
            self.assertEqual(result.returncode, 2)
            self.assertIn('No .yaml scenarios', result.stderr)

    def test_duplicate_ids_are_clear_error(self):
        with tempfile.TemporaryDirectory() as folder:
            source = (ROOT / 'scenarios/01-lost-ack.yaml').read_text()
            for name in ['a.yaml', 'b.yaml']:
                (Path(folder) / name).write_text(source)
            result = self.invoke('validate', '--scenarios', folder)
            self.assertEqual(result.returncode, 2)
            self.assertIn('Scenario ids must be unique', result.stderr)

    def test_malformed_yaml_has_actionable_error_not_traceback(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / 'bad.yaml').write_text('fault: [')
            result = self.invoke('validate', '--scenarios', folder)
            self.assertEqual(result.returncode, 2)
            self.assertIn('Invalid scenario', result.stderr)
            self.assertNotIn('Traceback', result.stderr)

if __name__ == '__main__':
    unittest.main()
