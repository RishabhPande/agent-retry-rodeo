import os, sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src")); sys.path.insert(0, str(ROOT / "examples"))
from agent_retry_rodeo.engine import load_scenario, run, NaiveAgent, RecoveryAgent
from duplicate_count_mapping import duplicate_count, normalize_value, to_effects

SC = load_scenario(ROOT / "scenarios/01-lost-ack.yaml")
GOAL = SC["goal"]["comment"]

class Mapping(unittest.TestCase):
    def test_naive_retry_leaves_one_duplicate(self):
        r = run(SC, NaiveAgent())
        self.assertEqual(duplicate_count(r, GOAL), 1)
        self.assertEqual(r["duplicate_comments"], 1)  # engine's own exact-match count agrees

    def test_verify_then_recover_leaves_zero(self):
        r = run(SC, RecoveryAgent())
        self.assertEqual(duplicate_count(r, GOAL), 0)
        self.assertEqual(r["duplicate_comments"], 0)

    def test_reformatted_comment_still_counts(self):
        r = run(SC, RecoveryAgent())
        r["final_state"]["comments"].append("  " + GOAL.upper() + "  ")
        self.assertEqual(duplicate_count(r, GOAL), 1)          # normalized view
        self.assertEqual(r["final_state"]["comments"].count(GOAL), 1)  # exact view misses it

    def test_different_body_is_not_a_duplicate(self):
        r = run(SC, RecoveryAgent())
        r["final_state"]["comments"].append(GOAL + " again")
        self.assertEqual(duplicate_count(r, GOAL), 0)

    def test_naive_run_commits_two_matching_effects(self):
        r = run(SC, NaiveAgent())
        self.assertEqual(len(to_effects(r, GOAL)), 2)

    def test_optional_crosscheck_with_idempotencybench_ledger(self):
        ib = os.environ.get("IDEMPOTENCYBENCH")
        if not ib: self.skipTest("set IDEMPOTENCYBENCH to a checkout to cross-check")
        sys.path.insert(0, str(Path(ib) / "src"))
        from idempotencybench.world import Ledger, Effect
        r = run(SC, NaiveAgent())
        led = Ledger()
        for e in to_effects(r, GOAL):
            led.commit(Effect("create_ticket", {"queue": e["args"]["ticket"], "title": e["args"]["body"]}, "", e["task_id"], 0))
        self.assertEqual(led.violations(f"{r['scenario_id']}:{r['seed']}:{r['agent']}"), duplicate_count(r, GOAL))

    def test_baselines_never_count_across_runs(self):
        a, b = run(SC, NaiveAgent()), run(SC, RecoveryAgent())
        ids = {e["task_id"] for e in to_effects(a, GOAL) + to_effects(b, GOAL)}
        self.assertEqual(len(ids), 2)  # separate task ids, so a pooled ledger cannot cross-count
        self.assertEqual(duplicate_count(a, GOAL) + duplicate_count(b, GOAL), 1)

if __name__ == "__main__": unittest.main()
