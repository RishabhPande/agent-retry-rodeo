from __future__ import annotations
import argparse
import json
import math
from .process_agent import ProcessAgent
import importlib.util
import yaml
from pathlib import Path
from .engine import load_scenario, run, NaiveAgent, RecoveryAgent
from .report import render
from .compare import compare, load_runs
from .junit import render_junit

def main():
    parser = argparse.ArgumentParser(description="Grade agent recovery against local synthetic state. Trusted adapters may use network or paid APIs.")
    parser.add_argument("command", choices=["demo", "validate", "run", "compare"])
    parser.add_argument("--scenarios", type=Path, default=Path("scenarios"), help="Scenario folder, relative to current directory")
    parser.add_argument("--output", type=Path, default=Path("rodeo-output"))
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--max-tool-calls", type=int, default=None,
                        help="Positive per-run tool-call budget for run (default: 100); not a timeout or sandbox")
    parser.add_argument("--agent", type=Path, help="Trusted local Python file exporting create_agent(); executes arbitrary code")
    parser.add_argument("--agent-command", nargs=argparse.REMAINDER,
                        help="Trusted external executable and arguments; must be the last option")
    parser.add_argument("--agent-timeout", type=float, default=None,
                        help="Positive per-case external process deadline in seconds (default: 30)")
    parser.add_argument("--baseline", type=Path, help="Saved single-adapter results.json")
    parser.add_argument("--candidate", type=Path, help="Matching candidate results.json")
    parser.add_argument("--junit-xml", type=Path, help="Optional compare-only JUnit regression report; not adapter pass/fail")
    args = parser.parse_args()
    if args.junit_xml is not None and args.command != "compare":
        parser.error("--junit-xml is only supported with compare")
    if args.agent_command is not None and (args.command != "run" or not args.agent_command or args.agent is not None):
        parser.error("--agent-command requires run, an executable, and no --agent")
    if args.agent_timeout is not None and (args.agent_command is None or not math.isfinite(args.agent_timeout) or args.agent_timeout <= 0):
        parser.error("--agent-timeout requires --agent-command and a positive finite value")
    if args.max_tool_calls is not None:
        if args.command != "run" or args.max_tool_calls < 1:
            parser.error("--max-tool-calls requires run and a positive integer")
    if args.command == "compare":
        if args.baseline is None or args.candidate is None or args.agent is not None:
            parser.error("compare requires --baseline and --candidate, and does not load --agent")
        try:
            if args.junit_xml is not None:
                for source in (args.baseline, args.candidate):
                    if (args.junit_xml.resolve() == source.resolve() or
                            (args.junit_xml.exists() and source.exists() and args.junit_xml.samefile(source))):
                        raise ValueError("JUnit output must not overwrite a baseline or candidate report")
            comparison = compare(load_runs(args.baseline), load_runs(args.candidate))
            if args.junit_xml is not None:
                args.junit_xml.write_text(render_junit(comparison), encoding="utf-8")
        except (ValueError, OSError) as exc:
            parser.error(f"Cannot compare reports: {exc}")
        print(json.dumps(comparison, indent=2))
        if comparison["regressed"]:
            raise SystemExit(1)
        return
    if args.baseline is not None or args.candidate is not None:
        parser.error("--baseline and --candidate are only supported with compare")
    if args.command == "run" and args.agent is None and args.agent_command is None:
        parser.error("run requires --agent path/to/agent.py or --agent-command executable args...")
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
    if args.agent_command is not None:
        factory = lambda: ProcessAgent(args.agent_command, args.agent_timeout or 30.0)
    elif args.command == "run":
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
            results.append(run(scenario, agent, args.seed, max_tool_calls=args.max_tool_calls or 100))
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
