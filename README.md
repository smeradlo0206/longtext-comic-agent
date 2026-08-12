# Longtext Comic Agent — StoryBible Curator

长文本多 Agent 连续漫画生成系统。StoryBible Curator 是系统的核心 Agent，负责从源文本中提取人物、组织、地点和状态，生成候选提案（Proposal），经人工审批后写入正式 StoryBible。

## 环境要求

- Python 3.12+
- uv（推荐）或 pip

```bash
uv sync
```

## 配置 .env

在项目根目录创建 `.env` 文件：

```
LLM_BASE_URL=https://api.llm.ustc.edu.cn/v1
LLM_API_KEY=你的密钥
STORYBIBLE_MODEL=deepseek-v4-pro
LLM_TIMEOUT_SECONDS=120
```

为减小 LLM 调用延迟，关闭 VPN 通常可以直接连接。

## 启动服务

### 本地开发（SQLite）

```bash
$env:DATABASE_URL="sqlite+pysqlite:///./comic_agent.db"
uv run uvicorn comic_agent.main:app --host 127.0.0.1 --port 8000 --log-level debug
```

浏览器访问 Swagger 文档：http://127.0.0.1:8000/docs

### Docker（PostgreSQL + Redis + MinIO）

```bash
cp .env.example .env
docker compose up -d postgres redis minio
uv run uvicorn comic_agent.main:app --reload
```

## API 端点总览

### 基础

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/health` | 健康检查 |
| `POST` | `/projects` | 创建项目 |
| `POST` | `/projects/{project_id}/documents/import` | 导入 TXT 文档 |
| `GET` | `/projects/{project_id}/chapters` | 列出章节 |
| `GET` | `/chapters/{chapter_id}/chunks` | 列出章节下的文本块 |
| `GET` | `/chunks/{chunk_id}` | 查询单个文本块 |

### Mock Event（无需 LLM）

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/chunks/{chunk_id}/mock-event` | 生成确定性 Mock EventProposal |
| `GET` | `/chunks/{chunk_id}/event-proposals` | 列出 chunk 的事件提案 |
| `GET` | `/event-proposals/{proposal_id}` | 查询单个事件提案 |
| `GET` | `/chunks/{chunk_id}/agent-runs` | 列出 chunk 的 Agent 运行记录 |
| `GET` | `/agent-runs/{agent_run_id}` | 查询单个 Agent 运行记录 |

### StoryBible Curator（需要 LLM）

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/projects/{project_id}/storybible/curate` | 提交上下文，LLM 生成候选提案 |
| `POST` | `/projects/{project_id}/storybible/commit-plans/{plan_id}` | 审批并提交候选计划 |
| `GET` | `/projects/{project_id}/storybible/profiles` | 列出正式人物/组织/地点 |
| `GET` | `/projects/{project_id}/storybible/profiles/{profile_id}` | 查询单个 profile |
| `GET` | `/projects/{project_id}/storybible/profiles/{profile_id}/states` | 查询 profile 的状态历史 |
| `GET` | `/projects/{project_id}/storybible/profiles/{profile_id}/states?event_id=X` | 按事件筛选状态 |

## StoryBible Curator 工作流

```
导入 TXT → 获取 chunk_id → 调用 curate → 审查候选 → 审批提交 → 查询正式资源
```

### 1. 创建项目

```powershell
$project = @{
    id = "demo-story"
    name = "Demo Story"
    project_type = "LONG_NOVEL"
    fidelity_mode = "CANON_STRICT"
    output_format = "PAGES"
    reading_direction = "LTR"
    allow_new_events = $false
    allow_new_dialogue = $false
    allow_event_reordering = $false
    allow_visual_compression = $true
    allow_dialogue_splitting = $false
    require_source_traceability = $true
    max_auto_repairs = 2
} | ConvertTo-Json

Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/projects" `
  -ContentType "application/json" -Body $project
```

### 2. 导入 TXT 并获取 chunk_id

```powershell
# 导入 TXT 文件
curl.exe -X POST "http://127.0.0.1:8000/projects/demo-story/documents/import" `
  -F "file=@E:\study\3spring\demo.txt;type=text/plain"

# 获取 chunk_id
$chapters = Invoke-RestMethod "http://127.0.0.1:8000/projects/demo-story/chapters"
$chunks = Invoke-RestMethod "http://127.0.0.1:8000/chapters/$($chapters[0].chapter_id)/chunks"
$chunkId = $chunks[0].chunk_id
```

### 3. 调用 StoryBible Curator

```powershell
$context = @{
    project_id = "demo-story"
    source_chunk_ids = @($chunkId)
} | ConvertTo-Json

$proposal = Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8000/projects/demo-story/storybible/curate" `
  -ContentType "application/json" -Body $context
