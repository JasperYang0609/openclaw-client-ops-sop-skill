# Deployment Provenance — Repo-owned, Read-only Verification

Use this contract when client-local scripts or enabled scheduler jobs need a traceable canonical source. It does **not** install files, read or write scheduler configuration, or repair a live client automatically.

## Boundary

- Canonical implementation must live in an owned Git Repository.
- Capture runs only from a clean repository: tracked modifications and untracked files both block.
- Verification consumes a deployment directory and a scheduler inventory JSON supplied through an approved read-only adapter.
- Do not invent or shell out to a scheduler command from this skill. Export inventory using the target platform's authorized read-only mechanism.
- Never put tokens, credentials, private keys, customer absolute paths, or secret-bearing commands into the spec or manifest.

## Versioned deployment spec

Commit a JSON spec in the implementation Repository. See `examples/deployment-spec.example.json`.

- `managedRoots`: deployment subtrees exclusively managed by this spec. Exact file-set verification detects missing and extra files there.
- `jobNamespace`: stable prefix for scheduler jobs managed by this spec. Exact namespace verification detects missing, duplicate, and orphaned jobs without treating unrelated customer jobs as drift.
- `files`: committed source path → deployment-root-relative target path.
- `jobs`: stable name, normalized schedule, and command. The raw command stays in the committed spec; the generated provenance manifest stores only SHA-256.

Managed roots must not overlap. Every target must be inside one managed root. Every managed job name must start with `jobNamespace`.

## Capture

Run after the implementation commit is final and the working tree is clean. Write the manifest outside the source Repository or into a release artifact location so the new file does not make the source dirty.

```bash
python3 scripts/deployment_provenance.py capture \
  --repo /path/to/canonical-repo \
  --spec deployment/spec.json \
  --output /path/to/deployment-provenance.json
```

The manifest records:

- canonical credential-free `origin` URL;
- full 40-character Git commit;
- spec path and SHA-256;
- source/target path, Git mode, bytes, and SHA-256 for each deployed file;
- managed job name, schedule, and command SHA-256.

It does not record local Repository paths, deployment absolute paths, or raw scheduler commands.

## Scheduler inventory

Provide JSON shaped like `examples/scheduler-inventory.example.json`:

```json
{
  "schema": "openclaw-scheduler-inventory-v1",
  "jobs": [
    {
      "name": "ansai:example:daily-check",
      "schedule": "15 5 * * *",
      "command": "python3 skills/example-managed/check.py"
    }
  ]
}
```

Treat this inventory as temporary sensitive operational data because it contains raw commands. Do not commit it. The verifier hashes commands locally and never echoes raw command text in its result or mismatch errors.

## Verify

```bash
python3 scripts/deployment_provenance.py verify \
  --manifest /path/to/deployment-provenance.json \
  --deployment-root /path/to/client/deployment-root \
  --scheduler-inventory /path/to/read-only-scheduler-inventory.json
```

Verification is read-only and fails closed on:

- file missing, extra file under a managed root, content hash drift, or executable-mode drift;
- symlink or special file under a managed root;
- missing, orphaned, or duplicate job inside the managed namespace;
- schedule or command-hash drift;
- malformed or secret-bearing provenance fields.

## Recovery decision

- `verified`: deployed files and managed jobs match the canonical commit.
- `blocked`: preserve the evidence and prepare a human-reviewed reconciliation plan.
- Never auto-delete an extra file/job or overwrite a drifted file. A mismatch can represent an emergency client patch, malicious change, or a stale deployment; ownership must be decided first.
