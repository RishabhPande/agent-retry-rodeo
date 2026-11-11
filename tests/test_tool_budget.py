"""Tool-call limits bound simulator work, not arbitrary trusted adapter code."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from agent_retry_rodeo.engine import (RecoveryAgent, ToolCallLimitError, World,
                                     load_scenario, run)

ROOT = Path(__file__).resolve().parents[1]


class ToolBudgetTests(unittest.TestCase):
    def setUp(self):
        self.scenario = load_scenario(ROOT / 'scenarios/01-lost-ack.yaml')

    def test_limit_checked_before_write_or_fault(self):
        world = World(self.scenario, 42, max_tool_calls=1)
        world.call('read_ticket')
        with self.assertRaises(ToolCallLimitError):
            world.call('append_comment', text='must not be written')
        self.assertEqual(world.state, self.scenario['initial'])
        self.assertFalse(world.fault_used)
        self.assertEqual(len(world.events), 1)
        self.assertEqual(world.tool_calls, 1)

    def test_budget_exhaustion_keeps_partial_evidence(self):
        class RetryForever:
            name = 'Retry forever'
            def run(self, call, goal):
                while True:
                    call('read_ticket')
        result = run(self.scenario, RetryForever(), max_tool_calls=3)
        self.assertFalse(result['success'])
        self.assertEqual(result['error']['type'], 'ToolCallLimitError')
        self.assertEqual(len(result['events']), 3)
        self.assertEqual(result['tool_calls'], 3)
        self.assertEqual(result['max_tool_calls'], 3)
        json.dumps(result)

    def test_catching_limit_cannot_hide_failed_run(self):
        class CatchLimit(RecoveryAgent):
            def run(self, call, goal):
                super().run(call, goal)
                try:
                    for _ in range(10):
                        call('read_ticket')
                except ToolCallLimitError:
                    return True
        result = run(self.scenario, CatchLimit(), max_tool_calls=8)
        self.assertTrue(all(a['pass'] for a in result['assertions']))
        self.assertFalse(result['success'])
        self.assertFalse(result['claimed_complete'])
        self.assertEqual(result['error']['type'], 'ToolCallLimitError')

    def test_exact_budget_does_not_fail_completed_adapter(self):
        normal = run(self.scenario, RecoveryAgent())
        exact = run(self.scenario, RecoveryAgent(), max_tool_calls=normal['tool_calls'])
        self.assertTrue(exact['success'])
        self.assertEqual(exact['events'], normal['events'])
        self.assertIsNone(exact['error'])

    def test_invalid_api_limits_rejected(self):
        for value in [True, False, 0, -1, 1.0, '3', None]:
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'positive integer'):
                run(self.scenario, RecoveryAgent(), max_tool_calls=value)

    def test_invalid_calls_also_consume_budget(self):
        world = World(self.scenario, 42, max_tool_calls=1)
        with self.assertRaises(ValueError):
            world.call('unknown')
        with self.assertRaises(ToolCallLimitError):
            world.call('read_ticket')
        self.assertEqual(world.events, [])

    def invoke(self, *args):
        return subprocess.run([sys.executable, '-m', 'agent_retry_rodeo.cli', *map(str, args)],
                              cwd=ROOT, capture_output=True, text=True, timeout=15)

    def test_cli_limit_exports_replay_and_failed_runs(self):
        with tempfile.TemporaryDirectory() as folder:
            result = self.invoke('run', '--agent', 'examples/my_agent.py',
                                 '--max-tool-calls', 1, '--output', folder)
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertNotIn('Traceback', result.stderr)
            runs = json.loads((Path(folder) / 'results.json').read_text())
            self.assertEqual(len(runs), 4)
            self.assertTrue(all(r['error']['type'] == 'ToolCallLimitError' for r in runs))
            self.assertTrue(all(r['tool_calls'] == 1 for r in runs))
            self.assertTrue((Path(folder) / 'index.html').exists())

    def test_cli_rejects_invalid_limits_and_other_commands(self):
        for args in [('run', '--max-tool-calls', '0'), ('run', '--max-tool-calls', '-1'),
                     ('demo', '--max-tool-calls', '3'), ('validate', '--max-tool-calls', '3'),
                     ('compare', '--max-tool-calls', '3')]:
            with self.subTest(args=args):
                result = self.invoke(*args)
                self.assertEqual(result.returncode, 2)
                self.assertIn('positive integer', result.stderr)
