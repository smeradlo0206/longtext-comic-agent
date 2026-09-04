# Longtext Comic Agent — StoryBible Curator

长文本多 Agent 连续漫画生成系统。StoryBible Curator 是系统的核心 Agent，负责从源文本中提取人物、组织、地点和状态，生成候选提案（Proposal），经人工审批后写入正式 StoryBible。

## 环境要求

- Python 3.12+
- uv（推荐）或 pip

```bash
uv sync
```

## 当前流程

```text
TXT（最多 120,000 字符）
  -> Gate 1 文本审查
  -> SourceDocument / Chapter / Chunk（稳定 ID 与字符偏移）
  -> Narrative / Timeline / StoryBible（可选真实 Provider）
  -> ComicPlanningService -> PanelPlanningService
  -> ComicPlanStoryboardAdapter（或离线 LongTextStoryboardAgent）
  -> PageSpec / PanelSpec + EvidenceRef（逐字证据）
  -> PromptSpec（此处才绑定 local-flux2-klein）
  -> 一个跨页 WorkflowJob 入队
  -> GPU worker 只加载一次 FLUX.2
  -> 已审核 canonical 素材策略校验
  -> 先为每个角色生成一次统一彩色身份锚点
  -> 每个 panel 使用身份锚点、场景参考和独立 seed 单独生图
  -> 单格视觉 QA；失败时只重绘该格
  -> 从原文提取对白并在无字底图副本上排版气泡
  -> 每 6 张按 3x2 拼成 page-001.png、page-002.png ...
```

## 配置 .env

在项目根目录创建 `.env` 文件：

```
LLM_BASE_URL=https://api.llm.ustc.edu.cn/v1
LLM_API_KEY=你的密钥
STORYBIBLE_MODEL=deepseek-v4-pro
LLM_TIMEOUT_SECONDS=120
TIMELINE_LLM_ENABLED=false
TIMELINE_MODEL=deepseek-v4-pro
TIMELINE_LLM_TIMEOUT_SECONDS=60
TIMELINE_LLM_MAX_RETRIES=1
```

`TIMELINE_LLM_ENABLED=false` keeps Timeline analysis in safe rule-only mode. Set it
to `true` only after supplying a local `LLM_API_KEY`; the Timeline model can then be
changed through `TIMELINE_MODEL` without changing application code.

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

---

# FLUX.2 生图流程 Agent

这是一个只使用 `black-forest-labs/FLUX.2-klein-4B` 的本地生图流程。工作区中的唯一参考素材位于 `inputs/references/`；旧模型脚本、旧参考素材和旧输出不参与当前流程。

流程固定为：

```text
用户选择 JSON（StoryboardRequest）
  -> 分镜 Agent 只引用锁定的 asset_id / slot / role
  -> 分镜任务 JSON（WorkflowJob）
  -> 校验交接字段、参考图清单与文件哈希
  -> 原子写入剧情生图队列
  -> GPU worker 按优先级领取任务并复用已加载模型
  -> 编译漫画风格首句和带编号的多参考图提示词
  -> 按连续性依赖生成关键帧和派生镜头并有限重试
  -> 按故事顺序保存单张 PNG、自动拼图和 result.json
```

## 目录

```text
configs/                 任务配置
inputs/references/       已登记参考图及 manifest.json
src/flux2_agent/         流程实现
tests/                   无 GPU 测试
queue/                   运行时任务状态，不纳入版本管理
runs/                    运行时自动创建，不纳入版本管理
```

每张图片都有稳定 `asset_id`：原始微信图片沿用 `wechat-001` 形式，普通上传图片使用 `asset-001` 形式。重新登记时已有 ID 保持不变。用户选择层再为它绑定 `entity_id`、`slot` 和 `role`；人物名仅可作为 `display_name`，不用于视觉身份绑定。一个镜头选择 1 至 4 张图片。Agent 不允许传任意文件路径，也不会自动读取其他目录中的图片。

## 安装

建议在有 NVIDIA GPU、CUDA 12.8 和至少约 24 GiB 显存的 Linux 节点运行：

```bash
bash scripts/install.sh
source .venv/bin/activate
```

首次运行会从 Hugging Face 下载模型权重，所需空间以模型仓库当前版本为准。若模型需要授权，先执行 `huggingface-cli login`。

## 使用

先查看参考图清单并验证任务：

```bash
flux2-agent references
flux2-agent validate configs/example.json \
  --selection configs/example-selection.json
flux2-agent run configs/example.json \
  --selection configs/example-selection.json \
  --dry-run
```

在 GPU 上生成：

```bash
flux2-agent run configs/example.json \
  --selection configs/example-selection.json
```

指定已下载的本地模型并禁止联网：

```bash
flux2-agent run configs/example.json \
  --selection configs/example-selection.json \
  --model-path /models/FLUX.2-klein-4B \
  --offline
```

