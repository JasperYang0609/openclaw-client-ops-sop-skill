# Partial Execution Recovery

Use when a model/tool run stopped after possible side effects.

## Recovery checklist

1. Capture the original goal and timestamp.
2. List expected side effects.
3. Inspect target systems read-only first.
4. Build a status table:
   - expected item
   - current evidence
   - status: done / partial / missing / duplicate / unsafe
   - safe next action
5. Continue only from missing or partial items.
6. If duplicate items exist, do not delete until the user approves.
7. If sensitive permissions changed, escalate before further writes.

## Stop conditions

Stop and ask before continuing when:

- permissions/RLS may be too broad
- multiple possible duplicates exist
- customer-visible messages may be resent
- live data could be overwritten
- external API write outcome cannot be confirmed
## Local scripts or scheduler drift

If a client-local script or enabled job differs from the expected implementation:

1. Freeze writes; do not overwrite the file or recreate/delete the job.
2. Identify the owned canonical Repository and full expected commit. If none exists, mark `canonical_unknown` and hold implementation changes.
3. Capture or locate the provenance manifest generated from a clean committed Repository.
4. Export scheduler state through an approved read-only adapter into the inventory JSON contract. Do not use this skill to read or write crontab/scheduler configuration directly.
5. Run the read-only provenance verifier. Preserve only redacted mismatch evidence; do not preserve raw secret-bearing commands.
6. Classify each mismatch as expected emergency patch, stale deployment, ambiguous ownership, or suspected tamper.
7. Prepare a reviewed deploy/rollback plan. Ask before client file writes, job edits/deletion, restart, or notification.

A failed verification is not permission to “fix” production automatically.
