# Mapping the lost-ack ticket case to idempotencybench timeout_after_commit

Script: `examples/duplicate_count_mapping.py`. Test: `tests/test_duplicate_count_mapping.py` (set `IDEMPOTENCYBENCH` to a checkout to also cross-check against its `Ledger`).

Scripted baselines, not LLM results. Not a claim that the two harnesses are equivalent.

| idempotencybench needs | Retry Rodeo source |
|---|---|
| Stable task ID for the intended effect | `scenario_id:seed:agent` (for example `lost-ack:42:Naive retry`), so baselines never share a task. One ticket per run, so the ticket is the task. |
| Effect-defining fields | ticket (same task ID) and comment body, compared after formatting-only normalization (case, whitespace, quotes, number formats). No idempotency key exists in Retry Rodeo, so none is recorded or compared. |
| Persisted state after recovery | `final_state.comments` in the run report. Count of matching comments minus one = duplicates. |

Behavior mapping: the lost-ack fault commits the first comment write then returns a timeout with unknown commit status, which corresponds to the timeout-after-commit mode. Retry Rodeo's "Verify + recover" baseline reads state before retrying (closest to the "check first" prompt agent, not idempotency keys or receipts). "Naive retry" retries blindly.

Expected duplicate counts (tested): Naive retry = 1, Verify + recover = 0. Reformatted body counts as a duplicate; a different body does not.
Difference to state: Retry Rodeo's own `duplicate_comments` uses exact string equality; the mapping applies normalization on top, so it can count more.
