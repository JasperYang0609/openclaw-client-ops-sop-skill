# Claude API Overload / Rate-Limit Triage

## Common signals

- `The AI service is temporarily overloaded. Please try again in a moment.`
- HTTP `529`
- `overloaded_error`
- `rate_limit_error`
- Anthropic responses during dense consecutive tasks

## Diagnosis order

1. Confirm whether local Gateway and channel are healthy.
2. Check timestamp-adjacent logs for provider overload/rate-limit.
3. Check whether the workload triggered many dense model calls.
4. Check Anthropic usage tier, rate limits, and concurrent request volume if available.

## Mitigation

- Retry after 1–5 minutes for isolated incidents.
- Use exponential backoff for automated retries.
- Queue dense tasks instead of running them concurrently.
- Configure fallback model when customer experience requires continuity.
- For repeated failures, reduce prompt/tool payload size and split tasks.

## Customer-facing wording

「這次不是你操作錯，錯誤比較像 Claude API 服務商端短暫容量不足或請求太密集。請先等 1–5 分鐘重試；如果連續發生，我們會幫你加上重試間隔與備援模型，避免工作中斷。」
