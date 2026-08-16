# StoryBible Curator — Agent 说明文档

> 本文档面向两类读者:① 要**调用**这个 Agent 的其他模块(分镜、合并层、编排脚本);
> ② 要**修改**这个 Agent 的开发者。先读"分工"和"关键语义",再看契约和调用方式。

## 1. 它是干什么的

StoryBible Curator 维护一本**全过程存在的"故事状态账本"**(StoryBible):

- 人物 / 地点 / 组织是谁、有什么属性;
- **从哪个事件开始生效**的状态(穿着、持有物、位置、伤势、环境状况……);
- 人物/组织之间的关系(时间有界);
- 世界规则(全天候生效的设定)。

它解决的核心问题是:**图像模型前后画出来的人物/环境不一致**。分镜 agent 画每一格前,
从账本按"此刻"取一份合并快照,人物穿什么、背景什么状态,永远有据可查。

### 三兄弟分工(重要,不要越界)

| 模块 | 职责 | 产出 |
|------|------|------|
| narrative-analysis(他人维护) | 记录**这一章发生了什么** | entity / event / claim / state-change 提案 |
| timeline(他人维护) | 记录**这些事谁先谁后** | `TemporalRelationProposalV1`(成对 BEFORE/AFTER 关系) |
| **storybible-curator(本 Agent)** | 记录**这一刻人物和世界是什么状态** | 状态库(profile/state/relationship/world-rule)+ 时刻快照 |
| 分镜 agent(他人维护) | 用合并后的信息设计画面并出图 | 分镜/画面 |

**本 Agent 不做**:不自行提取时间线(只消费 timeline 的关系输出盖序)、不写分镜、
不做叙事解析。状态一旦入账,**跨章节自动继承**:第 5 章没提衣服,第 1 章定了,
查第 5 章的时刻照样返回第 1 章的衣服。

## 2. 模块地图(改哪里)

| 文件 | 作用 | 什么时候改 |
|------|------|-----------|
| `comic_agent/schemas/storybible.py` | 全部契约:Pydantic 是唯一 schema 权威来源 | 改输入/输出结构时 |
| `comic_agent/agents/storybible_curator.py` | Curator 本体:prompt、输出 JSON Schema、确定性后处理 | 改提示词/后处理规则时 |
| `comic_agent/services/storybible_event_order.py` | 消费 timeline 关系 → 盖 `valid_from_order`/`valid_until_order` | 改排序消费规则时 |
| `comic_agent/services/storybible_snapshot.py` | 时刻快照合并(纯读、确定性、无 LLM) | 改快照合并逻辑时 |
| `comic_agent/services/storybible_content_hash.py` | 服务端 SHA-256 内容哈希(幂等键) | 一般不用动 |
| `comic_agent/services/storybible_validator.py` | 确定性校验:证据、身份去重、状态区间重叠 | 加校验规则时 |
| `comic_agent/services/commit_service.py` | 唯一正式写入入口(单事务、幂等) | 改提交流程时 |
| `comic_agent/services/context_builder.py` | 组装有界上下文(上限:提案 20/类、时间关系 64、chunk 3) | 改上下文裁剪时 |
| `comic_agent/repositories/storybible_repository.py` | 项目隔离的持久化与读取 | 改查询/存储时 |
| `comic_agent/api/storybible.py` | HTTP 路由 | 加端点时 |
| `scripts/demo_storybible_state_flow.py` | 端到端演示(离线假 LLM) | 演示/冒烟 |
| `docs/schema_contracts.md` | 契约与兼容性说明 | 每次改 schema 必更新 |
| `migrations/versions/0004_storybible_resources.py` | 存储表迁移 | 加表/加列时 |

## 3. 数据流

```
叙事解析提案(entity/event/claim/state-change)  +  timeline 关系(temporal_relation)
        │
        ▼  POST /projects/{pid}/storybible/curate (StoryBibleContextV1)
StoryBibleCurator.run
  1. LLM 按 prompt 生成草稿(合并提案,不重抽原文)
  2. 确定性后处理:
     a. 从 timeline 关系盖状态区间序(BEFORE/AFTER 链;全 UNKNOWN 不盖)
     b. 服务端重算 SHA-256 content_hash(不信任模型)
     c. confidence < 0.7 → 追加阻塞冲突 LOW_CONFIDENCE
  3. 强制 status=CANDIDATE(Agent 永远不写正式数据)
        │
        ▼  人工审阅 → POST /commit-plans/{plan_id} {"status":"APPROVED"}
CommitService(唯一写入边界):证据校验 + 身份/区间不变量 + 单事务幂等入库
        │
        ▼  正式状态库(profile / state / relationship / world_rule)
        │
        ▼  GET /projects/{pid}/storybible/state-at?event_order=N
StoryBibleSnapshotV1(此刻人物+地点+组织+关系+世界规则的合并快照)→ 给分镜
```

