"""Duplicate-count mapping: agent-retry-rodeo lost-ack case -> idempotencybench.

Maps one Retry Rodeo run report to three things idempotencybench's semantic
duplicate count needs: a task id, effect-defining fields, and persisted state.
Offline, stdlib only. Scripted baselines, not LLM results.
"""
import re, sys, json
from decimal import Decimal, InvalidOperation

_NUM = re.compile(r"^[$€£]?\s*-?[\d,]+(\.\d+)?$")

def normalize_value(v):
    """Same formatting-only normalization idempotencybench documents (world.py)."""
    s = re.sub(r"\s+", " ", str(v).strip()).strip("'\"").strip()
    if _NUM.match(s):
        try:
            return format(Decimal(s.lstrip("$€£ ").replace(",", "")).normalize(), "f")
        except InvalidOperation:
            pass
    return s.casefold()

def to_effects(report, goal_comment):
    """Persisted-state view: one effect per matching comment left in final_state.
    task_id = scenario_id:seed:agent (one ticket per run, so the ticket id is that task).
    Idempotency keys do not exist in this simulator, so none is recorded."""
    task_id = f"{report['scenario_id']}:{report['seed']}:{report['agent']}"
    n = sum(1 for c in report["final_state"]["comments"]
            if normalize_value(c) == normalize_value(goal_comment))
    return [{"tool": "append_comment", "task_id": task_id,
             "args": {"ticket": task_id, "body": goal_comment}} for _ in range(n)]

def duplicate_count(report, goal_comment):
    effects = to_effects(report, goal_comment)
    seen = {}
    for e in effects:
        sid = (e["task_id"], e["tool"], normalize_value(e["args"]["ticket"]),
               normalize_value(e["args"]["body"]))
        seen[sid] = seen.get(sid, 0) + 1
    return sum(n - 1 for n in seen.values() if n > 1)
