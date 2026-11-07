"""Compare saved local-adapter runs. Reports are evidence, not signed attestations."""
from __future__ import annotations
import json
from pathlib import Path
import re


def _unique_object(pairs: list) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str):
    raise ValueError(f"Non-standard JSON number: {value}")


def load_runs(path: Path) -> list:
    """Reject ambiguous JSON before looking at run metrics.

    This is format validation, not authentication of a saved report.
    """
    return json.loads(path.read_text(encoding="utf-8"),
                      object_pairs_hook=_unique_object,
                      parse_constant=_reject_constant)


def _index(runs: list) -> dict:
    if not isinstance(runs, list) or not runs:
        raise ValueError("Expected a nonempty run array")
    indexed = {}
    for run in runs:
        if not isinstance(run, dict) or type(run.get("schema_version")) is not int or run["schema_version"] != 1:
            raise ValueError("Unsupported run schema")
        if not isinstance(run.get("scenario_id"), str) or not run["scenario_id"].strip() or type(run.get("seed")) is not int:
            raise ValueError("Each run needs a scenario_id and integer seed")
        digest = run.get("scenario_sha256")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("Missing scenario fingerprint; regenerate reports with this version")
        for field in ("success", "false_completion", "claimed_complete"):
            if type(run.get(field)) is not bool:
                raise ValueError(f"{field} must be a boolean")
        for field in ("duplicate_comments", "uncompleted_steps"):
            if type(run.get(field)) is not int or run[field] < 0:
                raise ValueError(f"{field} must be a nonnegative integer")
        if "error" not in run or (run["error"] is not None and not isinstance(run["error"], dict)):
            raise ValueError("Each run needs an error object or null")
        key = (run["scenario_id"], run["seed"])
        if key in indexed:
            raise ValueError("Multiple runs for one scenario/seed; record one adapter per file, not demo output")
        indexed[key] = run
    return indexed


def compare(before: list, after: list) -> dict:
    """Reject incomparable packs, then report directional regressions per case."""
    baseline, candidate = _index(before), _index(after)
    if baseline.keys() != candidate.keys():
        raise ValueError("Scenario/seed sets differ; missing or added cases cannot be compared")
    cases = []
    for key in sorted(baseline):
        old, new = baseline[key], candidate[key]
        if old["scenario_sha256"] != new["scenario_sha256"]:
            raise ValueError(f"Scenario content changed for {key[0]}; record a matching baseline")
        regressions = []
        if old["success"] and not new["success"]:
            regressions.append("lost_success")
        if not old["false_completion"] and new["false_completion"]:
            regressions.append("new_false_completion")
        if old["error"] is None and new["error"] is not None:
            regressions.append("new_adapter_error")
        for field in ("duplicate_comments", "uncompleted_steps"):
            if new[field] > old[field]:
                regressions.append("increased_" + field)
        cases.append({"scenario_id": key[0], "seed": key[1], "regressions": regressions})
    return {"schema_version": 1, "regressed": any(c["regressions"] for c in cases),
            "cases": cases,
            "scope": "Directional checks on matching synthetic fixtures. Not an LLM benchmark or authenticity check."}
