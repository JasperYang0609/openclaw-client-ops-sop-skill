# Idempotency Patterns

## Stable keys

Use stable keys before writes:

- Notion: database/page title + date + source ID/link + client slug.
- Files: deterministic path under `records/<client_slug>/` plus date/version.
- Scheduler/Cron: exact stable job name inside an owned namespace, plus normalized schedule and command hash; never description text alone.
- Discord: channel ID/thread ID + message source ID; avoid display names.
- RLS/member records: Discord/OpenClaw sender ID + department + role.

## Create-or-update pattern

1. Search for the stable key.
2. If exactly one match exists, update/append according to the task.
3. If no match exists, create.
4. If multiple matches exist, stop and ask or produce a merge plan.

## Report wording

- `created`: new artifact made.
- `updated`: existing artifact reused.
- `skipped`: artifact already satisfied acceptance criteria.
- `blocked`: ambiguous duplicate or unsafe state found.

## Deployment provenance

Before treating a local script or scheduler job as managed, bind it to a committed deployment spec and provenance manifest. Search the exact managed target and job name first. Extra or duplicate managed entries are `blocked`, not candidates for silent deletion.
