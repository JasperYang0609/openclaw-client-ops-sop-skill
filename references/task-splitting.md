# Heavy Task Splitting

## Decision

Split a task when a failed retry could create duplicates, expose data, or leave customer-visible half-finished output.

## Standard run plan

1. Scope: state the exact artifact(s) to create or update.
2. Inventory: list current pages, databases, files, cron jobs, channels, and IDs.
3. Duplicate check: search stable keys before every create.
4. Single write step: perform only one class of write.
5. Verification: inspect count, sample rows, links, permissions, or output files.
6. Persist: update state/memory/issue ledger with what was actually done.
7. Report: say `done`, `partial`, or `blocked`; include evidence path.

## Acceptance criteria template

- Structure exists exactly once.
- Required fields/properties are present.
- Sample data can be read back.
- Permissions are no broader than intended.
- User-facing report states any partial/deferred items.