每次运行默认写入当前工作区下的 `runs/<job-id>-<UTC时间>/`。实际使用的参考图会以 `reference-<ID>.<扩展名>` 复制到该目录根层，与最终 PNG 放在同一个文件夹中，便于直接对比。`request.json` 是输入快照，`plan.json` 是实际提示词、引用关系和执行顺序，`result.json` 记录参考图副本、连续性来源、seed、耗时、模型来源和图片路径。配置 `contact_sheet` 后，流程会在全部单张成功时按 `shots` 的故事顺序自动拼图。运行失败时也会保留参考图与错误信息，便于定向重试；仍可用 `--output-root` 显式指定其他目录。

## 剧情生图队列

上游分镜 Agent 的输出契约就是 `WorkflowJob`。可直接获取当前版本的 JSON Schema：

```bash
flux2-agent queue schema > workflow-job.schema.json
```

上游可提交文件，也可通过标准输入把 JSON 直接送入队列。`job_id` 同时作为队列幂等键，同一个 ID 不能重复提交；`priority` 数字越小越先执行：

```bash
flux2-agent queue submit configs/morning-tea-storyboard.json --priority 20
cat configs/campus-sunset-walk.json \
  | flux2-agent queue submit - --priority 50
```

一次性排空当前队列：

```bash
flux2-agent queue worker \
  --model-path ./models/FLUX.2-klein-4B \
  --offline
```

作为持续运行的 GPU worker：

```bash
comic-agent --workspace . run \
  examples/morning-tea-novella.txt \
  --request configs/longtext-morning-tea.json \
  --compile-only
```

使用上游 Comic Planning 的 `panels.json` 进入同一条本地生图链路：

```bash
uv run python scripts/run_comic_demo.py \
  --input examples/morning-tea-novella.txt \
  --output-dir runs/planning \
  --provider-mode deterministic

comic-agent --workspace . run-planned \
  examples/morning-tea-novella.txt \
  --panels runs/planning/<demo-run-id>/panels.json \
  --request configs/longtext-morning-tea.json \
  --model-path ./models/FLUX.2-klein-4B \
  --offline
```

`run-planned` 从 `PanelPlanV1.project_id` 派生项目 ID，并逐项复核 `EvidenceRefV1` 的 chunk、
字符范围和原文。请求中的角色素材 `entity_id` 必须覆盖规划结果的 `character_ids`；这是人工
审核 StoryBible 角色与 canonical 参考资产映射的位置。规划 schema 保持 provider-neutral，
只有随后生成的 `PromptSpecV1` 和 `WorkflowJob` 才绑定本地 FLUX.2。

恢复或单独启动 worker：

```bash
comic-agent --workspace . worker \
  --model-path ./models/FLUX.2-klein-4B \
  --offline \
  --watch \
  --poll-interval 2
```

worker 按 `priority -> enqueued_at -> job_id` 排序领取任务。模型路径、设备和 dtype 相同的连续任务共用一次模型加载；每个任务仍独立编译计划、seed、尺寸和输出目录。队列状态写在 `queue/` 的 `pending/running/succeeded/failed/cancelled` 子目录，领取和迁移均加文件锁并使用原子重命名。

所有运行结果只写到当前工作区的 `runs/<comicrun-id>-<UTC时间>/`。其中包含原始参考图副本、
彩色身份锚点、独立 panel PNG、`page-*.png`、`chapter-overview.png`、`request.json`、`plan.json`、
`lettered-*.png`、`production-manifest.json` 和 `result.json`。被 QA 淘汰的候选以
`qa-rejected-*.png` 保留供审核。项目不会创建或使用 `output/` 目录。
每个运行目录强制使用 `0700` 权限，目录内参考图、生成图和 JSON 强制使用 `0600`，避免同一
服务器上的其他用户读取或修改本次任务资产。

查询和故障处理：

```bash
flux2-agent queue list
flux2-agent queue list --status failed
flux2-agent queue status morning-tea-storyboard-v11
flux2-agent queue retry morning-tea-storyboard-v11
flux2-agent queue cancel waiting-job
flux2-agent queue recover
```

`retry` 保留此前尝试历史；`recover` 把 worker 异常退出时留下的 `running` 任务重新放回队列。提交时仍可加 `--selection`，在入队前锁定剧本、角色、场景和质量约束。默认生成结果仍只进入当前工作区的 `runs/`，不会使用 `output` 目录。

## 连续分镜

独立镜头即使共用角色图和风格提示词，也会因为每次扩散抽样而发生脸型、服装、机位和场景漂移。当前流程使用“主关键帧 -> 派生镜头”的有向依赖来减少这种漂移：

```json
{
  "contact_sheet": {"columns": 3, "filename": "storyboard-2x3.png"},
  "shots": [
    {"shot_id": "01-before", "continuity_from": "02-keyframe", "references": []},
    {
      "shot_id": "02-keyframe",
      "references": [
        {
          "slot": "CHAR_A",
          "asset_id": "asset-001",
          "role": "character_identity",
          "purpose": "角色身份"
        }
      ]
    },
    {"shot_id": "03-after", "continuity_from": "02-keyframe", "references": []}
  ]
}
```

## 两种规划模式

