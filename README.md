# Longtext Comic Agent

长文本多 Agent 连续漫画生成系统的启动阶段工程脚手架。

本仓库当前实现的是第一阶段闭环：创建项目、导入 TXT、识别章节、生成 SourceChunk、写入数据库、查询章节和 chunk、用 Mock Provider 生成可验证 Proposal。真实 LLM、真实图片 API、完整漫画生成和完整前端都不在本阶段范围内。

## Quick Start

```bash
uv sync
uv run uvicorn comic_agent.main:app --reload
```

API:

- `GET /health`
- `POST /projects`
- `POST /projects/{project_id}/documents/import`
- `GET /projects/{project_id}/chapters`
- `GET /chapters/{chapter_id}/chunks`
- `GET /chunks/{chunk_id}`
- `GET /projects/{project_id}/agent-runs`
- `POST /projects/{project_id}/agent-runs/mock-event`
- `GET /agent-runs/{agent_run_id}`
- `GET /agent-runs/{agent_run_id}/evidence`
- `GET /settings/llm/status`
- `GET /demo/status`
- `POST /demo/verify-access`
- `POST /projects/{project_id}/agent-runs/real-event`
- `POST /projects/{project_id}/agent-runs/narrative-analyst`

Website-ready audit surfaces:

- AgentRun list
- AgentRun detail
- Evidence audit
- LLM status
- Sanitized real eval summary
- Narrative Analyst Console for `event_extraction`, `entity_extraction`, and
  `claim_extraction`

Internal hosted demo console:

- Open `web_console/index.html` in a browser.
- Start the API with `uv run uvicorn comic_agent.main:app --reload`.
- TXT import recognizes common webnovel headings such as `正文 第一章 ...`,
  `楔子`, `卷一 ...`, and `第一回 ...`.
- TXT import also splits overlong webnovel paragraphs into sentence-aware chunks
  capped around 1200 characters for stable agent evaluation.
- Local demo access does not require an access code by default. For a shared
  hosted demo, set `INTERNAL_DEMO_REQUIRE_ACCESS_CODE=true` and configure
  `INTERNAL_DEMO_ACCESS_CODE` in local environment only.
- Real Event and Narrative Analyst real calls use the server-side configured
  provider key and still require both `ENABLE_REAL_LLM=true` and an explicit
  request-level opt-in.
- The Narrative Analyst Console can show full Proposal JSON for manual review,
  but it does not show API keys, raw provider responses, complete source chunk
  text, or canonical story-data writes.
- `event_extraction` now returns `EventProposalBatchV1`; timeline and downstream
  consumers should read event proposals from `proposal.events[]`.
- `entity_extraction` now returns `EntityProposalBatchV1`; downstream consumers
  should read entity proposals from `proposal.entities[]`.
- `claim_extraction` now returns `ClaimProposalBatchV1`; downstream consumers
  should read claim proposals from `proposal.claims[]`.
- New `claim_extraction` outputs use Claim schema version `1.2`: current
  `claim_type` values are `FACTUAL_ASSERTION`, `BELIEF`, `HYPOTHESIS`, `DENIAL`,
  `ACCUSATION`, `MEMORY`, `EVALUATION`, `INTERPRETATION`, `PREDICTION`, and
  `COMMITMENT`, and every claim includes `temporal_scope`. `FACTUAL_ASSERTION`
  is reserved for direct unhedged statements, rather than a fallback for guesses,
  beliefs, evaluations, or interpretations. Legacy `ASSERTION` is read-only for
  historical `schema_version="1.0"` payloads; v1.1 claim payloads remain readable.
- Current recommended real model for Narrative Analyst extraction smoke tests is
  `deepseek-chat`. Keep `deepseek-v4-pro` for later Continuity Timeline style
  reasoning tests rather than the default extraction path.
- In the Narrative Analyst Console, explicitly select 1-3 chunks before every
  run. The browser does not rely on an empty Chunk IDs field plus
  chunk_offset/chunk_limit, because that can accidentally reuse older chunks in
  a reused project.
- For manual tests with a different TXT, prefer a fresh `project_id`, then click
  View Chapters, select the intended chunks, and verify the Selected input
  chunks preview before running. Full Proposal evidence quotes should match the
  selected input chunks.
- The demo does not expose KnowledgeState, multi-agent orchestration, or
  canonical StoryBible writes.

## 项目文档

- [文档索引](docs/README.md)
- [领域词汇表 V1](docs/domain_glossary.md)
- [领域业务规则 V1](docs/domain_rules.md)
- [完整流水线示例](docs/examples/story_pipeline_example.md)

## Docker Compose

```bash
cp .env.example .env
docker compose up -d postgres redis minio
uv run uvicorn comic_agent.main:app --reload
```

To run the API inside Compose:

```bash
docker compose up --build api
```

## Development Commands

```bash
uv sync
uv run ruff check .
uv run mypy comic_agent
uv run pytest
uv run python scripts/export_json_schemas.py
docker compose config
```

## Architecture Notes

- `comic_agent/schemas` is the only source of schema truth.
- Agents output Proposal models only.
- `CommitService` is the only promotion gate for canonical story data.
- `PanelSpecV1` is provider-neutral; provider-specific prompt data belongs in `PromptSpecV1`.
- Unit tests use Mock providers and local SQLite, never real model APIs.
