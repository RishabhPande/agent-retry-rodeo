# Scenario format v1

Copy `scenarios/01-lost-ack.yaml`. Required top-level fields are exactly:

- `schema_version`: integer 1.
- `id`: unique nonempty text.
- `title`, `description`: nonempty text, displayed as plain text.
- `fault`: `lost_ack`, `partial_failure`, or `stale_version`.
- `initial`: `status` text, `version` positive integer, `comments` list of text.
- `goal`: nonempty `status` and `comment` text. The goal comment must not exist initially.
- `expected`: exactly `goal_comment_count: 1` and `preserve_existing_comments: true`.

Each fault fires once, at a fixed tool boundary:

- `lost_ack`: first append commits but returns timeout with unknown commit status.
- `partial_failure`: first status update returns unavailable before mutation.
- `stale_version`: first status update receives a concurrent comment/version bump, then fails its version check.

The evaluator requires the target status, exactly one target comment, and preservation of original/external comments with multiplicity. It checks persisted state, not agent claims. Assertions include expected and actual values and a state path in exported JSON.

`retry-rodeo demo --scenarios path/to/pack` reads every `.yaml` in that folder. No Python expressions, file paths, HTTP calls, or custom executable assertion hooks are allowed in YAML. To introduce a new fault, change the engine and tests in a separate reviewed PR.

Validation rejects duplicate YAML mapping keys at any level. Integer fields do not accept boolean or floating-point lookalikes. The preservation assertion must use YAML boolean `true`, not the number `1`. Whitespace-only goal strings are rejected. Invalid packs return a filename and validation error through the CLI.
