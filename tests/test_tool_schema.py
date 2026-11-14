import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from agent_retry_rodeo.engine import World, load_scenario, run

ROOT = Path(__file__).resolve().parents[1]


class ToolSchemaTests(unittest.TestCase):
    def scenario(self, name='01-lost-ack.yaml'):
        return load_scenario(ROOT / 'scenarios' / name)

    def test_unknown_parameters_rejected_before_state_fault_or_occurrence(self):
        calls = [('read_ticket', {'extra': 'ignored'}),
                 ('append_comment', {'text': 'hello', 'idempotency_key': 'not-supported'}),
                 ('set_status', {'status': 'closed', 'expected_version': 1, 'force': True})]
        for action, params in calls:
            with self.subTest(action=action):
                world = World(self.scenario(), 42)
                before = copy.deepcopy(world.state)
                with self.assertRaisesRegex(ValueError, 'parameters'):
                    world.call(action, **params)
                self.assertEqual(world.state, before)
                self.assertEqual(world.events, [])
                self.assertEqual(world.action_counts, {})
                self.assertFalse(world.fault_used)
                self.assertEqual(world.tool_calls, 1)
                self.assertFalse(world.call('append_comment', text='valid').ok)

    def test_missing_parameters_rejected_before_occurrence(self):
        for action, params in [('append_comment', {}), ('set_status', {}),
                               ('set_status', {'status': 'closed'}),
                               ('set_status', {'expected_version': 1})]:
            with self.subTest(action=action, params=params):
                world = World(self.scenario(), 42)
                with self.assertRaises(ValueError):
                    world.call(action, **params)
                self.assertEqual(world.action_counts, {})
                self.assertEqual(world.events, [])

    def test_unsupported_action_never_changes_occurrence_or_fault(self):
        for action in ['erase_ticket', '', [], {}, None, True, 1]:
            with self.subTest(action=action):
                world = World(self.scenario(), 42)
                with self.assertRaisesRegex(ValueError, 'Unknown action'):
                    world.call(action)
                self.assertEqual(world.action_counts, {})
                self.assertEqual(world.events, [])
                self.assertFalse(world.fault_used)

    def test_nonserializable_unused_arguments_leave_usable_failed_report(self):
        for value in [object(), {1, 2}, float('nan')]:
            with self.subTest(value=type(value).__name__):
                class Bad:
                    name = 'Unsupported argument'
                    def run(self, call, goal):
                        call('read_ticket', extra=value)
                        return True
                result = run(self.scenario(), Bad())
                self.assertFalse(result['success'])
                self.assertEqual(result['error']['type'], 'ValueError')
                self.assertEqual(result['events'], [])
                json.dumps(result, allow_nan=False)

    def test_unknown_parameter_does_not_consume_custom_fault(self):
        scenario = self.scenario()
        scenario['fault'] = 'none'
        scenario['fault_plan'] = [{'action': 'read_ticket', 'occurrence': 1,
                                   'timing': 'before', 'error': 'service_unavailable'}]
        world = World(scenario, 42)
        with self.assertRaises(ValueError):
            world.call('read_ticket', extra=True)
        self.assertFalse(world.call('read_ticket').ok)
        self.assertEqual(world.action_counts, {'read_ticket': 1})

    @unittest.skipUnless(os.name == 'posix', 'POSIX subprocess transport')
    def test_external_protocol_reports_unsupported_parameter_without_write(self):
        from agent_retry_rodeo.process_agent import ProcessAgent
        code = 'print(\'{"type":"call","action":"append_comment","params":{"text":"hello","idempotency_key":"key"}}\')'
        result = run(self.scenario(), ProcessAgent([sys.executable, '-c', code]))
        self.assertFalse(result['success'])
        self.assertEqual(result['error']['type'], 'ValueError')
        self.assertEqual(result['initial_state'], result['final_state'])
        self.assertEqual(result['events'], [])

    def test_cli_still_exports_report_after_nonserializable_extra_argument(self):
        with tempfile.TemporaryDirectory() as folder:
            agent = Path(folder) / 'bad.py'
            agent.write_text("class Agent:\n name='Unsupported argument'\n def run(self,call,goal): call('read_ticket',extra=object()); return True\ndef create_agent(): return Agent()\n")
            result = subprocess.run([sys.executable, '-m', 'agent_retry_rodeo.cli', 'run',
                                     '--agent', str(agent), '--output', folder], cwd=ROOT,
                                    text=True, capture_output=True)
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertNotIn('Traceback', result.stderr)
            runs = json.loads((Path(folder) / 'results.json').read_text())
            self.assertEqual(len(runs), 4)
            self.assertTrue(all(r['error']['type'] == 'ValueError' for r in runs))
            self.assertTrue((Path(folder) / 'index.html').exists())
