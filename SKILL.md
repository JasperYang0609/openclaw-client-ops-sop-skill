---
name: openclaw-client-ops-sop
description: Run, recover, review, or harden client-facing OpenClaw operations where long AI tasks create Notion databases, mirror data, write reports, send Discord messages, use Claude API, or maintain customer knowledge. Use for client incident reviews, heavy task splitting, idempotency checks, partial execution recovery, Claude overloaded/rate-limit triage, canonical Discord recipient rules, customer issue ledgers, and post-failure continuation SOPs.
---

# OpenClaw Client Ops SOP

Use this skill when a client deployment needs reliable operations, not only a one-off answer.

## Core rule

Never retry a failed heavy operation blindly.

For any task that may create, modify, mirror, publish, notify, or archive customer data:

1. Define the intended end state.
2. Check the current state before acting.
3. Execute one bounded step.
4. Verify the side effect.
5. Persist progress.
6. Report partial completion honestly.

## Trigger patterns

Use this skill for requests like:

- “客戶最近問題整理 / review / 優化”
- “這個任務做到一半失敗，幫我續”
- “Agent couldn't generate a response; some tool actions may have executed”
- “Notion DB 建到一半 / 鏡像資料半成品”
- “AI service temporarily overloaded”
- “Ambiguous Discord recipient”
- “幫客戶建立穩定 SOP / 問題台帳 / 導入防呆”

## Heavy-task split

Classify a task as heavy if it includes any two or more of:

- creates a database, page, folder, role, schedule, or integration
- writes more than one external system
- mirrors or migrates data
- performs multi-file analysis
- sends notifications to multiple people/channels
- uses long-running model/tool calls
- changes client permissions, RLS, or data visibility

For heavy tasks, use one step per turn/run:

1. Plan and acceptance criteria.
2. Preflight inventory and duplicate check.
3. Create or update structure.
4. Verify structure.
5. Write or mirror data.
6. Verify counts and samples.
7. Analyze.
8. Report with evidence and next step.

Read `references/task-splitting.md` when designing the run plan.

## Recovery after interrupted execution

If a tool/model run failed after possible side effects:

1. Stop. Do not rerun the original command/prompt.
2. List intended side effects.
3. Inspect each target system for actual side effects.
4. Mark each item: `done`, `partial`, `missing`, `duplicate`, `unsafe`.
5. Continue only from the first safe missing/partial step.
6. If external writes are ambiguous, ask before modifying.

Read `references/recovery.md` for the full checklist.

## Idempotency requirements

Before creating customer-facing resources, always search by stable keys:

- Notion database/page: title + source meeting/date + client/project slug
- Discord message/thread: channel ID + thread ID + source item ID/date
- file output: deterministic path + version/date suffix
- memory record: dated heading + source artifact path
- cron job: exact job name
- RLS/member row: canonical user ID, not display name

If found, update or append only when safe. If not found, create once.

Read `references/idempotency.md` for examples.

## Repo-backed deployment provenance

When client-local scripts or enabled scheduler jobs need reliability work, do not patch the live machine first. Establish an owned canonical Repository and a versioned deployment spec, then capture a provenance manifest from a clean committed HEAD.

Use `scripts/deployment_provenance.py` to record credential-free repository URL, full Git commit, spec hash, deployed-file hashes/modes, and managed scheduler job hashes. Use only a client-approved **read-only scheduler inventory** as verifier input. The tool must not install files, read/write crontab, edit scheduler state, or delete drifted resources.

Rules:

1. Block capture if the Repository is dirty, has untracked files, or a source is not a regular tracked file at HEAD.
2. Keep target paths relative to a declared managed root; keep scheduler ownership inside a stable job namespace.
3. Never persist raw scheduler commands in the generated manifest. Never persist tokens, credentials, client absolute paths, or private keys.
4. Verify exact managed file/job sets plus SHA-256 and executable mode. Missing, extra, duplicate, symlinked, or drifted items are blockers.
5. A mismatch creates a reconciliation plan, not an automatic repair. Ask before client deployment, scheduler edits, deletion, or restart.

Read `references/deployment-provenance.md` for the contract and examples.

## Discord recipient governance

Do not send client messages by display name or nickname when the recipient matters.

Use canonical targets:

