import copy
import json
from pathlib import Path
import tempfile
import unittest
from agent_retry_rodeo.engine import load_scenario, run, NaiveAgent, RecoveryAgent
from agent_retry_rodeo.report import render

class EngineTests(unittest.TestCase):
    def scenarios(self):
        return [load_scenario(p) for p in sorted(Path("scenarios").glob("*.yaml"))]
    def test_all_baselines(self):
        for scenario in self.scenarios():
            with self.subTest(scenario=scenario["id"]):
                naive = run(scenario, NaiveAgent())
                safe = run(scenario, RecoveryAgent())
                self.assertFalse(naive["success"])
                self.assertTrue(naive["false_completion"])
                self.assertTrue(safe["success"])
                self.assertFalse(safe["false_completion"])
    def test_determinism_and_input_unchanged(self):
        for scenario in self.scenarios():
            before = copy.deepcopy(scenario)
            self.assertEqual(run(scenario, RecoveryAgent()), run(scenario, RecoveryAgent()))
            self.assertEqual(before, scenario)
    def test_lost_ack_did_commit(self):
        result = run(self.scenarios()[0], NaiveAgent())
        event = result["events"][0]
        self.assertFalse(event["observation"]["ok"])
        self.assertEqual(len(event["after"]["comments"]), 1)
        self.assertEqual(result["duplicate_comments"], 1)
    def test_other_work_preserved(self):
        scenario = next(s for s in self.scenarios() if s["fault"] == "stale_version")
        result = run(scenario, RecoveryAgent())
        self.assertEqual(len(result["final_state"]["comments"]), 3)
    def test_unknown_fields_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            data = self.scenarios()[0]
            data["execute"] = "no"
            path = Path(d) / "bad.yaml"
            path.write_text(json.dumps(data))
            with self.assertRaises(ValueError): load_scenario(path)
    def test_unsafe_yaml_rejected(self):
        import yaml
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "bad.yaml"
            path.write_text('!!python/object/apply:os.system ["echo unsafe"]')
            with self.assertRaises(yaml.YAMLError): load_scenario(path)
    def test_report_escapes_script_close(self):
        result = run(self.scenarios()[0], NaiveAgent())
        result["title"] = "</script><script>alert(1)</script>"
        page = render([result])
        self.assertNotIn(result["title"], page)
        self.assertIn('\\u003c/script', page)

if __name__ == "__main__": unittest.main()
