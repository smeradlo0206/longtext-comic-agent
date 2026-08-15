# EventExtractionAgent V0.1 Summary

Last updated: 2026-07-31

## Scope

`EventExtractionAgent` v0.1 is the first real LLM event-extraction path for
Phase 1. It remains bounded and proposal-only:

- reads selected `SourceChunkV1` context through `ContextBuilder`;
- calls external models only through the `LLMProvider` interface;
- outputs only `EventProposalBatchV1`, with 1 or more `EventProposalV1` records
  in `events[]`;
- does not write canonical StoryBible data;
- validates evidence through `CommitService` in `RealEventWorkflow`;
- records auditable `AgentRunV1` and `ProviderResultV1` data.

The real-event LLM context is intentionally slim. Each selected chunk sent to
the provider includes only:

```text
chunk_id
chapter_id
char_start
char_end
text
```

It does not send extraction-irrelevant fields such as `document_id`, `checksum`,
storage URI, or timestamps.

## Manual Real Eval Result

Sanitized campus-network manual evaluation results:

- 1 chunk with `deepseek-v4-pro`: passed. AgentRun succeeded, provider
  succeeded, schema validation passed, evidence validation passed, quote matched,
  and `char_range_matched` was null.
- 2 chunks with `deepseek-v4-pro`: `LLM_RESPONSE_FORMAT=json_object` first failed
  with `finish_reason=length` and missing content. With
  `LLM_MAX_OUTPUT_TOKENS=3000` and `LLM_TIMEOUT_SECONDS=240`, it passed with
  schema, evidence, quote, and char-range validation.
- 3 chunks with `deepseek-v4-pro`: `LLM_RESPONSE_FORMAT=json_object` timed out
  before and after prompt/payload compression. With `LLM_RESPONSE_FORMAT` unset,
  it passed with schema, evidence, quote, and char-range validation.

Conclusion: `EventExtractionAgent` v0.1 real eval passed up to 3 chunks.

Current output contract: `event_extraction` always returns
`EventProposalBatchV1`. The `events[]` count follows actual story events, not
chunk count. One chunk may yield multiple events, while several chunks may yield
one continuous event. Timeline and downstream agents should consume
`proposal.events[]`.

## Recommended Manual Eval Settings

```text
ENABLE_REAL_LLM=true only during manual eval
LLM_PROVIDER_NAME=ustc-openai-compatible
LLM_BASE_URL=https://api.llm.ustc.edu.cn/v1
LLM_MODEL=deepseek-v4-pro
LLM_RESPONSE_FORMAT=
LLM_TIMEOUT_SECONDS=240, or 360 for slow long-text 3 chunk runs
LLM_MAX_OUTPUT_TOKENS=3000
```

`LLM_RESPONSE_FORMAT=json_object` remains supported by code, but is not
recommended for the current USTC 3 chunk eval because the provider may return
missing content with reasoning metadata or time out.

## Long-Text 3 Chunk Notes

Sanitized long-text smoke observations:

- Some 3 chunk offsets can fail with `finish_reason=length`, missing final
  content, `has_reasoning_content=true`, and high prompt/completion token usage.
- Nearby offsets can still pass with schema validation, evidence validation, and
  quote matching, which indicates the agent/provider/evidence pipeline is usable.
- Some long-text offsets can time out.

Recommended long-text command shape:

```powershell
uv run python scripts/smoke_narrative_analyst.py `
  --mode event_extraction `
  --txt-path local_eval/console_smoke_xuanhuan.txt `
  --output-dir output/evaluations `
  --chunk-limit 3 `
  --chunk-offset 0 `
  --max-chars-per-chunk 1200 `
  --enable-real-llm
```

`--max-chars-per-chunk` trims only the provider input context and leaves stored
`SourceChunkV1` records unchanged. If the provider exceeds max output tokens
before final JSON content, first reduce `--max-chars-per-chunk` or try another
`--chunk-offset`. Do not paste or commit local source text, evidence quotes, raw
provider responses, `message.content`, or reasoning text.

## Safety Rules

Do not paste or commit:

- `.env`;
- API keys or key fragments;
- real novel text or long quotes;
- raw provider responses;
- `message.content`;
- reasoning content text;
- tool call arguments;
- `local_eval/`, `output/`, `local_web_console/`, `tmp/`, `Panabit/`, `*.db`, or
  `*.sqlite`.

Use `docs/reviews/event_extraction_eval_template.md` for future sanitized
manual-evaluation reports.

## Manual Evidence Alignment

`quote_matched=true` only proves that each `EvidenceRefV1.quote_text` exists in
the selected chunk. Human review must also check whether each quote fully
supports its event summary.

For batch review, score whether `events[]` covers the major plot points, whether
the event count is reasonable, whether duplicate or invented events appear, and
whether every event has supporting evidence. For each event, verify that the
quote directly supports every actor, action, object, and outcome named in
`summary`. If the quote supports only part of the proposed event, mark the item
as partial and keep `manual_score <= 4`. If the summary merges adjacent events,
such as an action plus a later explanation, announcement, or reaction, record
`manual_issue` and treat the proposal as needing prompt or selection review.

## Website-Ready Audit APIs

A future committed website can consume the existing backend audit APIs:

- `GET /projects/{project_id}/agent-runs`
- `GET /agent-runs/{agent_run_id}`
- `GET /agent-runs/{agent_run_id}/evidence`
- `GET /settings/llm/status`

Suggested views:

- AgentRun list;
- AgentRun detail;
- ProviderResult status;
- EvidenceRef audit;
- sanitized real eval summary;
- LLM status without API key display.
