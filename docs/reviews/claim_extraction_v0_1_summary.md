# ClaimExtractionAgent V0.1 Summary

Last updated: 2026-08-03

## Scope

`ClaimExtractionAgent` v0.1 is the third implemented Narrative Analyst mode. It
is a bounded proposal-only agent:

- reads selected `SourceChunkV1` context from caller-provided `input_context`;
- calls external models only through the `LLMProvider` interface;
- outputs only `ClaimProposalV1`;
- requires at least one `EvidenceRefV1`;
- does not write canonical StoryBible data;
- does not add or modify schemas.

## Current Implementation

Implemented:

- `comic_agent/agents/claim_extraction.py`;
- `CLAIM_EXTRACTION_SYSTEM_PROMPT`;
- `ClaimExtractionAgent.spec`;
- `ClaimExtractionAgent.run(input_context) -> ClaimProposalV1`;
- `NarrativeAnalyst` registry entry with `status="implemented"`;
- fake provider tests in `tests/test_claim_extraction_agent.py`;
- NarrativeAnalyst routing tests in `tests/test_narrative_analyst.py`;
- unified smoke path in `scripts/smoke_narrative_analyst.py`.

The prompt asks for exactly one source-grounded claim and keeps claim extraction
separate from event and entity extraction.

## Test Status

Automatic tests use fake providers only. They cover:

- provider call wiring;
- `ClaimProposalV1` return validation;
- prompt boundaries for claims, events, entities, evidence, conservative
  verification, and StoryBible exclusion;
- bounded proposal-only `AgentSpec`;
- `NarrativeAnalyst.run("claim_extraction", input_context)` routing;
- planned modes remaining not implemented;
- sanitized smoke dry-run and fake real-run summaries.

No real LLM evaluation has been executed for this mode yet.

## Manual Real Eval

Recommended manual sequence:

1. dry-run with `--mode claim_extraction`;
2. 1 chunk real eval;
3. 2 chunk real eval;
4. 3 chunk real eval.

Dry-run command:

```powershell
uv run python scripts/smoke_narrative_analyst.py `
  --mode claim_extraction `
  --txt-path local_eval/claim_smoke.txt `
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
uv run python scripts/smoke_narrative_analyst.py `
  --mode claim_extraction `
  --txt-path local_eval/claim_smoke.txt `
  --output-dir output/evaluations `
  --chunk-limit 1 `
  --enable-real-llm
```

If the 1 chunk run passes, repeat with `--chunk-limit 2` and
`--chunk-limit 3`. The provider is called only when both `ENABLE_REAL_LLM=true`
and `--enable-real-llm` are set.

## Safety Boundary

Do not paste or commit:

- `.env`;
- API keys or key fragments;
- real source text or long quotes;
- `claim_text` from real source;
- raw provider responses;
- `message.content`;
- local evaluation outputs;
- database files.
