# Event Extraction 3 Chunk Evaluation Template

Use this template after manually running the real LLM smoke evaluation on the
campus network. Paste only sanitized fields back into Codex.

## Current Manual Findings

- 1 chunk real evaluation passed with `deepseek-v4-pro`.
- 2 chunk real evaluation passed with `deepseek-v4-pro`,
  `LLM_MAX_OUTPUT_TOKENS=3000`, and `LLM_TIMEOUT_SECONDS=240`.
- 3 chunk real evaluation passed with `deepseek-v4-pro` and
  `LLM_RESPONSE_FORMAT` disabled.
- `LLM_RESPONSE_FORMAT=json_object` remains supported by code, but it is not
  recommended for current USTC 3 chunk eval because the provider may return
  `content=None` with `reasoning_content` or time out.

Conclusion: `EventExtractionAgent` v0.1 real eval passed up to 3 chunks.
Current recommended model: `deepseek-v4-pro`.

This readiness pass reduces the event-agent LLM context by sending only
`chunk_id`, `chapter_id`, `char_start`, `char_end`, and `text` for each selected
chunk. It also asks the provider for direct final JSON, no reasoning, concise
summary text, event count based on actual story events rather than chunk count,
and the shortest exact supporting quote for each event.

## Manual Command

```powershell
cd D:\107
$env:UV_CACHE_DIR = 'D:\107\tmp\uv-cache'
$env:ENABLE_REAL_LLM = 'true'
$env:LLM_PROVIDER_NAME = 'ustc-openai-compatible'
$env:LLM_BASE_URL = 'https://api.llm.ustc.edu.cn/v1'
$env:LLM_MODEL = 'deepseek-v4-pro'
$env:LLM_RESPONSE_FORMAT = ''
$env:LLM_MAX_OUTPUT_TOKENS = '3000'
$env:LLM_TIMEOUT_SECONDS = '240'
uv run python scripts/smoke_real_event_agent.py `
  --txt-path local_eval/console_smoke_xuanhuan.txt `
  --output-dir output/evaluations `
  --chunk-limit 3 `
  --enable-real-llm
```

## Automatic Sanitized Fields

```text
project_id
dry_run
real_llm_requested
real_llm_enabled
real_llm_called
provider_name
model
chunks_count
selected_chunks_count
selected_chunk_ids
context_chunk_ids
import_idempotent
agent_run_saved
agent_run_id
agent_run_status
evidence_validation_passed
error_message
provider_result_id
provider_success
output_schema
schema_validation_passed
proposal_id
batch_id
events_count
event_proposal_ids
primary_event_type
primary_event_summary
event_evidence_results
confidence
actor_resolution_status
evidence_chunk_id
quote_matched
char_range_matched
provider_error_diagnostics
finish_reason
response_has_choices
choices_count
message_keys
content_type
content_length
has_reasoning_content
has_tool_calls
usage_prompt_tokens
usage_completion_tokens
usage_total_tokens
```

## Human Quality Scores

Use `true`, `false`, or `unknown`. Do not include source text or long quotes.

```text
schema_valid
evidence_valid
quote_exact
char_range_exact
actor_resolution_correct
summary_fidelity
events_cover_major_plot_points
event_count_reasonable
no_duplicate_events
no_invention
every_event_has_supporting_evidence
event_summaries_supported_by_quotes
overall_pass
quality_notes_without_source_quotes
```

## Current V0.1 Conclusion Summary

```text
EventExtractionAgent v0.1 real eval passed up to 3 chunks.
event_extraction now returns EventProposalBatchV1 with events[].
3 chunk passed with deepseek-v4-pro and LLM_RESPONSE_FORMAT disabled.
Current recommended USTC real eval settings:
ENABLE_REAL_LLM=true only during manual eval
LLM_PROVIDER_NAME=ustc-openai-compatible
LLM_BASE_URL=https://api.llm.ustc.edu.cn/v1
LLM_MODEL=deepseek-v4-pro
LLM_RESPONSE_FORMAT=
LLM_TIMEOUT_SECONDS=240
LLM_MAX_OUTPUT_TOKENS=3000
```

## Do Not Paste

```text
.env
API key
API key prefix
API key suffix
API key length
key_status
complete chunk text
real novel text
long quote_text
message.content
raw provider response
reasoning_content text
tool call arguments
output/*.sqlite
output/*.db
local_eval/*
local_web_console/*
tmp/*
Panabit/*
```

## Review Questions

- Did the model return one `EventProposalBatchV1` with 1 or more events?
- Does `events[]` cover the major plot points without mechanically matching
  chunk count?
- If one chunk has multiple events, did the model include multiple event
  proposals?
- If multiple chunks narrate one continuous event, did the model avoid
  duplicating it?
- Did each summary describe one event from the selected chunks?
- Did the model avoid inventing characters, locations, dialogue, motives, or
  causal explanations?
- If the actor was uncertain, did it use `UNKNOWN` or `UNRESOLVED` instead of
  forcing a participant id?
- Did every event have EvidenceRef support, and did aggregate `quote_matched`
  and `char_range_matched` pass?
- If the run failed, did `finish_reason`, token usage, and content diagnostics
  indicate timeout, max output length, schema failure, or an unsupported content
  shape?
- Is any failure message sanitized and free of secrets or source text?
