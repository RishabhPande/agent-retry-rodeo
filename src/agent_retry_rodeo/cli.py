from __future__ import annotations
import argparse
import json
import importlib.util
import yaml
from pathlib import Path
from .engine import load_scenario, run, NaiveAgent, RecoveryAgent
from .report import render

def main():
    parser = argparse.ArgumentParser(description="Run local synthetic recovery scenarios. No network or API keys.")
    parser.add_argument("command", choices=["demo", "validate", "run"])
    parser.add_argument("--scenarios", type=Path, default=Path("scenarios"), help="Scenario folder, relative to current directory")
    parser.add_argument("--output", type=Path, default=Path("rodeo-output"))
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--agent", type=Path, help="Trusted local Python file exporting create_agent(); executes arbitrary code")
    args = parser.parse_args()
    if args.command == "run" and args.agent is None:
        parser.error("run requires --agent path/to/agent.py")
    if args.command != "run" and args.agent is not None:
        parser.error("--agent is only supported with run")
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
    factory = None
    if args.command == "run":
        try:
            spec = importlib.util.spec_from_file_location("rodeo_user_agent", args.agent.resolve())
            if spec is None or spec.loader is None:
                raise ValueError("Agent must be a readable Python file")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            factory = getattr(module, "create_agent", None)
            if not callable(factory):
                raise ValueError("Agent file must export create_agent()")
        except Exception as exc:
            parser.error(f"Cannot load trusted local agent: {exc}")
    results = []
    for scenario in scenarios:
        try:
            agents = (NaiveAgent(), RecoveryAgent()) if factory is None else (factory(),)
        except Exception as exc:
            parser.error(f"create_agent() failed: {exc}")
        for agent in agents:
            if not isinstance(getattr(agent, "name", None), str) or not agent.name.strip() or not callable(getattr(agent, "run", None)):
                parser.error("create_agent() must return an agent with a nonempty name and run(call, goal)")
            results.append(run(scenario, agent, args.seed))
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    (args.output / "index.html").write_text(render(results), encoding="utf-8")
    for r in results:
        print(f"{'PASS' if r['success'] else 'FAIL'}  {r['scenario_id']:18} {r['agent']:18} false_completion={r['false_completion']}")
    print(f"Replay: {(args.output / 'index.html').resolve()}")
    print("These are scripted baselines, not measured LLM performance." if factory is None else "Custom local adapter. This is not a sandbox; model provenance is not verified.")
    if factory is not None and any(not r["success"] for r in results):
        raise SystemExit(1)

if __name__ == "__main__":
    main()
