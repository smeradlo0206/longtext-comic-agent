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
- is available through the unified NarrativeAnalyst workflow/API/web console
  entrypoints.

## Current Implementation

Implemented:

- `comic_agent/agents/entity_extraction.py`;
- `ENTITY_EXTRACTION_SYSTEM_PROMPT`;
- `EntityExtractionAgent.spec`;
- `EntityExtractionAgent.run(input_context) -> EntityProposalV1`;
- fake provider tests in `tests/test_entity_extraction_agent.py`;
- dry-run / real opt-in smoke path in `scripts/smoke_real_entity_agent.py`;
- unified NarrativeAnalyst mode execution in `scripts/smoke_narrative_analyst.py`;
- internal console endpoint
  `POST /projects/{project_id}/agent-runs/narrative-analyst`;
- `web_console/index.html` Narrative Analyst Console mode selector;
- smoke-script regression tests in `tests/test_real_entity_smoke.py`.

The prompt asks for exactly one source-grounded entity and requires conservative
handling of names, aliases, entity type, and evidence quotes.

## Prompt Hardening

The v0.1 prompt is now strengthened around:

- output boundary: only `EntityProposalV1`, no Event, Claim, KnowledgeState, or
  canonical StoryBible data;
- entity type decision labels: `CHARACTER`, `LOCATION`, `ORGANIZATION`,
  `OBJECT / PROP`, `ABILITY / TECHNIQUE`, and `CONCEPT / WORLD_RULE`;
- selection strategy: choose one specific reusable entity that affects later
  story understanding, not ordinary nouns, actions, event results, or claims;
- `canonical_name`: source-supported, short, stable, and not invented or expanded;
- `aliases`: explicit aliases or forms of address only; inferred aliases and
  descriptions are rejected;
- `EvidenceRefV1`: shortest exact quote, no paraphrase, with optional char range
  only when confident;
- no step-by-step reasoning, no candidate lists, and no explanations.

## Test Status

Automatic tests use a fake provider only. They cover:

- provider call wiring;
- `EntityProposalV1` return validation;
- prompt boundaries and forbidden output types;
- entity type decision labels;
- canonical name and aliases anti-invention rules;
- exact quote and no-paraphrase requirements;
- no step-by-step reasoning and no candidate list rules;
- bounded proposal-only `AgentSpec`;
- TXT import and idempotency dry-run;
- `ContextBuilder` selected chunk wiring;
- blocked real-run behavior when `ENABLE_REAL_LLM=false`;
- sanitized success and failure smoke summaries.

The smoke summary is intentionally sanitized. It records counts, ids, ranges,
hashes, model/provider labels, schema status, evidence audit status, proposal id,
entity type, canonical name, aliases count, first evidence chunk id, quote match,
char-range match, sanitized provider diagnostics, and token counts when present.
It does not write canonical StoryBible data and does not include source text,
quote text, aliases, API keys, raw provider responses, or `message.content`.

The unified NarrativeAnalyst API/console summary for `entity_extraction`
includes only sanitized mode-specific fields:

```text
proposal_id
entity_type
canonical_name
aliases_count
confidence
evidence_chunk_id
quote_matched
char_range_matched
```

The full Proposal JSON may be shown in the console's collapsible Proposal area
for the user's manual evaluation. Do not commit or paste Proposal quotes,
complete source text, raw provider responses, or API keys.

## Manual Real Eval Status

Latest sanitized manual real LLM results:

- dry-run: passed.
- model: `deepseek-v4-pro`.
- output schema: `EntityProposalV1`.
- 1 chunk real eval: passed.
- 2 chunk real eval: passed.
- 3 chunk real eval: passed.
- provider success: true.
- schema validation passed: true.
- evidence validation passed: true.
- quote matched: true.
- char-range match may be null when `quote_start` and `quote_end` are omitted.
- observed entity types include `CHARACTER` and `ORGANIZATION`.
- canonical name was non-empty.
- aliases count was 0 in these tests.

Conclusion: `EntityExtractionAgent` v0.1 real evaluation has passed up to
3 chunks with `deepseek-v4-pro`.

## Manual Real Eval Commands

Recommended manual sequence:

1. 1 chunk real eval.
2. 2 chunk real eval.
3. 3 chunk real eval.

Each run should record only sanitized status fields such as schema validity,
evidence validity, quote match, entity type quality, canonical name quality, and
overall pass/fail.

Manual quality checklist:

```text
is_entity
entity_type_correct
canonical_name_correct
evidence_supports_entity
salient_entity
manual_score
manual_issue
```

Prompt triage hints:

- aliases invented: tighten aliases rules;
- canonical_name too long or invented: tighten canonical_name rules;
- wrong entity_type: update the type decision table;
- `quote_matched=false`: tighten exact quote and no-paraphrase rules;
- event or claim extracted as entity: tighten mode boundary and selection rules.

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
