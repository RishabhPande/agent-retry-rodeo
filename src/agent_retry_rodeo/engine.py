"""A deliberately small, state-grounded simulator, not a production agent runtime."""
from __future__ import annotations
import copy
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
import yaml

FAULTS = {"lost_ack", "partial_failure", "stale_version"}
FIELDS = {"schema_version", "id", "title", "description", "fault", "initial", "goal", "expected"}

class ScenarioLoader(yaml.SafeLoader):
    """Safe YAML with duplicate keys rejected instead of silently overwritten."""

def _unique_mapping(loader, node, deep=False):
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in mapping
        except TypeError as exc:
            raise ValueError("Scenario mapping keys must be scalar values") from exc
        if duplicate:
            raise ValueError(f"Duplicate scenario key: {key}")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping

ScenarioLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _unique_mapping)

def load_scenario(path: Path) -> dict:
    if path.stat().st_size > 64_000:
        raise ValueError("Scenario exceeds 64 KB")
    data = yaml.load(path.read_text(encoding="utf-8"), Loader=ScenarioLoader)
    if not isinstance(data, dict) or set(data) != FIELDS:
        raise ValueError("Scenario must contain exactly the documented fields")
    if type(data["schema_version"]) is not int or data["schema_version"] != 1 or not isinstance(data["fault"], str) or data["fault"] not in FAULTS:
        raise ValueError("Unsupported schema or fault")
    for field in ("id", "title", "description"):
        if not isinstance(data[field], str) or not data[field].strip():
            raise ValueError(f"{field} must be nonempty text")
    if not isinstance(data["initial"], dict) or set(data["initial"]) != {"status", "version", "comments"}:
        raise ValueError("initial requires status, version, comments")
    s = data["initial"]
    if not isinstance(s["status"], str) or type(s["version"]) is not int or s["version"] < 1 or not isinstance(s["comments"], list) or not all(isinstance(x, str) for x in s["comments"]):
        raise ValueError("Invalid initial state")
    if not isinstance(data["goal"], dict) or set(data["goal"]) != {"status", "comment"} or not all(isinstance(x, str) and x.strip() for x in data["goal"].values()):
        raise ValueError("goal requires nonempty status and comment")
    if data["goal"]["comment"] in s["comments"]:
        raise ValueError("Goal comment must not already exist")
    if not isinstance(data["expected"], dict) or set(data["expected"]) != {"goal_comment_count", "preserve_existing_comments"} or type(data["expected"]["goal_comment_count"]) is not int or data["expected"]["goal_comment_count"] != 1 or data["expected"]["preserve_existing_comments"] is not True:
        raise ValueError("Expected assertions must require exactly one goal comment and preservation")
    return data

@dataclass(frozen=True)
class Observation:
    ok: bool
    result: dict

class World:
    def __init__(self, scenario: dict, seed: int):
        self.scenario = scenario
        self.state = copy.deepcopy(scenario["initial"])
        self.events = []
        self.fault_used = False
        self.incident = f"INC-{random.Random(seed).randrange(1000, 9999)}"

    def call(self, action: str, **params) -> Observation:
        before = copy.deepcopy(self.state)
        fault = self.scenario["fault"]
        label = None
        if action == "read_ticket":
            out = Observation(True, copy.deepcopy(self.state))
        elif action == "append_comment":
            self.state["comments"].append(params["text"])
            self.state["version"] += 1
            if fault == "lost_ack" and not self.fault_used:
                self.fault_used = True
                label = "Write committed; acknowledgement lost"
                out = Observation(False, {"error": "timeout", "committed": "unknown"})
            else:
                out = Observation(True, {"comment_added": True})
        elif action == "set_status":
            if fault == "partial_failure" and not self.fault_used:
                self.fault_used = True
                label = "Second step failed before commit"
                out = Observation(False, {"error": "service_unavailable"})
            else:
                if fault == "stale_version" and not self.fault_used:
                    self.fault_used = True
                    self.state["comments"].append(f"{self.incident}: another worker inspected this ticket")
                    self.state["version"] += 1
                    label = "Concurrent write changed the ticket version"
                if params.get("expected_version") != self.state["version"]:
                    out = Observation(False, {"error": "version_conflict"})
                else:
                    self.state["status"] = params["status"]
                    self.state["version"] += 1
                    out = Observation(True, {"status_updated": True})
        else:
            raise ValueError(f"Unknown action: {action}")
        self.events.append({"step": len(self.events) + 1, "action": action, "params": params, "observation": {"ok": out.ok, **out.result}, "fault": label, "before": before, "after": copy.deepcopy(self.state)})
        return out

class Agent(Protocol):
    name: str
    def run(self, call, goal: dict) -> bool:
        """Use only the tool callable. Return whether the agent claims completion."""

class NaiveAgent:
    name = "Naive retry"
    kind = "scripted, not an LLM"
    def run(self, call, goal):
        first = call("append_comment", text=goal["comment"])
        if not first.ok:
            call("append_comment", text=goal["comment"])
        current = call("read_ticket")
        call("set_status", status=goal["status"], expected_version=current.result["version"])
        return True  # Deliberately wrong: assumes the task finished.

class RecoveryAgent:
    name = "Verify + recover"
    kind = "scripted, not an LLM"
    def run(self, call, goal):
        for _ in range(6):  # Bound all retries.
            state = call("read_ticket").result
            if goal["comment"] not in state["comments"]:
                call("append_comment", text=goal["comment"])
                continue
            if state["status"] != goal["status"]:
                call("set_status", status=goal["status"], expected_version=state["version"])
                continue
            return True
        return False

def run(scenario: dict, agent: Agent, seed: int = 42) -> dict:
    world = World(scenario, seed)
    error = None
    try:
        claimed = agent.run(world.call, copy.deepcopy(scenario["goal"]))
        if type(claimed) is not bool:
            raise ValueError("Agent.run must return a boolean completion claim")
    except Exception as exc:
        claimed = False
        error = {"type": type(exc).__name__, "message": str(exc)}
    state, goal = world.state, scenario["goal"]
    count = state["comments"].count(goal["comment"])
    # Preserve both original and externally added comments, including multiplicity.
    from collections import Counter
    required = Counter(scenario["initial"]["comments"])
    for event in world.events:
        if event["fault"] == "Concurrent write changed the ticket version":
            required += Counter(event["after"]["comments"]) - Counter(event["before"]["comments"])
    actual = Counter(state["comments"])
    assertions = [
        {"id": "target_status", "pass": state["status"] == goal["status"], "expected": goal["status"], "actual": state["status"], "path": "final_state.status"},
        {"id": "exactly_one_comment", "pass": count == 1, "expected": 1, "actual": count, "path": "final_state.comments"},
        {"id": "preserve_comments", "pass": all(actual[k] >= v for k, v in required.items()), "expected": dict(required), "actual": dict(actual), "path": "final_state.comments"},
    ]
    success = error is None and all(x["pass"] for x in assertions)
    return {"schema_version": 1, "scenario_id": scenario["id"], "scenario_version": scenario["schema_version"], "title": scenario["title"], "description": scenario["description"], "fault": scenario["fault"], "seed": seed, "agent": agent.name, "baseline_type": getattr(agent, "kind", "custom local adapter; model provenance not verified"), "initial_state": copy.deepcopy(scenario["initial"]), "error": error, "claimed_complete": bool(claimed), "success": success, "false_completion": bool(claimed) and not success, "duplicate_comments": max(0, count - 1), "uncompleted_steps": int(state["status"] != goal["status"]) + int(count == 0), "assertions": assertions, "events": world.events, "final_state": copy.deepcopy(state)}
