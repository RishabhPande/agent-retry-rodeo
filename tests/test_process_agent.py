import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

from agent_retry_rodeo.engine import load_scenario, run
from agent_retry_rodeo.process_agent import ProcessAgent

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == 'posix', 'POSIX subprocess transport')
class ProcessTests(unittest.TestCase):
    def scenario(self):
        return load_scenario(ROOT / 'scenarios/01-lost-ack.yaml')

    def execute(self, code, timeout=2):
        return run(self.scenario(), ProcessAgent([sys.executable, '-u', '-c', code], timeout))

    def test_protocol_example_passes_original_and_custom_cases(self):
        for path in list((ROOT / 'scenarios').glob('*.yaml')) + list((ROOT / 'examples/custom-faults').glob('*.yaml')):
            with self.subTest(path=path):
                result = run(load_scenario(path), ProcessAgent([sys.executable, str(ROOT / 'examples/process_agent.py')]))
                self.assertTrue(result['success'], result['error'])
                self.assertIn('not verified', result['baseline_type'])

    def test_fresh_process_each_case(self):
        adapter = ProcessAgent([sys.executable, str(ROOT / 'examples/process_agent.py')])
        self.assertEqual(run(self.scenario(), adapter), run(self.scenario(), adapter))

    def test_false_completion_is_graded_against_parent_state(self):
        result = self.execute('print(\'{"type":"done","claimed_complete":true}\')')
        self.assertTrue(result['false_completion'])
        self.assertEqual(result['initial_state'], result['final_state'])

    def test_false_claim_stays_false(self):
        result = self.execute('print(\'{"type":"done","claimed_complete":false}\')')
        self.assertFalse(result['false_completion'])
        self.assertIsNone(result['error'])

    def test_malformed_protocol_fails_closed(self):
        frames = ['not json', '[]', '{"type":"done","claimed_complete":"true"}',
                  '{"type":"done","claimed_complete":true,"state":{}}',
                  '{"type":"call","action":"read_ticket","params":[]}',
                  '{"type":"call","action":"read_ticket","params":{},"extra":1}',
                  '{"type":"nope"}', '{"type":"done","type":"done","claimed_complete":true}',
                  '{"type":"call","action":"read_ticket","params":{"x":NaN}}',
                  '{"type":"call","action":"read_ticket","params":{"x":1e9999}}']
        for frame in frames:
            with self.subTest(frame=frame):
                result = self.execute('print(' + repr(frame) + ')')
                self.assertFalse(result['success'])
                self.assertIsNotNone(result['error'])

    def test_unknown_tool_is_error(self):
        result = self.execute('print(\'{"type":"call","action":"wipe_state","params":{}}\')')
        self.assertFalse(result['success'])
        self.assertIn('Unknown action', result['error']['message'])

    def test_partial_evidence_survives_crash(self):
        result = self.execute('import json,sys;sys.stdin.readline();print(json.dumps({"type":"call","action":"append_comment","params":{"text":"Investigated and resolved"}}),flush=True);sys.stdin.readline();sys.exit(7)')
        self.assertEqual(len(result['events']), 1)
        self.assertIn('status 7', result['error']['message'])

    def test_timeout_after_partial_write(self):
        result = self.execute('import json,sys,time;sys.stdin.readline();print(json.dumps({"type":"call","action":"append_comment","params":{"text":"written"}}),flush=True);sys.stdin.readline();time.sleep(10)', .15)
        self.assertEqual(len(result['events']), 1)
        self.assertEqual(result['error']['type'], 'TimeoutError')
        self.assertIn('written', result['final_state']['comments'])

    def test_done_then_hang_is_not_success(self):
        result = self.execute('import time;print(\'{"type":"done","claimed_complete":true}\',flush=True);time.sleep(10)', .15)
        self.assertEqual(result['error']['type'], 'TimeoutError')

    def test_timeout_when_child_never_reads_start(self):
        start = time.monotonic()
        result = self.execute('import time;time.sleep(10)', .15)
        self.assertLess(time.monotonic() - start, 2)
        self.assertEqual(result['error']['type'], 'TimeoutError')

    def test_unterminated_frame(self):
        result = self.execute('import sys;sys.stdout.write(\'{"type":"done","claimed_complete":true}\')')
        self.assertIn('unterminated', result['error']['message'])

    def test_no_completion_and_nonzero_exit(self):
        for code in ('pass', 'import sys;sys.exit(4)'):
            self.assertIsNotNone(self.execute(code)['error'])

    def test_data_after_done_rejected(self):
        result = self.execute('print(\'{"type":"done","claimed_complete":true}\\n{"type":"done","claimed_complete":true}\')')
        self.assertIn('after completion', result['error']['message'])

    def test_oversize_frame_with_and_without_newline(self):
        for newline in ('', '\n'):
            result = self.execute('import sys;sys.stdout.write("x"*64001+' + repr(newline) + ')')
            self.assertIn('64 KB', result['error']['message'])

    def test_stderr_drained_but_not_disclosed(self):
        result = self.execute('import sys;sys.stderr.write("SECRET-NOT-EVIDENCE"*10000);print(\'{"type":"done","claimed_complete":false}\')')
        self.assertIsNone(result['error'])
        self.assertNotIn('SECRET-NOT-EVIDENCE', json.dumps(result))

    def test_output_budget_includes_stderr(self):
        result = self.execute('import sys;sys.stderr.write("x"*4000001)')
        self.assertIn('output budget', result['error']['message'])

    def test_tool_budget_cannot_be_caught_by_external_agent(self):
        result = run(self.scenario(), ProcessAgent([sys.executable, str(ROOT / 'examples/process_agent.py')]), max_tool_calls=1)
        self.assertEqual(result['error']['type'], 'ToolCallLimitError')
        self.assertEqual(result['tool_calls'], 1)

    def test_constructor_validation(self):
        for command in ([], [''], [1]):
            with self.assertRaises(ValueError):
                ProcessAgent(command)
        for timeout in (0, -1, float('inf'), float('nan')):
            with self.assertRaises(ValueError):
                ProcessAgent(['python'], timeout)

    def test_cli_exports_failed_timeout_and_enforces_options(self):
        with tempfile.TemporaryDirectory() as folder:
            result = subprocess.run([sys.executable, '-m', 'agent_retry_rodeo.cli', 'run', '--output', folder,
                                     '--agent-timeout', '.15', '--agent-command', sys.executable, '-c', 'import time;time.sleep(10)'],
                                    cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(result.returncode, 1, result.stderr)
            reports = json.loads((Path(folder) / 'results.json').read_text())
            self.assertTrue(all(r['error']['type'] == 'TimeoutError' for r in reports))
            self.assertTrue((Path(folder) / 'index.html').exists())
        for args in (['demo', '--agent-command', 'python'], ['run', '--agent-command'],
                     ['run', '--agent', 'x.py', '--agent-command', 'python'],
                     ['run', '--agent-timeout', 'nan', '--agent-command', 'python'],
                     ['demo', '--agent-timeout', '1']):
            with self.subTest(args=args):
                result = subprocess.run([sys.executable, '-m', 'agent_retry_rodeo.cli', *args], cwd=ROOT, capture_output=True, text=True)
                self.assertEqual(result.returncode, 2)