```

返回的 `StoryBibleCuratorProposalV1` 包含：
- `status`: 始终为 `CANDIDATE`（不会直接写入正式数据）
- `commit_plan.updates`: 识别出的人物 (PERSON)、组织 (ORGANIZATION)、地点 (LOCATION) 及状态
- 每条记录都带有 `evidence_refs` 追溯源文本

### 4. 审批前检查

```powershell
# 审批前正式资源应为空
Invoke-RestMethod "http://127.0.0.1:8000/projects/demo-story/storybible/profiles"
# 预期: []
```

### 5. 审批并提交

```powershell
$planId = $proposal.commit_plan.commit_plan_id
Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8000/projects/demo-story/storybible/commit-plans/$planId" `
  -ContentType "application/json" -Body '{"status":"APPROVED"}'
```

重复提交相同审批返回相同结果（幂等），不会产生重复资源。

### 6. 查询正式资源

```powershell
# 列出所有 profiles
Invoke-RestMethod "http://127.0.0.1:8000/projects/demo-story/storybible/profiles"

# 查询单个 profile
Invoke-RestMethod "http://127.0.0.1:8000/projects/demo-story/storybible/profiles/prof_linxia"

# 查询某 profile 的状态
Invoke-RestMethod "http://127.0.0.1:8000/projects/demo-story/storybible/profiles/prof_linxia/states"

# 按事件过滤状态
Invoke-RestMethod "http://127.0.0.1:8000/projects/demo-story/storybible/profiles/prof_linxia/states?event_id=event-a"
```

## 架构说明

- **`comic_agent/schemas/`** 是所有 schema 的唯一权威来源，`StrictBaseModel` 拒绝未声明的字段（`extra="forbid"`）
- **Agent 只输出 Proposal**，不直接写入正式数据
- **`CommitService`** 是正式 StoryBible 数据的唯一写入入口
- **`StoryBibleCurator`** 接收 `StoryBibleContextV1`（API 端自动将 `source_chunk_ids` 解析为文本注入 prompt），输出 `StoryBibleCuratorProposalV1`
- **`StoryBibleValidator`** 在写入前验证所有 `evidence_refs` 的 `quote_text` 精确匹配源文本
- **`EvidenceRefV1`** 必填字段仅 `chunk_id`，可选 `quote_start`/`quote_end`/`quote_text`。建议只提供 `chunk_id` + `quote_text`（精确子串即可通过验证）
- **所有资源 ID 必须带项目前缀**，格式 `{project_id}:{short_id}`，如 `demo-story:prof_linxia`。Curator prompt 已要求模型遵守此规则，以确保跨项目全局唯一
- Curator prompt 内嵌完整 JSON Schema，确保不同 LLM 模型都能输出符合预期的结构
- 单元测试使用 Mock providers 和本地 SQLite，不依赖真实模型 API

## 开发命令

```bash
uv sync
uv run ruff check .
uv run mypy comic_agent
uv run pytest -p no:cacheprovider
uv run python scripts/export_json_schemas.py
```

## 错误排查

| 症状 | 可能原因 | 检查方法 |
|------|---------|---------|
| `api_key_loaded=False` | `.env` 不在 worktree 根目录，或变量名不对 | `python -c "from comic_agent.config import Settings; s=Settings(); print(bool(s.llm_api_key.get_secret_value()))"` |
| `ReadTimeout` | LLM 响应超时 | 增加 `LLM_TIMEOUT_SECONDS=120` 或以上；检查网络/VPN |
| `ValidationError: Extra inputs not permitted` | 模型输出字段与 schema 不匹配 | 查看服务端 traceback，通常是 prompt 未包含 schema 或字段名不对 |
| `EvidenceRef quote_text does not match` | 模型生成的 quote_text 与源文本不精确匹配 | 检查 prompt 是否强调精确复制；确认模型未改写原文 |
| `401 / 403` | API 密钥无效或权限不足 | 检查 `LLM_API_KEY` 和模型访问权限 |
| `400 / 404` | Base URL 或模型名错误 | 确认 `LLM_BASE_URL` 包含 `/v1`，`STORYBIBLE_MODEL` 正确 |
| `PytestCacheWarning / WinError 5` | Windows 临时目录权限 | 添加 `--basetemp=./.pytest_tmp` |
| `canonical resource id already belongs to another project` | 模型生成短 ID 跨项目冲突 | 检查所有 ID 是否带 `{project_id}:` 前缀；清 DB 重试 |
| 500 Internal Server Error | 服务端异常 | 查看 uvicorn 窗口的 traceback |
