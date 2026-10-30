# Changes

## Unreleased

- Add strict YAML type and duplicate-key checks, with clean CLI validation errors.
- Add contributor-input, evaluator snapshot, false-completion and CLI artifact tests.
- Add a deterministic static Pages build script and no-main-merge deployment runbook.
- Keep all agent results labeled as synthetic scripted teaching baselines.

### Bring your own local agent

- Add an explicit trusted-local adapter runner and copyable `create_agent()` example.
- Preserve initial state and partial evidence for no-op/error runs.
- Reject non-boolean completion outputs instead of treating truthy values as done.
- Make replay strategy controls data-driven; handle empty traces without crashing.
