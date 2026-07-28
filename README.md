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