## 4. 输入契约:`StoryBibleContextV1`

策展请求体直接就是上游两个模块的输出汇总,字段全部可选(按需给):

| 字段 | 类型 | 上限 | 来源 |
|------|------|------|------|
| `project_id` | str | — | **必填**,须与 URL 路径一致 |
| `source_chunk_ids` | list[str] | 3 | 源文本块,服务端会把文本注入 prompt 供证据引用 |
| `entity_proposals` | list[EntityProposalV1] | 20 | narrative-analysis |
| `event_proposals` | list[EventProposalV1] | 20 | narrative-analysis |
| `claim_proposals` | list[ClaimProposalV1] | 20 | narrative-analysis |
| `state_change_proposals` | list[StateChangeProposalV1] | 20 | narrative-analysis |
| `temporal_relation_proposals` | list[TemporalRelationProposalV1] | 64 | timeline |
| `profiles` / `states` / `relationships` / `world_rules` | 对应 canonical 模型 | 3/3/3/3 | **只用作选取现有正式资源的提示,内容以数据库为准**(伪造值会被忽略) |

**ID 约定**:所有 ID 必须带项目前缀 `{project_id}:xxx`,如 `demo-story:ev-1`。
**证据约定**:`evidence_refs` 用 `chunk_id` + `quote_text`,`quote_text` 必须与 chunk
原文**逐字一致**(写提案时从 chunk 文本里复制,不要改写)。

完整示例(可对照 `scripts/demo_storybible_state_flow.py`):

```json
{
  "project_id": "demo-story",
  "source_chunk_ids": ["c1", "c2", "c5"],
  "entity_proposals": [
    {"proposal_id": "ent-linxia", "entity_type": "CHARACTER", "canonical_name": "林夏",
     "aliases": ["小夏"], "evidence_refs": [{"chunk_id": "c1", "quote_text": "林夏"}],
     "confidence": 0.95}
  ],
  "event_proposals": [
    {"proposal_id": "demo-story:ev-1", "event_type": "ARRIVAL", "summary": "林夏进城",
     "participant_ids": ["ent-linxia"], "location_id": "ent-city",
     "evidence_refs": [{"chunk_id": "c1", "quote_text": "林夏"}],
     "confidence": 0.95, "reality_layer": "PRIMARY"}
  ],
  "claim_proposals": [
    {"claim_id": "claim-1", "subject_id": "ent-city", "predicate": "setting",
     "object_value": "灵气充盈之地可施法", "asserted_by_entity_id": null,
     "evidence_refs": [{"chunk_id": "c2", "quote_text": "灵气充盈,得灵气者方可施法"}],
     "confidence": 0.95, "reality_layer": "PRIMARY"}
  ],
  "state_change_proposals": [
    {"proposal_id": "sc-1", "event_id": "demo-story:ev-1",
     "target_entity_id": "ent-linxia", "attribute_path": "appearance.clothing",
     "old_value": null, "new_value": "黑金外套", "persistent": true,
     "reality_layer": "PRIMARY",
     "evidence_refs": [{"chunk_id": "c1", "quote_text": "裹着黑金外套"}],
     "confidence": 0.95}
  ],
  "temporal_relation_proposals": [
    {"proposal_id": "rel-1", "source_event_id": "demo-story:ev-1",
     "target_event_id": "demo-story:ev-2", "relation": "BEFORE",
     "evidence_refs": [{"chunk_id": "c2", "quote_text": "结伴同行"}],
     "confidence": 0.95}
  ]
}
```

要点:

- 实体类型映射由 Curator 完成:`CHARACTER→PERSON`、`LOCATION→LOCATION`、
  `ORGANIZATION→ORGANIZATION`;`OBJECT/PROP/CREATURE/ABILITY/CONCEPT` **不建 profile**,
  其事实落到人物状态属性上(如 `possession.holder`);
- claim 只有在"叙述者层面的设定性客观断言"时才升格为世界规则,人物信念/猜测不会;
- `attribute_path` 直接成为状态库里的键(如 `appearance.clothing`),推荐沿用叙事解析的
  受控路径(`appearance.clothing`、`possession.holder`、`physical.condition`、`location` 等)。

