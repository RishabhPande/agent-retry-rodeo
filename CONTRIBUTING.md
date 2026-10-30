# Contributing

Start small. A useful failure fixture beats a large untested framework.

1. Fork and create a branch.
2. Install with `python -m pip install -e .`.
3. Read `docs/scenarios.md`, then copy a fixture.
4. Validate, run tests, and inspect the generated replay.
5. Open a PR explaining the task, the fault, and the final-state assertion that proves the result.

Do not include real customer data, credentials, copied private incidents, live-service actions, or network-dependent default tests. Keep the no-key offline demo working. Use synthetic examples. Do not advertise scripted baselines as model performance.

For new fault types, explain what is committed before failure and add regression tests. For real-agent adapters, document optional dependencies and costs separately. Do not add API keys to source, reports, screenshots, issues, or logs.

Before submitting:

```bash
retry-rodeo validate
python -m unittest discover -s tests -v
retry-rodeo demo
```

Open an issue before a large architectural change. This release is a learning/demo kit, not a production reliability or security guarantee.
