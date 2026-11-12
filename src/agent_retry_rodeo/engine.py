"""A deliberately small, state-grounded simulator, not a production agent runtime."""
from __future__ import annotations
import copy
import hashlib
import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
import yaml

FAULTS = {"lost_ack", "partial_failure", "stale_version", "invalid_call"}
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
    if not isinstance(data, dict) or set(data) not in (FIELDS, FIELDS | {"fault_plan"}):
        raise ValueError("Scenario must contain exactly the documented fields")
    if type(data["schema_version"]) is not int or not isinstance(data["fault"], str):
        raise ValueError("Unsupported schema or fault")
    if data["schema_version"] == 2 and data["fault"] == "custom":
        plan = data.get("fault_plan")
        if not isinstance(plan, list) or not 1 <= len(plan) <= 64:
            raise ValueError("Custom fault_plan requires 1 to 64 rules")
        seen = set()
        for rule in plan:
            if not isinstance(rule, dict) or set(rule) != {"action", "occurrence", "timing", "error"}:
                raise ValueError("Fault rule requires action, occurrence, timing, error")
            if rule["action"] not in ("read_ticket", "append_comment", "set_status") or type(rule["occurrence"]) is not int or not 1 <= rule["occurrence"] <= 10000:
                raise ValueError("Invalid fault action or occurrence")
            if rule["timing"] not in ("before", "after") or not isinstance(rule["error"], str) or not rule["error"].strip() or len(rule["error"]) > 200:
                raise ValueError("Invalid fault timing or error")
            key = (rule["action"], rule["occurrence"])
            if key in seen:
                raise ValueError("Only one fault rule may target each action occurrence")
            seen.add(key)
    elif data["schema_version"] != 1 or data["fault"] not in FAULTS or "fault_plan" in data:
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

class ToolCallLimitError(RuntimeError):
    """The adapter exhausted its synthetic tool-call budget."""


@dataclass(frozen=True)
class Observation:
    ok: bool
    result: dict

class World:
    def __init__(self, scenario: dict, seed: int, max_tool_calls: int = 100):
        if type(max_tool_calls) is not int or max_tool_calls < 1:
            raise ValueError("max_tool_calls must be a positive integer")
        self.max_tool_calls = max_tool_calls
        self.tool_calls = 0
        self.limit_exceeded = False
        self.scenario = scenario
        self.state = copy.deepcopy(scenario["initial"])
        self.events = []
        self.fault_used = False
        self.action_counts = {}
        self.incident = f"INC-{random.Random(seed).randrange(1000, 9999)}"

    def call(self, action: str, **params) -> Observation:
        if self.tool_calls >= self.max_tool_calls:
            self.limit_exceeded = True
            raise ToolCallLimitError(f"Tool-call budget exhausted ({self.max_tool_calls})")
        self.tool_calls += 1
        # Reject malformed state values before a write or a one-shot fault.
        # Otherwise a list/dict comment can crash final-state scoring outside
        # the adapter exception boundary, leaving no usable run report.
        if action == "append_comment" and not isinstance(params.get("text"), str):
            raise ValueError("append_comment requires text to be a string")
        if action == "set_status" and not isinstance(params.get("status"), str):
            raise ValueError("set_status requires status to be a string")
        before = copy.deepcopy(self.state)
        fault = self.scenario["fault"]
        self.action_counts[action] = self.action_counts.get(action, 0) + 1
        rule = next((r for r in self.scenario.get("fault_plan", [])
                     if r["action"] == action and r["occurrence"] == self.action_counts[action]), None)
        label = None
        if rule and rule["timing"] == "before":
            self.fault_used = True
            out = Observation(False, {"error": rule["error"]})
            self.events.append({"step": len(self.events) + 1, "action": action, "params": params,
                                "observation": {"ok": out.ok, **out.result},
                                "fault": f"Custom before fault: {rule['error']}",
                                "before": before, "after": copy.deepcopy(self.state)})
            return out
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
            # invalid_call is a standing workflow rule, not a one-shot fault:
            # from "open" the tracker only accepts "in-progress". Every direct
            # jump is rejected with the allowed intermediate step named, and
            # nothing commits. An agent that ignores the error detail never
            # completes; one that reads it takes the named step.
            if fault == "invalid_call":
                allowed = {"open": {"in-progress"}}.get(self.state["status"])
                if allowed is not None and params["status"] not in allowed:
                    via = sorted(allowed)[0]
                    label = "Rejected invalid transition; allowed step named"
                    out = Observation(False, {
                        "error": "invalid_transition",
                        "detail": f"cannot move {self.state['status']} to {params['status']}; set {via} first",
                        "via": via,
                    })
                    self.events.append({"step": len(self.events) + 1, "action": action, "params": params, "observation": {"ok": out.ok, **out.result}, "fault": label, "before": before, "after": copy.deepcopy(self.state)})
                    return out
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
        if rule and rule["timing"] == "after":
            self.fault_used = True
            label = f"Custom after fault: {rule['error']}"
            out = Observation(False, {"error": rule["error"], "committed": "unknown"})
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
                attempt = call("set_status", status=goal["status"], expected_version=state["version"])
                if not attempt.ok and attempt.result.get("error") == "invalid_transition" and attempt.result.get("via"):
                    # The rejection names the required intermediate step.
                    # Re-read, take it, then finish on the next pass.
                    via = attempt.result["via"]
                    fresh = call("read_ticket").result
                    call("set_status", status=via, expected_version=fresh["version"])
                continue
            return True
        return False

def run(scenario: dict, agent: Agent, seed: int = 42, *, max_tool_calls: int = 100) -> dict:
    world = World(scenario, seed, max_tool_calls)
    error = None
    try:
        claimed = agent.run(world.call, copy.deepcopy(scenario["goal"]))
        if type(claimed) is not bool:
            raise ValueError("Agent.run must return a boolean completion claim")
    except Exception as exc:
        claimed = False
        error = {"type": type(exc).__name__, "message": str(exc)}
    # An adapter cannot turn an exhausted budget into success by catching it.
    if world.limit_exceeded:
        claimed = False
        error = {"type": "ToolCallLimitError",
                 "message": f"Tool-call budget exhausted ({world.max_tool_calls})"}
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
    return {"fault_plan": copy.deepcopy(scenario.get("fault_plan", [])), "max_tool_calls": world.max_tool_calls, "tool_calls": world.tool_calls, "schema_version": 1, "scenario_id": scenario["id"], "scenario_sha256": hashlib.sha256(json.dumps(scenario, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest(), "scenario_version": scenario["schema_version"], "title": scenario["title"], "description": scenario["description"], "fault": scenario["fault"], "seed": seed, "agent": agent.name, "baseline_type": getattr(agent, "kind", "custom local adapter; model provenance not verified"), "initial_state": copy.deepcopy(scenario["initial"]), "error": error, "claimed_complete": bool(claimed), "success": success, "false_completion": bool(claimed) and not success, "duplicate_comments": max(0, count - 1), "uncompleted_steps": int(state["status"] != goal["status"]) + int(count == 0), "assertions": assertions, "events": world.events, "final_state": copy.deepcopy(state)}
