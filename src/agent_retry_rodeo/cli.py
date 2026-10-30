from __future__ import annotations
import argparse
import json
import yaml
from pathlib import Path
from .engine import load_scenario, run, NaiveAgent, RecoveryAgent
from .report import render

def main():
    parser = argparse.ArgumentParser(description="Run local synthetic recovery scenarios. No network or API keys.")
    parser.add_argument("command", choices=["demo", "validate"])
    parser.add_argument("--scenarios", type=Path, default=Path("scenarios"), help="Scenario folder, relative to current directory")
    parser.add_argument("--output", type=Path, default=Path("rodeo-output"))
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    paths = sorted(args.scenarios.glob("*.yaml"))
    if not paths:
        parser.error(f"No .yaml scenarios in {args.scenarios}")
    scenarios = []
    for path in paths:
        try:
            scenarios.append(load_scenario(path))
        except (ValueError, OSError, yaml.YAMLError) as exc:
            parser.error(f"Invalid scenario {path}: {exc}")
    ids = [s["id"] for s in scenarios]
    if len(set(ids)) != len(ids):
        parser.error("Scenario ids must be unique")
    if args.command == "validate":
        print(f"Validated {len(scenarios)} scenarios")
        return
    results = [run(s, agent, args.seed) for s in scenarios for agent in (NaiveAgent(), RecoveryAgent())]
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    (args.output / "index.html").write_text(render(results), encoding="utf-8")
    for r in results:
        print(f"{'PASS' if r['success'] else 'FAIL'}  {r['scenario_id']:18} {r['agent']:18} false_completion={r['false_completion']}")
    print(f"Replay: {(args.output / 'index.html').resolve()}")
    print("These are scripted baselines, not measured LLM performance.")

if __name__ == "__main__":
    main()