- user mention: `<@USER_ID>`
- channel mention: `<#CHANNEL_ID>`
- tool target: `channel:ID` where supported
- role mention: `<@&ROLE_ID>` only when explicitly approved

If a user ID is missing, mark `pending_id` and do not rely on the name for permissions or sensitive notifications.

## Claude API overload triage

Treat `The AI service is temporarily overloaded. Please try again in a moment.` as likely provider capacity, especially with Claude API / Anthropic.

Standard handling:

1. Check whether Gateway/Discord is otherwise healthy.
2. Look for `529`, `overloaded_error`, `rate_limit`, `anthropic`, or failover messages near the timestamp.
3. Retry with exponential backoff for transient overload.
4. Reduce concurrent heavy model calls.
5. Use a configured fallback model when user experience matters.
6. Do not claim local bug unless local health checks fail.

Read `references/claude-overload.md` for customer-facing wording and escalation criteria.

## Client incident ledger

For every recurring or customer-visible issue, record:

- date/time and reporter
- symptom and exact error text
- affected channel/system/model
- severity: P1/P2/P3
- root cause confidence: confirmed/probable/unknown
- immediate fix
- prevention / skill or config update
- evidence path or log path
- owner and next review date

Use `scripts/generate_issue_entry.py` to create a Markdown issue entry template.


## Client-visible status updates

For client deployments, progress/status UI should reassure the client that the assistant is alive and working. Every assistant turn must send at least one `status_update_ui` card when the UI tool is available, including short tasks and pure-text turns. Keep each card short, specific, and safe. Do not reduce updates to generic “processing” messages.

Use event-based updates when any of these change:

- phase: preflight, diagnosis, execution, verification, recovery, handoff
- blocker or risk: permission, billing, model/runtime, missing ID, ambiguous target, partial side effect
- strategy: switching model, retrying with backoff, splitting task, moving from write to verify
- confidence: confirmed root cause vs probable vs unknown
- next action: what will be checked or changed next

Good update shape:

`狀態更新：目前在<階段/動作>；發現/卡點是<可公開事實>；思路變更是<策略或風險摘要>；下一步<具體驗證/處理>。`

Rules:

- Keep updates short, concrete, and Traditional Chinese by default for Jasper/Anan/client Discord contexts.
- Include current phase, key evidence, risk/change, and next step.
- Do not expose chain-of-thought, secrets, raw tokens, API keys, private local paths, or full commands unless explicitly needed and safe.
- Do not spam fixed heartbeats inside the same turn; however, every assistant turn must include at least one concise status card.
- For long waits inside one turn, update every 20–30 seconds if still waiting or the blocker changed.
- For customer-facing incidents, name the impact plainly and separate confirmed facts from assumptions.
- Final report still needs evidence: validation result, artifact/log path, before/after state, or explicit blocker.

Client quality bar:

- Weak: `處理中`
- Better: `狀態更新：目前在檢查 Discord 投遞層；模型已能產生回覆，但公開訊息未送出；下一步確認 channel 權限與 thread 狀態。`
- Best: `狀態更新：目前在比對模型與投遞層；已確認 Claude CLI 可回、Discord 手動送訊可達，所以問題縮小到 inbound activation；下一步用明確任務句測觸發規則。`

## Evidence standards

Final reports should include concise evidence:

- log path or artifact path
- validation command/result
- before/after state
- remaining risk or blocker

Do not paste large logs into chat. Summarize and keep full logs in files.

## Bundled resources

- `references/task-splitting.md` — heavy task run plan and acceptance criteria.
- `references/recovery.md` — partial execution recovery checklist.
- `references/idempotency.md` — stable keys and duplicate prevention examples.
- `references/claude-overload.md` — Claude API overload/rate-limit triage.
- `references/deployment-provenance.md` — clean-Git provenance and read-only deployment/scheduler drift checks.
- `examples/deployment-spec.example.json` — versioned deployment contract example.
- `examples/scheduler-inventory.example.json` — read-only scheduler inventory shape.
- `scripts/deployment_provenance.py` — capture deterministic manifests and verify drift without mutating clients.
- `scripts/generate_issue_entry.py` — prints a customer issue ledger entry template.
- `scripts/post_run_check.py` — dependency-free maintainer validation.
