# External agent protocol v1

This POSIX transport connects a trusted executable to the synthetic ticket world.
It does not make an arbitrary agent compatible automatically: provide a bridge
that maps the agent's tools to the following protocol. `examples/process_agent.py`
is a runnable scripted reference, not evidence about any model's performance.

## Launch

```bash
retry-rodeo run --output process-run --agent-timeout 30 --max-tool-calls 40 \
  --agent-command python examples/process_agent.py
```

Put every Rodeo option before `--agent-command`. The remaining arguments are
passed directly to the executable, not through a shell. A fresh process starts
for each case in the current working directory with the inherited environment.
No API keys, model dependencies or paid calls are supplied by Rodeo. Add optional
framework/model dependencies to your own bridge, with your own spending controls.

## JSON lines on stdin/stdout

Every frame is a UTF-8 JSON object terminated by a newline. Flush stdout after
each frame. Do not put logs on stdout; stderr is drained but omitted from evidence.
Duplicate keys, nonfinite numbers, unknown frame types/fields, malformed JSON,
frames over 64000 bytes, and unterminated final frames fail the case.

Parent sends one start frame:

```json
{"type":"start","protocol":1,"goal":{"status":"resolved","comment":"Recovery verified"}}
```

Agent sends a tool request, then waits for its observation:

```json
{"type":"call","action":"read_ticket","params":{}}
```

Parent returns only the tool observation:

```json
{"type":"observation","ok":true,"result":{"status":"open","version":1,"comments":[]}}
```

Available actions:

- `read_ticket`, with `{}`. Returns current `status`, `version`, `comments`.
- `append_comment`, with `{"text":"..."}`. May commit even if its observation fails.
- `set_status`, with `{"status":"resolved","expected_version":2}`. The version
  must match persisted state; re-read after a conflict. Workflow rejection may
  name an intermediate status in `via`.

Your decision loop can use any model/framework, as long as calls go through this
bridge. Do not assume a failed observation means a write was rolled back. Read
state to verify a task before claiming done. When finished, send:

```json
{"type":"done","claimed_complete":true}
```

Then exit with status 0. `false` is a valid completion claim. More stdout after
done, a nonzero exit, a crash, missing done or a deadline all fail the run. The
parent never accepts state or assertions supplied by the child: it grades its
own persisted state and retains earlier tool events after an error. Success still
means state assertions passed, not merely that a done frame said true.

## Limits and trust

The per-case deadline covers the entire process lifetime, including waiting for
input, blocked output, and shutdown. Combined stdout/stderr is capped at 4 MB;
queued observations are capped too. The call budget defaults to 100. On timeout
or finish, the POSIX process group is killed and pipes are closed. This does not
contain children that escape the group, bound memory use, prevent filesystem or
network access, or revoke paid API credentials. It is not a security sandbox.
Only run code you trust. A same-user process can tamper with local files outside
the protocol; parent-owned state is a protocol separation, not hostile-code
isolation. Use a separate OS/container policy when adversarial code is involved.

Reports label runs as external commands with unverified model provenance. They
do not store the command line, environment or stderr. Tool/exception text may
still contain information from your adapter; inspect reports before sharing.
The examples use no network and no model. A real-model run can be nondeterministic
and wallet-bearing, so its costs and reproducibility are yours to manage. Saved
report comparison checks matching synthetic cases, not model identity, general
reliability or real application coverage.
