import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from xml.etree import ElementTree as ET

from agent_retry_rodeo.compare import compare
from agent_retry_rodeo.engine import load_scenario, run, RecoveryAgent, NaiveAgent
from agent_retry_rodeo.junit import render_junit

ROOT = Path(__file__).resolve().parents[1]


class JUnitTests(unittest.TestCase):
    def setUp(self):
        scenario = load_scenario(ROOT / "scenarios/01-lost-ack.yaml")
        self.good = run(scenario, RecoveryAgent())
        self.bad = run(scenario, NaiveAgent())

    def cli(self, baseline, candidate, output, *extra):
        return subprocess.run([sys.executable, "-m", "agent_retry_rodeo.cli", "compare",
                               "--baseline", str(baseline), "--candidate", str(candidate),
                               "--junit-xml", str(output), *extra], cwd=ROOT,
                              capture_output=True, text=True)

    def test_regression_counts_and_specific_reasons(self):
        root = ET.fromstring(render_junit(compare([self.good], [self.bad])))
        self.assertEqual(root.attrib["tests"], "1")
        self.assertEqual(root.attrib["failures"], "1")
        failure = root.find("testcase/failure")
        self.assertEqual(failure.attrib["type"], "DirectionalRegression")
        self.assertIn("new_false_completion", failure.text)
        self.assertIn("increased_duplicate_comments", failure.text)

    def test_unchanged_failure_is_not_claimed_adapter_success(self):
        root = ET.fromstring(render_junit(compare([self.bad], [self.bad])))
        self.assertEqual(root.attrib["failures"], "0")
        self.assertIsNone(root.find("testcase/failure"))
        prop = root.find("properties/property[@name='passing_case_meaning']")
        self.assertIn("Unchanged failures", prop.attrib["value"])

    def test_stable_cases_and_no_adapter_error_or_trace_contents(self):
        candidate = copy.deepcopy(self.bad)
        candidate["error"] = {"message": "DO_NOT_EXPORT_SECRET"}
        candidate["trace"] = [{"text": "PRIVATE_TRACE"}]
        other = copy.deepcopy(self.good)
        other["seed"] = 7
        xml = render_junit(compare([self.good, other], [candidate, other]))
        root = ET.fromstring(xml)
        self.assertEqual(root.attrib["tests"], "2")
        self.assertIn("seed=7", root.findall("testcase")[0].attrib["name"])
        self.assertNotIn("DO_NOT_EXPORT_SECRET", xml)
        self.assertNotIn("PRIVATE_TRACE", xml)
        self.assertIn("new_adapter_error", xml)

    def test_xml_escapes_identifiers_and_replaces_invalid_characters(self):
        good = copy.deepcopy(self.good)
        good["scenario_id"] = 'case<&"\x00\ud800'
        xml = render_junit(compare([good], [good]))
        root = ET.fromstring(xml)
        self.assertEqual(root.find("testcase").attrib["name"], 'case<&"\ufffd\ufffd [seed=42]')
        self.assertIn("&lt;", xml)

    def test_cli_writes_xml_preserving_json_and_exit_codes(self):
        with tempfile.TemporaryDirectory() as folder:
            baseline, candidate, output = [Path(folder) / n for n in ("before.json", "after.json", "junit.xml")]
            baseline.write_text(json.dumps([self.good]))
            for data, expected in (([self.good], 0), ([self.bad], 1)):
                candidate.write_text(json.dumps(data))
                result = self.cli(baseline, candidate, output)
                self.assertEqual(result.returncode, expected, result.stderr)
                comparison = json.loads(result.stdout)
                root = ET.parse(output).getroot()
                self.assertEqual(root.attrib["failures"], str(expected))
                self.assertEqual(comparison["regressed"], bool(expected))

    def test_cli_invalid_input_never_writes_new_xml(self):
        with tempfile.TemporaryDirectory() as folder:
            baseline, candidate, output = [Path(folder) / n for n in ("before.json", "after.json", "junit.xml")]
            baseline.write_text(json.dumps([self.good]))
            for data in ("{", "[]", "[NaN]", json.dumps([dict(self.good, seed=999)])):
                candidate.write_text(data)
                result = self.cli(baseline, candidate, output)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, "")
                self.assertNotIn("Traceback", result.stderr)
                self.assertFalse(output.exists())

    def test_cli_invalid_input_does_not_replace_existing_xml(self):
        with tempfile.TemporaryDirectory() as folder:
            baseline, candidate, output = [Path(folder) / n for n in ("before.json", "after.json", "junit.xml")]
            baseline.write_text(json.dumps([self.good]))
            candidate.write_text("[]")
            output.write_text("previous evidence")
            self.assertEqual(self.cli(baseline, candidate, output).returncode, 2)
            self.assertEqual(output.read_text(), "previous evidence")

    def test_output_must_not_overwrite_inputs_or_aliases(self):
        with tempfile.TemporaryDirectory() as folder:
            baseline, candidate = [Path(folder) / n for n in ("before.json", "after.json")]
            clean = json.dumps([self.good])
            baseline.write_text(clean)
            candidate.write_text(clean)
            symlink = Path(folder) / "link.xml"
            symlink.symlink_to(baseline)
            hardlink = Path(folder) / "hard.xml"
            os.link(candidate, hardlink)
            for output in (baseline, candidate, symlink, hardlink):
                result = self.cli(baseline, candidate, output)
                self.assertEqual(result.returncode, 2)
                self.assertIn("must not overwrite", result.stderr)
                self.assertEqual(baseline.read_text(), clean)
                self.assertEqual(candidate.read_text(), clean)

    def test_missing_output_parent_is_clean_error(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "runs.json"
            path.write_text(json.dumps([self.good]))
            result = self.cli(path, path, Path(folder) / "missing" / "report.xml")
            self.assertEqual(result.returncode, 2)
            self.assertEqual(result.stdout, "")
            self.assertNotIn("Traceback", result.stderr)

    def test_junit_option_is_compare_only(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "junit.xml"
            for command in ("validate", "demo", "run"):
                result = subprocess.run([sys.executable, "-m", "agent_retry_rodeo.cli", command,
                                         "--junit-xml", str(output)], cwd=ROOT,
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode, 2)
                self.assertIn("only supported with compare", result.stderr)
                self.assertFalse(output.exists())
