# OpenClaw Client Ops SOP Skill

Repository-owned operational safety guidance and dependency-free tooling for client-facing OpenClaw work.

## Included controls

- bounded heavy-task execution and post-failure recovery;
- idempotency and canonical recipient rules;
- incident-ledger templates;
- Git-backed deployment provenance for local scripts and managed scheduler jobs;
- read-only drift verification without installing, deleting, or editing client resources.

## Deployment provenance

See `references/deployment-provenance.md` and the examples under `examples/`.

```bash
python3 scripts/deployment_provenance.py --help
```

The provenance manifest contains a canonical Git remote/commit and hashes. It intentionally excludes raw scheduler commands, credentials, client absolute paths, and live scheduler access.

## Maintainer verification

```bash
python3 scripts/post_run_check.py
```

The Repository uses only the Python standard library for these checks.
