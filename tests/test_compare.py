import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from agent_retry_rodeo.compare import compare, load_runs
from agent_retry_rodeo.engine import load_scenario, run, RecoveryAgent, NaiveAgent

ROOT = Path(__file__).resolve().parents[1]

class ComparisonTests(unittest.TestCase):
    def setUp(self):
        self.scenario = load_scenario(ROOT / 'scenarios/01-lost-ack.yaml')
        self.good = run(self.scenario, RecoveryAgent())
        self.bad = run(self.scenario, NaiveAgent())

    def test_identical_and_improving_runs_pass(self):
        self.assertFalse(compare([self.good], [self.good])['regressed'])
        self.assertFalse(compare([self.bad], [self.good])['regressed'])

    def test_regression_is_specific(self):
        result = compare([self.good], [self.bad])
        self.assertTrue(result['regressed'])
        self.assertEqual(result['cases'][0]['regressions'],
                         ['lost_success', 'new_false_completion', 'increased_duplicate_comments'])

    def test_new_error_and_unfinished_work_are_detected(self):
        candidate = copy.deepcopy(self.good)
        candidate.update(success=False, false_completion=False,
                         error={'type': 'RuntimeError'}, uncompleted_steps=2)
        self.assertEqual(compare([self.good], [candidate])['cases'][0]['regressions'],
                         ['lost_success', 'new_adapter_error', 'increased_uncompleted_steps'])

    def test_changed_goal_or_fixture_rejected_even_same_id_and_version(self):
        for field in ('goal', 'initial'):
            scenario = copy.deepcopy(self.scenario)
            scenario[field]['status'] = 'different'
            other = run(scenario, RecoveryAgent())
            with self.assertRaisesRegex(ValueError, 'content changed'):
                compare([self.good], [other])

    def test_key_order_does_not_change_fingerprint(self):
        reordered = dict(reversed(list(self.scenario.items())))
        self.assertEqual(run(reordered, RecoveryAgent())['scenario_sha256'], self.good['scenario_sha256'])

    def test_seed_and_case_sets_must_match(self):
        for candidate in ([run(self.scenario, RecoveryAgent(), 5)], []):
            with self.assertRaises(ValueError):
                compare([self.good], candidate)

    def test_multi_adapter_demo_and_duplicate_keys_rejected(self):
        with self.assertRaisesRegex(ValueError, 'one adapter'):
            compare([self.good, self.bad], [self.good])

    def test_old_reports_and_malformed_metrics_fail_closed(self):
        for field, value in [('scenario_sha256', None), ('success', 1),
                             ('duplicate_comments', True), ('uncompleted_steps', -1),
                             ('seed', True), ('error', 'oops'), ('schema_version', True)]:
            bad = copy.deepcopy(self.good)
            bad[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                compare([bad], [self.good])

    def test_order_is_stable_and_adapter_rename_is_allowed(self):
        other = run(self.scenario, RecoveryAgent(), 7)
        renamed = copy.deepcopy(self.good)
        renamed['agent'] = 'Renamed adapter'
        report = compare([self.good, other], [other, renamed])
        self.assertEqual([r['seed'] for r in report['cases']], [7, 42])
        self.assertFalse(report['regressed'])

    def test_cli_exit_codes_json_and_no_output_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder) / 'baseline.json'
            cand = Path(folder) / 'candidate.json'
            out = Path(folder) / 'should-not-exist'
            base.write_text(json.dumps([self.good]))
            for data, expected in [([self.good], 0), ([self.bad], 1), ({}, 2)]:
                cand.write_text(json.dumps(data))
                proc = subprocess.run([sys.executable, '-m', 'agent_retry_rodeo.cli', 'compare',
                                       '--baseline', str(base), '--candidate', str(cand), '--output', str(out)],
                                      cwd=ROOT, capture_output=True, text=True)
                self.assertEqual(proc.returncode, expected, proc.stderr)
                self.assertNotIn('Traceback', proc.stderr)
                self.assertFalse(out.exists())
                if expected < 2:
                    self.assertEqual(json.loads(proc.stdout)['regressed'], bool(expected))

    def test_compare_does_not_need_scenario_folder_or_adapter_execution(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'runs.json'
            path.write_text(json.dumps([self.good]))
            proc = subprocess.run([sys.executable, '-m', 'agent_retry_rodeo.cli', 'compare',
                                   '--baseline', str(path), '--candidate', str(path),
                                   '--scenarios', str(Path(folder) / 'missing')],
                                  cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)


class ReportJSONTests(unittest.TestCase):
    def test_duplicate_keys_rejected_even_when_last_value_would_pass(self):
        good = run(load_scenario(ROOT / 'scenarios/01-lost-ack.yaml'), RecoveryAgent())
        clean = json.dumps([good])
        ambiguous = clean.replace('"success": true', '"success": false, "success": true')
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'report.json'
            for data in (ambiguous, clean.replace('"error": null',
                         '"error": {"type": "First", "type": "Second"}')):
                path.write_text(data, encoding='utf-8')
                with self.subTest(data=data), self.assertRaisesRegex(ValueError, 'Duplicate JSON key'):
                    load_runs(path)
            path.write_text(clean, encoding='utf-8')
            self.assertEqual(load_runs(path), [good])

    def test_nonstandard_numbers_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'report.json'
            for value in ('NaN', 'Infinity', '-Infinity'):
                path.write_text('[{"extra": ' + value + '}]', encoding='utf-8')
                with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'Non-standard JSON number'):
                    load_runs(path)

    def test_numeric_overflow_rejected_and_finite_numbers_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'report.json'
            for number in ('1e999', '-1e999', '9.9e9999'):
                path.write_text('[{"extra": {"number": ' + number + '}}]', encoding='utf-8')
                with self.subTest(number=number), self.assertRaisesRegex(ValueError, 'finite float range'):
                    load_runs(path)
            path.write_text('[{"extra": [1.5, -2.25, 1e100, 0.0]}]', encoding='utf-8')
            self.assertEqual(load_runs(path), [{"extra": [1.5, -2.25, 1e100, 0.0]}])

    def test_cli_rejects_ambiguous_either_side_without_traceback_or_output(self):
        good = run(load_scenario(ROOT / 'scenarios/01-lost-ack.yaml'), RecoveryAgent())
        with tempfile.TemporaryDirectory() as folder:
            baseline = Path(folder) / 'baseline.json'
            candidate = Path(folder) / 'candidate.json'
            clean = json.dumps([good])
            for side in (baseline, candidate):
                for malformed in (clean.replace('"success": true',
                                  '"success": false, "success": true'), '[NaN]', '[1e999]', '[-1e999]', '{', None):
                    baseline.write_text(clean, encoding='utf-8')
                    candidate.write_text(clean, encoding='utf-8')
                    if malformed is None:
                        side.write_bytes(b'\xff')
                    else:
                        side.write_text(malformed, encoding='utf-8')
                    proc = subprocess.run([sys.executable, '-m', 'agent_retry_rodeo.cli', 'compare',
                                           '--baseline', str(baseline), '--candidate', str(candidate)],
                                          cwd=ROOT, capture_output=True, text=True)
                    with self.subTest(side=side.name, malformed=malformed):
                        self.assertEqual(proc.returncode, 2)
                        self.assertEqual(proc.stdout, '')
                        self.assertIn('Cannot compare reports:', proc.stderr)
                        self.assertNotIn('Traceback', proc.stderr)
