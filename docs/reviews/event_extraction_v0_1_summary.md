# EventExtractionAgent V0.1 Summary

Last updated: 2026-07-31

## Scope

`EventExtractionAgent` v0.1 is the first real LLM event-extraction path for
Phase 1. It remains bounded and proposal-only:

- reads selected `SourceChunkV1` context through `ContextBuilder`;
- calls external models only through the `LLMProvider` interface;
- outputs only `EventProposalV1`;
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

## Recommended Manual Eval Settings

```text
ENABLE_REAL_LLM=true only during manual eval
LLM_PROVIDER_NAME=ustc-openai-compatible
LLM_BASE_URL=https://api.llm.ustc.edu.cn/v1
LLM_MODEL=deepseek-v4-pro
LLM_RESPONSE_FORMAT=
LLM_TIMEOUT_SECONDS=240
LLM_MAX_OUTPUT_TOKENS=3000
```

`LLM_RESPONSE_FORMAT=json_object` remains supported by code, but is not
recommended for the current USTC 3 chunk eval because the provider may return
missing content with reasoning metadata or time out.

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
