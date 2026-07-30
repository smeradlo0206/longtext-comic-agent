# Real LLM Setup

This page documents the phase-one preparation for calling a real OpenAI-compatible
LLM provider. The default behavior remains safe: real LLM calls are disabled
unless both environment configuration and an explicit smoke-script flag opt in.

## Supported Provider Shape

Phase one uses an OpenAI-compatible chat completions interface:

- base URL: `LLM_BASE_URL`
- model name: `LLM_MODEL`
- API key: `LLM_API_KEY`, with `OPENAI_API_KEY` accepted as a fallback
- endpoint: `{LLM_BASE_URL}/chat/completions`
- transport: `httpx`

The current default values are:

```text
ENABLE_REAL_LLM=false
LLM_PROVIDER_NAME=ustc-openai-compatible
LLM_BASE_URL=https://api.llm.ustc.edu.cn/v1
LLM_MODEL=deepseek-v4-pro
LLM_TIMEOUT_SECONDS=60
LLM_MAX_OUTPUT_TOKENS=2000
```

If the platform authorizes multiple models, `LLM_MODEL` can be switched without
code changes. Examples include `deepseek-v4-pro`, `qwen3.6-chat`, or other
models listed by the authorized platform. The selected value must match the
provider portal exactly.

## Local Secret File

Create a local `.env` file in the repository root. Do not commit it.

```text
ENABLE_REAL_LLM=false
LLM_PROVIDER_NAME=ustc-openai-compatible
LLM_BASE_URL=https://api.llm.ustc.edu.cn/v1
LLM_MODEL=deepseek-v4-pro
LLM_API_KEY=replace-with-local-key
LLM_TIMEOUT_SECONDS=60
LLM_MAX_OUTPUT_TOKENS=2000
```

Security rules:

- never paste a real API key into code, tests, docs, issues, screenshots, or PRs;
- never print the API key in logs;
- rotate the key immediately if it is exposed publicly;
- keep `.env`, `local_eval/`, `output/`, and `tmp/` untracked.

## Minimal Real Event Agent

The minimal real agent skeleton is `EventExtractionAgent`. It reads bounded
`SourceChunkV1` context and may only output `EventProposalV1`. It does not write
canonical story data.

The workflow wrapper is `RealEventWorkflow`:

- uses `ContextBuilder` instead of direct full-database reads;
- records `AgentRunV1` and `ProviderResultV1`;
- validates proposal `EvidenceRefV1` against source chunks through
  `CommitService`;
- saves failures as auditable failed agent runs;
- does not store the API key in payloads.

## Dry Run

Before any model call, run the real novel baseline evaluation. It imports the
local TXT, checks idempotency, verifies `ContextBuilder`, and writes sanitized
summary files:

```powershell
uv run python scripts/evaluate_real_novel_base.py `
  --txt-path local_eval/novel_excerpt.txt `
  --metadata-path local_eval/novel_metadata.json `
  --output-dir output/evaluations
```

The real Event agent smoke script can also be run without calling a real model:

```powershell
uv run python scripts/smoke_real_event_agent.py `
  --txt-path local_eval/novel_excerpt.txt `
  --output-dir output/evaluations
```

Dry-run output includes only sanitized metadata: counts, ids, ranges, hashes,
configuration status, and whether the real model was called. It does not include
source text or the API key.

## Real Call Opt-In

Only run a real call after confirming the local key and model configuration.
Both switches are required:

```text
ENABLE_REAL_LLM=true
```

and:

```powershell
uv run python scripts/smoke_real_event_agent.py `
  --txt-path local_eval/novel_excerpt.txt `
  --output-dir output/evaluations `
  --enable-real-llm
```

If `--enable-real-llm` is passed while `ENABLE_REAL_LLM=false`, the script records
that the run was blocked and does not call the provider.

## Current Boundary

Implemented:

- OpenAI-compatible provider adapter skeleton;
- minimal Event extraction agent;
- real Event workflow wrapper with audit persistence;
- dry-run smoke script;
- real long-novel baseline evaluation script;
- tests for settings, provider parsing/errors, agent behavior, workflow behavior,
  smoke-script safety, and sanitized long-novel evaluation.

Not implemented:

- real Claim or KnowledgeState extraction workflows;
- canonical story fact commits from LLM output;
- prompt tuning for production extraction quality;
- retry/backoff policy;
- streaming;
- provider registry;
- image generation.
