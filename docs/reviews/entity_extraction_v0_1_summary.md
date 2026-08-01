# EntityExtractionAgent V0.1 Summary

Last updated: 2026-08-01

## Scope

`EntityExtractionAgent` v0.1 is the second Narrative Analyst mode. It is a
bounded proposal-only agent:

- reads selected `SourceChunkV1` context from caller-provided `input_context`;
- calls external models only through the `LLMProvider` interface;
- outputs only `EntityProposalV1`;
- requires at least one `EvidenceRefV1`;
- does not write canonical StoryBible data;
- does not implement workflow, API, or web console entrypoints.

## Current Implementation

Implemented:

- `comic_agent/agents/entity_extraction.py`;
- `ENTITY_EXTRACTION_SYSTEM_PROMPT`;
- `EntityExtractionAgent.spec`;
- `EntityExtractionAgent.run(input_context) -> EntityProposalV1`;
- fake provider tests in `tests/test_entity_extraction_agent.py`;
- dry-run / real opt-in smoke path in `scripts/smoke_real_entity_agent.py`;
- smoke-script regression tests in `tests/test_real_entity_smoke.py`.

The prompt asks for exactly one source-grounded entity and requires conservative
handling of names, aliases, entity type, and evidence quotes.

## Test Status

Automatic tests use a fake provider only. They cover:

- provider call wiring;
- `EntityProposalV1` return validation;
- prompt boundaries and forbidden output types;
- bounded proposal-only `AgentSpec`;
- TXT import and idempotency dry-run;
- `ContextBuilder` selected chunk wiring;
- blocked real-run behavior when `ENABLE_REAL_LLM=false`;
- sanitized success and failure smoke summaries.

No real LLM evaluation has been executed for this mode yet.

The smoke summary is intentionally sanitized. It records counts, ids, ranges,
hashes, model/provider labels, schema status, evidence audit status, proposal id,
entity type, canonical name, aliases count, first evidence chunk id, quote match,
char-range match, sanitized provider diagnostics, and token counts when present.
It does not write canonical StoryBible data and does not include source text,
quote text, aliases, API keys, raw provider responses, or `message.content`.

## Pending Manual Real Eval

Recommended manual sequence:

1. 1 chunk real eval.
2. 2 chunk real eval.
3. 3 chunk real eval.

Each run should record only sanitized status fields such as schema validity,
evidence validity, quote match, entity type quality, canonical name quality, and
overall pass/fail.

Dry-run command:

```powershell
uv run python scripts/smoke_real_entity_agent.py `
  --txt-path local_eval/entity_smoke.txt `
  --output-dir output/evaluations `
  --chunk-limit 3
```

Recommended manual real-eval command after local secret setup:

```powershell
cd D:\107
$env:ENABLE_REAL_LLM = 'true'
$env:LLM_PROVIDER_NAME = 'ustc-openai-compatible'
$env:LLM_BASE_URL = 'https://api.llm.ustc.edu.cn/v1'
$env:LLM_MODEL = 'deepseek-v4-pro'
$env:LLM_RESPONSE_FORMAT = ''
$env:LLM_TIMEOUT_SECONDS = '240'
$env:LLM_MAX_OUTPUT_TOKENS = '3000'
$env:UV_CACHE_DIR = 'D:\107\tmp\uv-cache'
uv run python scripts/smoke_real_entity_agent.py `
  --txt-path local_eval/entity_smoke.txt `
  --output-dir output/evaluations `
  --chunk-limit 1 `
  --enable-real-llm
```

If the 1 chunk run passes, repeat with `--chunk-limit 2` and then
`--chunk-limit 3`. The provider is called only when both `ENABLE_REAL_LLM=true`
and `--enable-real-llm` are set.

## Safety Boundary

Do not paste or commit:

- `.env`;
- API keys or key fragments;
- real source text or long quotes;
- raw provider responses;
- `message.content`;
- local evaluation outputs;
- database files.
