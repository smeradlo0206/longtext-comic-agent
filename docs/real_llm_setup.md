# Real LLM Setup

This page documents the phase-one preparation for calling a real OpenAI-compatible
LLM provider. The default behavior remains safe: real LLM calls are disabled
unless both environment configuration and an explicit smoke-script flag opt in.

## Supported Provider Shape

Phase one uses an OpenAI-compatible chat completions interface:

- base URL: `LLM_BASE_URL`
- model name: `LLM_MODEL`
- optional JSON output mode: `LLM_RESPONSE_FORMAT`
- API key: `LLM_API_KEY`, with `OPENAI_API_KEY` accepted as a fallback
- endpoint: `{LLM_BASE_URL}/chat/completions`
- transport: `httpx`

The current default values are:

```text
ENABLE_REAL_LLM=false
LLM_PROVIDER_NAME=ustc-openai-compatible
LLM_BASE_URL=https://api.llm.ustc.edu.cn/v1
LLM_MODEL=deepseek-v4-pro
LLM_RESPONSE_FORMAT=
LLM_TIMEOUT_SECONDS=60
LLM_MAX_OUTPUT_TOKENS=2000
```

If the platform authorizes multiple models, `LLM_MODEL` can be switched without
code changes. Examples include `deepseek-v4-pro`, `qwen3.6-chat`, or other
models listed by the authorized platform. The selected value must match the
provider portal exactly.

For the current USTC `deepseek-v4-pro` evaluation path, the recommended local
configuration is:

```text
ENABLE_REAL_LLM=true
LLM_PROVIDER_NAME=ustc-openai-compatible
LLM_BASE_URL=https://api.llm.ustc.edu.cn/v1
LLM_MODEL=deepseek-v4-pro
LLM_RESPONSE_FORMAT=
LLM_TIMEOUT_SECONDS=240
LLM_MAX_OUTPUT_TOKENS=3000
LLM_API_KEY=replace-with-local-key
```

Use `ENABLE_REAL_LLM=true` only during manual evaluation. The committed default
remains `ENABLE_REAL_LLM=false`, and the smoke script still requires the
explicit `--enable-real-llm` flag before it can call a provider.

`LLM_RESPONSE_FORMAT=json_object` remains supported: when set, the
OpenAI-compatible request includes `response_format: {"type": "json_object"}`.
For the current USTC 3 chunk evaluation, leave `LLM_RESPONSE_FORMAT` empty.
Manual results showed that `json_object` can produce `content=None` with
`reasoning_content` or can time out on the 3 chunk path.

## Local Secret File

Create a local `.env` file in the repository root. Do not commit it.

```text
ENABLE_REAL_LLM=false
LLM_PROVIDER_NAME=ustc-openai-compatible
LLM_BASE_URL=https://api.llm.ustc.edu.cn/v1
LLM_MODEL=deepseek-v4-pro
LLM_RESPONSE_FORMAT=
LLM_API_KEY=replace-with-local-key
LLM_TIMEOUT_SECONDS=240
LLM_MAX_OUTPUT_TOKENS=3000
```

Security rules:

- never paste a real API key into code, tests, docs, issues, screenshots, or PRs;
- never print the API key in logs;
- rotate the key immediately if it is exposed publicly;
- keep `.env`, `local_eval/`, `output/`, `local_web_console/`, `tmp/`, and
  `Panabit/` untracked.

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
- does not store the API key in payloads;
- sends slim real-event LLM context: each selected chunk includes only
  `chunk_id`, `chapter_id`, `char_start`, `char_end`, and `text`.

## Manual Real Event Status

Latest sanitized campus-network manual results for `EventExtractionAgent` v0.1:

- 1 chunk with `deepseek-v4-pro`: passed. AgentRun succeeded, provider succeeded,
  schema validation passed, evidence validation passed, quote matched, and
  `char_range_matched` was null.
- 2 chunks with `deepseek-v4-pro`: `LLM_RESPONSE_FORMAT=json_object` first failed
  with `finish_reason=length` and `content=None`; after setting
  `LLM_MAX_OUTPUT_TOKENS=3000` and `LLM_TIMEOUT_SECONDS=240`, it passed with
  schema, evidence, quote, and char-range validation.
- 3 chunks with `deepseek-v4-pro`: `LLM_RESPONSE_FORMAT=json_object` timed out
  before and after prompt/payload compression. With `LLM_RESPONSE_FORMAT` unset,
  the 3 chunk run passed with schema, evidence, quote, and char-range validation.

Conclusion: `EventExtractionAgent` v0.1 real evaluation has passed up to
3 chunks. The current recommended model is `deepseek-v4-pro`.

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
  --output-dir output/evaluations `
  --chunk-limit 3
```

Dry-run output includes only sanitized metadata: counts, ids, ranges, hashes,
and whether the real model was called. It does not include source text, the API
key, or API-key status details such as key length.

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
  --chunk-limit 3 `
  --enable-real-llm
```

Recommended manual 3 chunk command:

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
uv run python scripts/smoke_real_event_agent.py `
  --txt-path local_eval/console_smoke_xuanhuan.txt `
  --output-dir output/evaluations `
  --chunk-limit 3 `
  --enable-real-llm
```

If `--enable-real-llm` is passed while `ENABLE_REAL_LLM=false`, the script records
that the run was blocked and does not call the provider.

After a manual campus-network run, paste only sanitized fields back into Codex.
Use `docs/reviews/event_extraction_eval_template.md` as the checklist. Do not
paste `.env`, API keys, complete chunk text, real novel text, long quotes, raw
provider response, `message.content`, `reasoning_content` text, tool call
arguments, or API-key status details.

## Website-Ready API Surface

No committed frontend exists in this repository yet. A future website can attach
to the existing backend audit APIs without reading local ignored folders:

- `GET /projects/{project_id}/agent-runs`
- `GET /agent-runs/{agent_run_id}`
- `GET /agent-runs/{agent_run_id}/evidence`
- `GET /settings/llm/status`

Recommended website views:

- AgentRun list page.
- AgentRun detail page.
- ProviderResult status display.
- EvidenceRef audit display.
- Three-chunk evaluation sanitized summary display.
- `quote_matched` and `char_range_matched` display.
- LLM configuration status page that never displays the API key.

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
