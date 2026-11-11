import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from agent_retry_rodeo.engine import load_scenario, run, RecoveryAgent
from agent_retry_rodeo.report import render

ROOT = Path(__file__).resolve().parents[1]
class CustomAgentTests(unittest.TestCase):
    def scenario(self): return load_scenario(ROOT / 'scenarios/01-lost-ack.yaml')
    def test_noop_keeps_initial_state_and_custom_identity(self):
        class Noop:
            name = 'My noop'
            def run(self, call, goal): return True
        result = run(self.scenario(), Noop())
        self.assertEqual(result['initial_state'], result['final_state'])
        self.assertEqual(result['events'], [])
        self.assertTrue(result['false_completion'])
        self.assertIn('not verified', result['baseline_type'])
        self.assertIn('initial_state', render([result]))
    def test_bad_completion_outputs_are_errors(self):
        for value in ['done', 1, {}, None, []]:
            class Bad:
                name = 'Bad return'
                def run(self, call, goal): return value
            result = run(self.scenario(), Bad())
            self.assertFalse(result['success'])
            self.assertFalse(result['claimed_complete'])
            self.assertEqual(result['error']['type'], 'ValueError')
    def test_exception_keeps_partial_evidence(self):
        class Crash:
            name = 'Crash'
            def run(self, call, goal):
                call('append_comment', text=goal['comment'])
                raise RuntimeError('adapter failed')
        result=run(self.scenario(), Crash())
        self.assertEqual(len(result['events']),1)
        self.assertEqual(result['error']['type'],'RuntimeError')
        self.assertFalse(result['success'])
    def test_exception_after_goal_is_not_success(self):
        class CrashAfter(RecoveryAgent):
            def run(self,call,goal):
                super().run(call,goal)
                raise RuntimeError('postprocessing failed')
        result=run(self.scenario(),CrashAfter())
        self.assertTrue(all(a['pass'] for a in result['assertions']))
        self.assertFalse(result['success'])
    def test_local_template_cli(self):
        with tempfile.TemporaryDirectory() as d:
            result=subprocess.run([sys.executable,'-m','agent_retry_rodeo.cli','run','--agent','examples/my_agent.py','--output',d],cwd=ROOT,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            runs=json.loads((Path(d)/'results.json').read_text())
            self.assertEqual(len(runs),4)
            self.assertTrue(all(r['success'] for r in runs))
            self.assertTrue(all(r['agent']=='My local recovery agent' for r in runs))
    def test_noop_cli_fails_with_usable_report(self):
        with tempfile.TemporaryDirectory() as d:
            agent=Path(d)/'noop.py';agent.write_text("class Agent:\n name='Noop'\n def run(self,call,goal): return True\ndef create_agent(): return Agent()\n")
            result=subprocess.run([sys.executable,'-m','agent_retry_rodeo.cli','run','--agent',str(agent),'--output',d],cwd=ROOT,capture_output=True,text=True)
            self.assertEqual(result.returncode,1,result.stderr)
            runs=json.loads((Path(d)/'results.json').read_text())
            self.assertTrue(all(r['false_completion'] for r in runs))
            self.assertTrue((Path(d)/'index.html').exists())
    def test_missing_factory_is_clear_error(self):
        with tempfile.TemporaryDirectory() as d:
            agent=Path(d)/'bad.py';agent.write_text('x = 1\n')
            result=subprocess.run([sys.executable,'-m','agent_retry_rodeo.cli','run','--agent',str(agent)],cwd=ROOT,capture_output=True,text=True)
            self.assertEqual(result.returncode,2)
            self.assertIn('create_agent()',result.stderr)
    def test_run_requires_explicit_agent(self):
        result=subprocess.run([sys.executable,'-m','agent_retry_rodeo.cli','run'],cwd=ROOT,capture_output=True,text=True)
        self.assertEqual(result.returncode,2)
        self.assertIn('requires --agent',result.stderr)


class MalformedToolInputTests(unittest.TestCase):
    def scenario(self):
        return load_scenario(ROOT / 'scenarios/01-lost-ack.yaml')

    def test_nonstring_comment_is_reported_without_mutating_state(self):
        for value in [[], {}, None, 1, True]:
            with self.subTest(value=value):
                class BadComment:
                    name = 'Malformed comment'
                    def run(self, call, goal):
                        call('append_comment', text=value)
                        return True
                result = run(self.scenario(), BadComment())
                self.assertFalse(result['success'])
                self.assertFalse(result['claimed_complete'])
                self.assertEqual(result['error']['type'], 'ValueError')
                self.assertIn('text', result['error']['message'])
                self.assertEqual(result['initial_state'], result['final_state'])
                self.assertEqual(result['events'], [])
                json.dumps(result)  # A usable JSON report, even for list/dict input.

    def test_nonstring_status_preserves_prior_valid_evidence(self):
        for value in [[], {}, None, 1, True]:
            with self.subTest(value=value):
                class BadStatus:
                    name = 'Malformed status'
                    def run(self, call, goal):
                        call('append_comment', text=goal['comment'])
                        call('set_status', status=value, expected_version=2)
                        return True
                result = run(self.scenario(), BadStatus())
                self.assertFalse(result['success'])
                self.assertEqual(result['error']['type'], 'ValueError')
                self.assertIn('status', result['error']['message'])
                self.assertEqual(len(result['events']), 1)
                self.assertEqual(result['final_state'], result['events'][0]['after'])
                self.assertEqual(result['final_state']['status'], 'open')
                json.dumps(result)

    def test_rejected_calls_do_not_consume_fault(self):
        from agent_retry_rodeo.engine import World
        for action, params in [('append_comment', {'text': []}),
                               ('set_status', {'status': [], 'expected_version': 1})]:
            with self.subTest(action=action):
                world = World(self.scenario(), 42)
                with self.assertRaises(ValueError):
                    world.call(action, **params)
                self.assertFalse(world.fault_used)
                self.assertEqual(world.events, [])
                ack = world.call('append_comment', text='valid comment')
                self.assertFalse(ack.ok)  # Lost-ack fault is still available.
                self.assertTrue(world.fault_used)

    def test_malformed_adapter_cli_still_exports_failed_run(self):
        with tempfile.TemporaryDirectory() as folder:
            agent = Path(folder) / 'bad.py'
            agent.write_text("class Agent:\n name='Malformed comment'\n def run(self,call,goal): call('append_comment',text=[]); return True\ndef create_agent(): return Agent()\n")
            result = subprocess.run([sys.executable, '-m', 'agent_retry_rodeo.cli',
                                     'run', '--agent', str(agent), '--output', folder],
                                    cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertNotIn('Traceback', result.stderr)
            runs = json.loads((Path(folder) / 'results.json').read_text())
            self.assertEqual(len(runs), 4)
            self.assertTrue(all(r['error']['type'] == 'ValueError' for r in runs))
            self.assertTrue((Path(folder) / 'index.html').exists())
