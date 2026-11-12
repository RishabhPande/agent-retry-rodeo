# Scenario format v1

Copy `scenarios/01-lost-ack.yaml`. Required top-level fields are exactly:

- `schema_version`: integer 1.
- `id`: unique nonempty text.
- `title`, `description`: nonempty text, displayed as plain text.
- `fault`: `lost_ack`, `partial_failure`, `stale_version`, or `invalid_call`.
- `initial`: `status` text, `version` positive integer, `comments` list of text.
- `goal`: nonempty `status` and `comment` text. The goal comment must not exist initially.
- `expected`: exactly `goal_comment_count: 1` and `preserve_existing_comments: true`.

The first three faults fire once, at a fixed tool boundary; `invalid_call` is a standing workflow rule that rejects every violating call:

- `lost_ack`: first append commits but returns timeout with unknown commit status.
- `partial_failure`: first status update returns unavailable before mutation.
- `stale_version`: first status update receives a concurrent comment/version bump, then fails its version check.
- `invalid_call`: from `open`, only the `in-progress` transition is accepted. Every direct jump is rejected with the allowed step named in the `via` field, and the rejected call commits nothing.

The evaluator requires the target status, exactly one target comment, and preservation of original/external comments with multiplicity. It checks persisted state, not agent claims. Assertions include expected and actual values and a state path in exported JSON.

`retry-rodeo demo --scenarios path/to/pack` reads every `.yaml` in that folder. No Python expressions, file paths, HTTP calls, or custom executable assertion hooks are allowed in YAML. To introduce a new fault, change the engine and tests in a separate reviewed PR.

Validation rejects duplicate YAML mapping keys at any level. Integer fields do not accept boolean or floating-point lookalikes. The preservation assertion must use YAML boolean `true`, not the number `1`. Whitespace-only goal strings are rejected. Invalid packs return a filename and validation error through the CLI.

## Custom schedules (schema v2)

See `examples/custom-faults/repeated-outage.yaml`. Keep all v1 task/assertion fields,
set `schema_version: 2`, set `fault: custom`, and add `fault_plan`. The plan contains
1 to 64 rules, each with exactly:

```yaml
- action: append_comment
  occurrence: 1
  timing: after
  error: timeout
```

- `action`: `read_ticket`, `append_comment`, or `set_status`.
- `occurrence`: positive integer up to 10000, counted per action, per fresh case.
- `timing`: `before` rejects the call without mutation; `after` executes the
  ordinary operation, then replaces its observation with an error and unknown
  commit status. An after fault does not force an invalid write to commit.
- `error`: nonblank text, at most 200 characters.

Only one rule may target a particular action occurrence. Invalid typed write
inputs are rejected before consuming a rule occurrence, though they consume the
tool budget. Valid but stale version writes do count. Rules whose occurrence is
never reached simply do not fire; the trace shows what happened, not coverage of
all planned faults. The report includes the schedule and its full scenario
fingerprint; changing a rule makes old and new reports incomparable.

The generic before/after primitives let a pack combine repeated outages and
ambiguous commits without editing engine code. They do not add arbitrary tool
schemas, mutation scripts, executable hooks, delays or live-service chaos. New
primitives/operations still require code and review. Final-state assertions remain
parent-owned and always require one target comment, the target status and
preservation of existing comments. Built-in schema v1 packs remain unchanged.