## 5. 输出契约

### 5.1 策展输出:`StoryBibleCuratorProposalV1`(永远 CANDIDATE,不会直接入账)

```json
{
  "proposal_id": "demo-story:curator-1",
  "project_id": "demo-story",
  "status": "CANDIDATE",
  "confidence": 0.9,
  "evidence_refs": [{"chunk_id": "c1", "quote_text": "林夏"}],
  "commit_plan": {
    "commit_plan_id": "demo-story:plan-1",
    "project_id": "demo-story",
    "source_proposal_id": "demo-story:curator-1",
    "content_hash": "<服务端计算的SHA-256>",
    "updates": [ /* 四类之一,见下 */ ],
    "evidence_refs": [{"chunk_id": "c1", "quote_text": "林夏"}]
  },
  "conflicts": [
    {"conflict_id": "demo-story:conf-1", "project_id": "demo-story",
     "category": "IDENTITY", "summary": "别名'小夏'仅出现一次,需人工确认。",
     "affected_update_ids": ["demo-story:upd-prof-linxia"],
     "evidence_refs": [{"chunk_id": "c1", "quote_text": "林夏"}],
     "blocking": false}
  ]
}
```

`updates` 四类(判别字段分别是 `profile` / `state` / `relationship` / `world_rule`):

```jsonc
// ① 人物/地点/组织
{"update_id": "demo-story:upd-prof-linxia", "project_id": "demo-story",
 "profile": {"profile_id": "demo-story:prof-linxia", "project_id": "demo-story",
   "entity_kind": "PERSON", "canonical_name": "林夏", "aliases": ["小夏"],
   "revision": 1, "evidence_refs": [{"chunk_id": "c1", "quote_text": "林夏"}]},
 "evidence_refs": [{"chunk_id": "c1", "quote_text": "林夏"}]}

// ② 状态(有效自事件;顺序字段由服务端从 timeline 关系盖,模型留空)
{"update_id": "demo-story:upd-st-1", "project_id": "demo-story",
 "state": {"state_id": "demo-story:st-1", "project_id": "demo-story",
   "profile_id": "demo-story:prof-linxia",
   "state": {"appearance.clothing": "黑金外套"},
   "triggering_event_id": "demo-story:ev-1",
   "valid_from_event_id": "demo-story:ev-1",
   "valid_until_event_id": "demo-story:ev-3",
   "valid_from_order": null, "valid_until_order": null,
   "evidence_refs": [{"chunk_id": "c1", "quote_text": "裹着黑金外套"}]},
 "evidence_refs": [{"chunk_id": "c1", "quote_text": "裹着黑金外套"}]}

// ③ 关系
{"update_id": "demo-story:upd-rel-1", "project_id": "demo-story",
 "relationship": {"relationship_id": "demo-story:rel-1", "project_id": "demo-story",
   "source_profile_id": "demo-story:prof-linxia",
   "target_profile_id": "demo-story:prof-suyan",
   "relationship_type": "ALLY",
   "valid_from_event_id": "demo-story:ev-2",
   "evidence_refs": [{"chunk_id": "c2", "quote_text": "结伴同行"}]},
 "evidence_refs": [{"chunk_id": "c2", "quote_text": "结伴同行"}]}

// ④ 世界规则
{"update_id": "demo-story:upd-rule-1", "project_id": "demo-story",
 "world_rule": {"rule_id": "demo-story:rule-1", "project_id": "demo-story",
   "name": "灵气施法", "statement": "此界灵气充盈,得灵气者方可施法。",
   "scope": null, "evidence_refs": [{"chunk_id": "c2", "quote_text": "灵气充盈,得灵气者方可施法"}]},
 "evidence_refs": [{"chunk_id": "c2", "quote_text": "灵气充盈,得灵气者方可施法"}]}
```

### 5.2 时刻快照:`GET .../state-at?event_order=N` → `StoryBibleSnapshotV1`