- `DETERMINISTIC_EXTRACTIVE`：当前可离线跑通的模式。按原文顺序均匀选择句子，保留精确
  `quote_start`、`quote_end` 和 `quote_text`，不会捏造事件。它可靠但不具备复杂文学理解。
- `LLM_PROPOSAL`：schema 已保留，但只有显式配置 storyboard Provider 后才允许使用。现有上游
  Narrative LLM 可以做实体、事件和时间线分析，尚不能直接替代完整的视觉分镜 Agent。

`identity_anchor_mode=AUTO` 会先把线稿角色标准化为一张彩色全身锚点，后续所有单人和多人镜头都
引用同一锚点。panel 使用独立 seed，以免上一帧姿势压制当前原文动作；场景参考和角色锚点负责稳定
视觉身份。实测已能在起床、行走、单人喝茶、双人坐下和对谈之间保持主要发型、发色、服装与体型。

FLUX.2 Klein 本身没有持久角色 ID 或参考图权重，因此生产项目仍应先人工审核自动锚点。对面部细节
要求严格时，应冻结 StoryBible/VisualBible，并进一步使用角色 LoRA 或人脸/视觉语义评分器。当前
版本已经实现客观视觉 QA 和失败单格重绘，但不会把配色相似度冒充精确的人脸身份判断。

## 素材库、QA 与 60 秒指标

生产参考图采用“候选 -> 人工审核 -> canonical 冻结”的素材包模式。每个实体与用途只有一个
canonical 基准，姿势、表情、服装等作为已审核非 canonical 变体保存。文件哈希变化会自动撤销
审核状态。单格 SLA、各阶段耗时、QA 报告、修复记录和气泡字层均写入 `result.json`，成功的
API/CLI 生产任务也会返回 `performance` 摘要。

具体审核命令、指标口径、人工作业边界和字体配置见
[docs/production_quality.md](docs/production_quality.md)。

## 开发验证

```bash
pytest
 ruff check .
 mypy comic_agent
 python scripts/export_json_schemas.py
```

示例只展示字段关系；没有 `continuity_from` 的根镜头必须至少提供一张静态参考图。被依赖的镜头会先生成，其成图作为子镜头最后一张参考图；`plan.json` 的 `execution_order` 记录真实生成顺序，而最终单张命名、`result.json` 和拼图都保持原始故事顺序。

- 每个镜头最多向一个已确认镜头声明 `continuity_from`。
- 连续性成图占用一个参考位，因此子镜头最多再使用 3 张静态参考图。
- `continuity_crop` 可用 0 到 1 的 `left/top/right/bottom` 从关键帧裁出单个人物，换场或减少演员时用它只传递彩色身份。
- 派生镜头可将 `references` 设为空，只使用已确认的彩色锚点，避免原始线稿与最终角色设计互相冲突；没有 `continuity_from` 的根镜头仍必须提供静态参考。
- 流程拒绝不存在的镜头 ID、循环依赖和超过 4 张总参考图的配置。
- 优先选择能同时稳定主要人物、服装和场景的双人中景作为主关键帧，再向相邻动作派生。
- 整张成图只适合在场景和演员集合兼容的镜头间传递；换场或减少演员时应断开依赖，继续使用静态角色参考，避免把父镜头的构图和额外人物带入。
- `continuity_from` 提高一致性，但不等于身份锁定；需要更强控制时，应在此工作流上增加角色 LoRA 和姿态/深度控制。

## Agent 交接

`configs/example-selection.json` 是传给分镜 Agent 的锁定输入：

- `comic_style` 是全部分镜共用的漫画风格，编译后固定为生图提示词首句。
- `selected_assets` 是用户选中的资料库句柄，包含 `asset_id`、`entity_id`、`slot` 和 `role`。
- `display_name` 只供界面和剧本展示，编译器不会把它当成身份提示。

`configs/example.json` 是分镜 Agent 输出、生图 Agent 输入：

- `source_script`、`comic_style`、`global_prompt`、`quality_constraints` 和 `selected_assets` 必须与锁定输入完全一致。
- `shots[].prompt` 用 `CHAR_A`、`SCENE_A` 等槽位描述画面，编译器会替换为“图1中的角色”等模型指令。
- `shots[].references` 只能引用 `selected_assets` 白名单，`role` 和槽位也必须一致。
- `shots[].continuity_from` 可引用另一个镜头的成图，运行器会按依赖顺序执行并把该图自动绑定到最后一个 Image 编号。
- `contact_sheet` 可指定最终拼图列数与 PNG 文件名；拼图只组合单独生成的镜头，不让模型直接绘制多格图。
- `quality_constraints` 只写正向保持项，不使用独立负面提示词。
- `generation.seed` 是首个 seed，后续镜头与重试使用确定性偏移。

运行时 `--selection` 会阻止分镜 Agent 替换用户锁定的角色、场景、风格或质量约束。

不要把全部参考图塞进单次生成。先为每张图确定用途，每个镜头只选真正相关的参考图，静态图与连续性图合计最多 4 张，能减少显存压力和参考信息互相污染。
