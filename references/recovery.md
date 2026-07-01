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