```json
{
  "project_id": "demo-story",
  "event_order": 40,
  "characters": [
    {"profile_id": "demo-story:prof-linxia", "project_id": "demo-story",
     "canonical_name": "林夏", "entity_kind": "PERSON",
     "state": {"appearance.clothing": "素白长裙"},
     "state_ids": ["demo-story:st-cloth2"], "unresolved_state_ids": []}
  ],
  "locations": [
    {"profile_id": "demo-story:prof-city", "project_id": "demo-story",
     "canonical_name": "北境城", "entity_kind": "LOCATION",
     "state": {"physical.condition": "废墟"},
     "state_ids": ["demo-story:st-city-ruin"], "unresolved_state_ids": []}
  ],
  "organizations": [],
  "relationships": [
    {"relationship_id": "demo-story:rel-1", "relationship_type": "ALLY",
     "source_profile_id": "demo-story:prof-linxia",
     "target_profile_id": "demo-story:prof-suyan"}
  ],
  "world_rules": [
    {"rule_id": "demo-story:rule-1", "name": "灵气施法",
     "statement": "此界灵气充盈,得灵气者方可施法。"}
  ],
  "unresolved_state_ids": []
}
```

同一 `event_order` 永远返回相同结果(确定性,无 LLM 参与)。

## 6. 关键语义(改代码前必须懂)

1. **有效自事件(effective-from)**:每条状态都锚定一个 from 事件,从它开始生效,直到
   被后一条同属性状态覆盖(或到 until 事件)。状态库**没有"过期自动删除"**——第 5 章
   不提衣服,第 1 章的衣服依旧生效。
2. **时间线消费,不推导**:`temporal_relation_proposals` 是 timeline agent 的输出;
   Curator 只从中做确定性拓扑序(`BEFORE/AFTER` 边)给状态盖 `valid_from_order`/
   `valid_until_order`。规则:
   - `valid_from_order` = from 事件的序;`valid_until_order` = until 事件的序 **−1**
     (区间两端闭,防止相邻状态在同一点重叠冲突);
   - 会破坏区间(until−1 < from)就不盖 until;until 事件序为 0 不盖;
   - **全 UNKNOWN / 环内事件 → 不盖任何序**,绝不伪造顺序制造虚假冲突;
   - 盖上序的状态由提交校验检查"同属性重叠区间值不同"。
3. **内容哈希服务端所有**:`content_hash` = 计划内容(排除身份字段与哈希自身)的 SHA-256;
   模型给的任何值都会被覆盖。重复提交相同内容 → 复用已存计划,不会重复入账。
4. **置信度门槛**:`confidence < 0.7` 自动追加阻塞冲突 `LOW_CONFIDENCE`,仍是 CANDIDATE,
   必须人工审批。
5. **证据逐字引用**:入账前每条证据的 `quote_text` 都要在源 chunk 原文中精确命中,
   否则整单 422,不落任何数据。
6. **只提案、不写库**:Agent 永远输出 CANDIDATE 提案;唯一写正式数据的是
   `CommitService`(审批 `APPROVED` 后,单事务、幂等)。
7. **项目隔离**:所有读写都以 `project_id` 为界;跨项目 ID/证据直接拒绝。
8. **未盖序的状态**:快照里按"永恒事实"处理(始终生效)并出现在
   `unresolved_state_ids`,下游应谨慎对待其生效时刻。

## 7. 其他模块如何调用

### 7.1 策展(生成候选账目)

```powershell
Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8000/projects/demo-story/storybible/curate" `
  -ContentType "application/json" -Body (@{
    project_id = "demo-story"
    source_chunk_ids = @("c1", "c2", "c5")
    entity_proposals = @(...)      # 见第 4 节
    event_proposals = @(...)
    claim_proposals = @(...)
    state_change_proposals = @(...)
    temporal_relation_proposals = @(...)   # timeline agent 的输出原样传入
  } | ConvertTo-Json -Depth 10)
```

### 7.2 审批入账

```powershell
Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8000/projects/demo-story/storybible/commit-plans/demo-story:plan-1" `
  -ContentType "application/json" -Body '{"status":"APPROVED"}'
```

重复提交返回相同结果(幂等)。

### 7.3 读取(分镜/合并层用)

```powershell
# 某一时刻的完整世界快照(分镜每格画面前取一次)
Invoke-RestMethod "http://127.0.0.1:8000/projects/demo-story/storybible/state-at?event_order=40"

# 全部正式 profile
Invoke-RestMethod "http://127.0.0.1:8000/projects/demo-story/storybible/profiles"

# 单个 profile / 其状态历史(可按事件过滤)
Invoke-RestMethod "http://127.0.0.1:8000/projects/demo-story/storybible/profiles/demo-story:prof-linxia"
Invoke-RestMethod "http://127.0.0.1:8000/projects/demo-story/storybible/profiles/demo-story:prof-linxia/states?event_id=demo-story:ev-1"
```

代码内调用(合并层/工作流)推荐直接用服务:

```python
from comic_agent.services.storybible_snapshot import build_state_snapshot
snapshot = build_state_snapshot(repository, "demo-story", event_order=40)
```

## 8. 如何修改这个 Agent

### 8.1 质量门(每次改动必跑)

```bash
uv run pytest -p no:cacheprovider          # 全量测试(当前 166 passed + 1 skipped)
uv run ruff check .                         # lint
uv run mypy comic_agent                     # 类型(mypy strict)
uv run python scripts/export_json_schemas.py  # 重导出契约(改了 schema 必跑)
python scripts/demo_storybible_state_flow.py  # 端到端冒烟(离线,无真实 LLM)
```

### 8.2 各层修改守则

- **改 schema**(`schemas/storybible.py`):同步更新 `docs/schema_contracts.md`(版本/迁移
  说明)、`scripts/export_json_schemas.py` 的 SCHEMAS 清单、`schemas/__init__.py` 导出,
  并加 `tests/test_storybible_schemas.py` 回归;破坏性变更要升 `schema_version` 并评估迁移。
- **改 prompt / 后处理**(`agents/storybible_curator.py`):prompt 与 `_OUTPUT_SCHEMA`
  必须保持同步(模型只会产出 schema 里允许的东西);确定性后处理要能离线测试
  (fake provider + `tests/test_storybible_curator.py`)。
- **加校验**(`services/storybible_validator.py`):先写失败测试(`tests/test_storybible_commit_service.py`),
  再实现。
- **任何 bug 修复必须加回归测试**(AGENTS.md 硬性要求)。
- 单元测试**禁止**调用真实 LLM/网络(用假 provider、SQLite、httpx MockTransport);
  真实模型冒烟只在显式 `RUN_LIVE_LLM_SMOKE_TEST=1` 时运行。

### 8.3 接新上游输出的套路

narrative-analysis 分支后续会合并 `RelationshipSignalProposalV1` 和
`KnowledgeStateProposalV1`。届时按以下套路接入(契约合并到 main 后即可动手):

1. 在 `StoryBibleContextV1` 加 `relationship_signal_proposals` /
   `knowledge_state_proposals` 字段;
2. `ContextBuilder` 与 API `_build_project_context` 透传 + 证据校验;
3. prompt 规则:关系信号 → `RelationshipUpdateProposalV1`;知晓状态 → 人物状态属性
   (如 `knowledge`)——消费逻辑已在文档标注,实现时补回归测试。

## 9. 边界与约定(不要做的事)

- 不要在 storybible 里推导/提取时间线(那是 timeline agent 的活);只消费
  `temporal_relation_proposals`。
- 不要让 Agent 直接写正式数据;唯一入口 `CommitService`,审批门是
  `{"status": "APPROVED"}`。
- 不要复制 schema 到 Agent/API/DB 模块(`schemas/` 是唯一权威)。
- 不要信任模型给的 `content_hash` / 顺序字段 / status(服务端全部重算或强制)。
- 不要悄悄合并疑似重复身份——输出 ConflictV1 交人工裁决。
- ID 一律 `{project_id}:xxx`;证据 `quote_text` 必须逐字复制原文。

## 10. 常见坑

| 症状 | 原因 | 处理 |
|------|------|------|
| curate 返回 422 `quote_text does not match` | 模型改写/漏字了原文 | 提示词要求逐字复制;调模型或换更稳的引用 |
| 状态没被盖序(全在 `unresolved_state_ids`) | timeline 输入是全 UNKNOWN,或事件 ID 与关系 ID 不一致(没加项目前缀) | 属预期;检查 ID 一致性 |
| 同属性两个状态提交被拒 | 区间重叠且值不同(包含 until 边界重叠) | until 序用 −1 规则;或先修时间线关系 |
| 重复策展返回不同 plan | 模型改了 update 内容 | 内容完全一致才会复用(按内容哈希) |
| `commit_plan_id already belongs to a different plan` | 同一 plan id 被不同内容复用 | 换 id;或确认重放时内容一致 |
| Windows 测试 `WinError 5` | 临时目录权限 | `pytest --basetemp=./.pytest_tmp` |

## 11. 演示与验证

`scripts/demo_storybible_state_flow.py` 用两章小说 + 假 LLM 跑完整链路,并打印
时刻 0/1/2/3/40 的快照,验证:状态继承(第 5 章没提的衣服/剑/城在时刻 40 依然正确)、
换装/易主/焚毁的时序切换、关系与世界规则全程生效。改完代码后建议跑一遍。
