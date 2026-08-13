# Narrative Analyst Modes Team Brief

## Current Batch Contract

NarrativeAnalyst is the top-level narrative parsing Agent. Its modes are
internal capability branches that read bounded `SourceChunkV1` context and output
Proposal objects only.

Implemented modes now share a batch-shaped outer contract:

```text
event_extraction -> EventProposalBatchV1 -> proposal.events[]
entity_extraction -> EntityProposalBatchV1 -> proposal.entities[]
claim_extraction -> ClaimProposalBatchV1 -> proposal.claims[]
knowledge_state_extraction -> KnowledgeStateProposalBatchV1 -> proposal.states[]
state_change_extraction -> StateChangeProposalBatchV1 -> proposal.changes[]
```

The number of items in each batch is based on distinct source-grounded facts,
not chunk count. One chunk can produce multiple proposals, and three chunks can
still produce one proposal when the text only supports one distinct item.
Each proposal item needs its own `EvidenceRefV1`; repeated entities or repeated
claims across chunks should be output once.

All six Narrative Analyst modes are implemented, including `relationship_signal_extraction`.

Current recommended model for manual Narrative Analyst extraction eval is
`deepseek-chat`. Keep `deepseek-v4-pro` for future Continuity Timeline or other
reasoning-heavy evals. Automated tests use fake providers only and must not call
real LLMs.

Next manual eval batches:

```text
B: Entity Batch, 1/2/3 chunks
C: Entity Batch + Claim Batch, 1/2/3 chunks
E: Claim Batch, 1/2/3 chunks, plus KnowledgeState prep notes
```

Record sanitized summaries only. Do not paste `.env`, API keys, real source
text, `quote_text`, `claim_text`, aliases, raw provider responses, or
`message.content`.

## Whole-Document Analysis v0.1

`NarrativeAnalyst` remains one top-level Agent with internal modes. The ordinary
user flow is document selection plus mode selection, not chunk selection. A
persisted analysis task plans three-chunk windows with stride two and runs them
sequentially. Each window delegates to the existing NarrativeAnalyst workflow,
keeps a linked AgentRun when a call is requested, and can fail independently.

The result aggregates only conservative exact matches: Event uses event type,
summary, and evidence; Entity uses canonical name plus entity type; Claim uses
type, text, source type, and evidence. Similar-looking proposals with different
evidence remain separate candidates for review.

Fresh Entity proposals use schema 1.1. Reviewers should verify that non-human
animals, monsters, and spirit beasts are `CREATURE`, not `CHARACTER`; subtype
must be source-supported or null. `CONCEPT` is not a fallback for every invented
or unfamiliar proper noun. Important source-grounded unnamed objects may be
`OBJECT`.

Whole-document work defaults to dry-run. A real provider call requires both the
explicit request-level checkbox and server-side `ENABLE_REAL_LLM=true`. The
in-process worker is restart-resumable through persisted pending/failed windows;
it does not write StoryBible or canonical data.

### Knowledge State v1.1 contract

`knowledge_state_extraction` is implemented. Its batch output is
`KnowledgeStateProposalBatchV1` containing only v1.1 Proposal candidates; an
empty `states=[]` batch is a successful extraction outcome.
Subjects, targets, and temporal anchors use source text plus optional candidate
Proposal links; unresolved links stay unresolved for a later linker. A Claim is
not automatically a Knowledge State, and conflicting candidate states retain
their own evidence and reality layers.

The agent reads only bounded `SourceChunkV1` context and emits Proposal objects;
it neither writes StoryBible data nor fabricates cross-Proposal ids. Automated
tests use FakeProvider only. A real LLM evaluation must be explicitly initiated
by a user. No database migration is needed: new fields exist only in compatible
Schema/JSON aggregation results and legacy v1.0 payloads remain readable.

Within one `KnowledgeStateProposalBatchV1`, `proposal_id` values and complete
knowledge-state semantics must both be unique. Across windows, a repeated
`proposal_id` is allowed, so review surfaces show batch or AgentRun context
instead of treating the bare id as globally unique. Aggregation merges only an
exact complete semantic key; it never uses fuzzy text matching or silently
upgrades unresolved references.

`target_kind` is the semantic type of the cognitive target itself, not the
speaking source and not `epistemic_status`: `EVENT` is a concrete occurrence,
discovery, change, or action; `WORLD_FACT` is a proposition about the world,
person, place, object, relationship, or fact state; and `CLAIM` is only a
statement, report, rumor, declaration, accusation, or promise as the target.
`HEARD` does not decide `target_kind`. For example, hearing that a gate is
closed is `WORLD_FACT + HEARD` when the gate state is the target; it is `CLAIM`
only when the speaker's assertion is the target.

Knowledge State `target_text` is the smallest complete, auditable core
proposition. It retains source-supported entities, negation, modality, time,
place, and causal qualifiers, but not a speech frame for a `WORLD_FACT`.
For example, normalize a rumor-content target to `山中有鬼`, not `山中有鬼的传言`;
only a target about the rumor itself retains its source and uses `CLAIM`.
`BELIEVES`, `SUSPECTS`, and `DISBELIEVES` are attitudes toward truth content, so
they must use `WORLD_FACT` or `EVENT`, never `CLAIM`: “不相信某个传言” becomes
`DISBELIEVES + WORLD_FACT + 山中有鬼`.
Do not emit both a composite target and one of its atomic parts unless they have
independent source-supported knowledge states or temporal anchors.

The Console may show a deterministic **可能重复** review hint when candidates
have the same subject, status, basis, reality layer, and temporal anchors, and
their safely normalized core target text matches while target kind or original
target expression differs. The hint is review-only: it never rewrites,
suppresses, links, upgrades, or automatically merges proposals. It exposes only
proposal, batch/AgentRun, status, basis, target, resolution, and Evidence audit
context.

`KNOWS + OBSERVED` requires text that explicitly establishes observation,
recognition, discovery, or confirmation of a concrete fact. Presence, a brief
glance, seeing an object, hearing a rumor, or narrator knowledge does not prove
the character knows the hidden fact. For example, seeing an envelope is not
knowing its letter content.


## 开发格式

可以参照已完成的事件抽取实现：

```text
参考 Agent: comic_agent/agents/event_extraction.py
参考测试: tests/test_event_extraction_agent.py
Agent 目录: comic_agent/agents/
测试目录: tests/
Schema 目录: comic_agent/schemas/narrative.py
```

每个 mode 可以参照以下格式开发：

```text
1. 新建 agent 文件

2. 编写 prompt v0.1（提示词第 0.1 版：给大模型看的任务说明）

3. 定义 AgentSpec（Agent 规格说明：记录这个 Agent 的基本约束）

4. 注入 LLMProvider（大模型调用接口）

5. 实现 run(input_context)（运行入口，Agent 的主函数。input_context 是传给 Agent 的输入上下文，比如项目 id、chunk id、文本片段）

6. 调用 provider.structured_generate(结构化生成调用：让 provider 调用模型，并要求模型输出指定的结构化结果)

7. 输出对应 Proposal schema(候选结果格式：Agent 输出的结构化数据格式)

8. 编写 fake provider 自动测试(不调用真实 LLM，用来验证代码链路是否正确)

9. 确认输出包含 EvidenceRef

10. 不写 StoryBible(Agent 不能直接写入正式故事设定库)
```

## 测试要求

每个 mode 做两类测试：

```text
自动测试: 使用 fake provider，验证代码链路。
手动测试: 使用真实 LLM，验证模型效果。
```

自动测试不调用真实 LLM，不需要 API key，也不需要校园网。验证：

```text
Agent 是否正确调用 provider
prompt 是否包含关键约束
input_context 是否正确传入
输出是否符合对应 Proposal schema
EvidenceRef 是否存在
AgentRun / workflow / API 是否能正确记录
错误信息是否脱敏
```

手动真实 LLM 测试由负责人在校园网环境执行。它验证：

```text
模型是否能理解原文
prompt 是否有效
输出是否符合 schema
是否有编造内容
EvidenceRef 是否匹配原文
quote_text 是否准确
多 chunk 输入是否稳定
```

手动测试只能记录脱敏结果，不能提交或粘贴：

```text
.env
API key
完整原文
长 quote
raw provider response
message.content
数据库文件
local_eval/
output/
tmp/
```

## Unified Smoke 评估矩阵

`scripts/smoke_narrative_analyst.py` 是当前 NarrativeAnalyst mode 的统一
dry-run / real opt-in smoke 入口。它支持：

```text
event_extraction
entity_extraction
claim_extraction
```

统一 summary 只记录脱敏评估字段，不记录原文、quote_text、claim_text、aliases
明细、raw provider response、message.content 或 API key。共同字段包括：

```text
project_id
mode
dry_run
real_llm_requested
real_llm_enabled
real_llm_called
provider_name
model
import_idempotent
context_chunk_ids
chunk_limit
chunk_offset
selected_chunks_count
max_chars_per_chunk
input_chars_total
truncated_chunks_count
agent_run_saved
agent_run_id
agent_run_status
provider_result_id
provider_success
provider_error_diagnostics
usage_prompt_tokens
usage_completion_tokens
usage_total_tokens
output_schema
schema_validation_passed
evidence_validation_passed
quote_matched
char_range_matched
error_message
manual_score
manual_issue
failure_category
recommended_action
```

mode-specific 字段：

```text
event_extraction: batch_id, events_count, event_proposal_ids, primary_event_type, primary_event_summary, event_evidence_results
entity_extraction: batch_id, entities_count, entity_proposal_ids, entity_evidence_results
claim_extraction: batch_id, claims_count, claim_proposal_ids, claim_evidence_results
```

当前 failure_category：

```text
PROVIDER_TIMEOUT
PROVIDER_LENGTH_BEFORE_FINAL_CONTENT
PROVIDER_CONTENT_MISSING
SCHEMA_VALIDATION_FAILED
EVIDENCE_VALIDATION_FAILED
QUOTE_NOT_MATCHED
CHAR_RANGE_NOT_MATCHED
MODE_NOT_IMPLEMENTED
UNKNOWN_ERROR
```

`manual_score` / `manual_issue` 是人工评估占位字段，自动输出保持 null。
如果负责人在本地填写人工评分，只能保存在 ignored 的本地输出目录，不提交。

## Narrative Analyst Console

`web_console/index.html` 已新增 Narrative Analyst Console。后端 endpoint：

```text
POST /projects/{project_id}/agent-runs/narrative-analyst
```

当前支持：

```text
event_extraction -> EventProposalBatchV1
entity_extraction -> EntityProposalBatchV1
claim_extraction -> ClaimProposalBatchV1
knowledge_state_extraction -> KnowledgeStateProposalBatchV1
```

`claim_extraction` fresh outputs use Claim schema `1.2`. Current claim types are
`FACTUAL_ASSERTION`, `BELIEF`, `HYPOTHESIS`, `DENIAL`, `ACCUSATION`, `MEMORY`,
`EVALUATION`, `INTERPRETATION`, `PREDICTION`, and `COMMITMENT`; every claim
includes `temporal_scope`. `FACTUAL_ASSERTION` is only for direct, unhedged
statements; it is never the fallback for a guess, belief, evaluation, or
interpretation. Legacy `ASSERTION` is read-compatible only for historical
`schema_version="1.0"` payloads; v1.1 payloads remain readable.

Console 能设置：

```text
mode
project_id
chunk_ids
chunk_limit
chunk_offset
max_chars_per_chunk
real_llm_requested
```

网站端 Narrative Analyst 必须显式选择 1-3 个 chunks 后再运行。不要在网页中让
Chunk IDs 留空并依赖 `chunk_offset` / `chunk_limit`，因为同一 project 多次导入
不同 TXT 后，project-level offset 可能指向旧导入文本。CLI / scripted caller 仍可
使用 offset fallback，但 API response 会返回脱敏的 selected chunk metadata，方便
审计实际输入。

手动评估新 TXT 时建议使用新的 `project_id`；导入后点击“查看章节”，重新选择本次
要评估的 chunks，并在 Selected input chunks 区域确认 chunk_id、chapter/document 和
短 preview。Full Proposal 中的 evidence quote 必须能对应这些 selected input
chunks。不要粘贴真实原文、长 quote、`claim_text`、raw provider response、
`message.content` 或 API key。

dry-run 不调用 provider，不保存 AgentRun，只返回上下文 readiness 和预算 summary。
real opt-in 需要同时满足：

```text
ENABLE_REAL_LLM=true
real_llm_requested=true
```

测试中通过 fake provider 覆盖 real opt-in 路径，不调用真实 LLM。
成功运行会保存 AgentRun，并可通过 AgentRun detail 和 evidence API 继续审计。

Console 默认展示脱敏 summary；Full Proposal JSON 折叠展示，供人工评估
`claim_text`、`quote_text` 和 EvidenceRef。不要把 Proposal 中的原文 quote、
claim_text、完整 chunk text、raw provider response、message.content、API key
或本地输出文件提交或粘贴到 PR / issue / chat。

Manual Review Checklist 目前只展示 null 占位，不写回数据库：

```text
event: events_cover_major_plot_points, event_count_reasonable, no_duplicate_events, no_invented_events, every_event_has_supporting_evidence, event_summaries_supported_by_quotes
entity: entities_cover_major_entities, entity_count_reasonable, no_duplicate_entities, entity_types_correct, names_and_aliases_not_invented, every_entity_has_supporting_evidence
claim: claims_cover_major_claims, claim_count_reasonable, no_duplicate_claims, claim_is_attributable_proposition, claim_type_matches_decision_table, claim_temporal_scope_correct, prediction_commitment_distinguished, every_claim_has_supporting_evidence, no_duplicate_or_invented_claims
common: manual_score, manual_issue
```

## Mode 分工

## NarrativeAnalyst 顶层入口

`NarrativeAnalyst` 是叙事解析顶层 Agent，负责统一承载“从原文读出候选事实”的内部 mode。
mode 是 `NarrativeAnalyst` 内部能力分支，不再作为额外顶层 Agent 计数。

当前 shell 提供：

```text
统一入口: comic_agent/agents/narrative_analyst.py
统一 mode registry: event/entity/claim 已实现，后续 mode 已登记 planned
统一运行接口: NarrativeAnalyst.run(mode, input_context)
统一查询接口: list_modes(), get_mode_spec(mode)
```

当前 implemented modes：

```text
event_extraction -> EventProposalBatchV1
entity_extraction -> EntityProposalBatchV1
claim_extraction -> ClaimProposalBatchV1
```

当前六个既定 Narrative Analyst mode 均为 implemented；没有 remaining planned mode。

shell 的意义：

```text
1. 后续 workflow/API 只需要接一个 NarrativeAnalyst 入口。
2. 所有 mode 的状态、output_schema、EvidenceRef 要求和 max_context_chunks 有统一注册表。
3. event/entity/claim 继续复用各自 Agent，不复制 prompt 逻辑。
4. 每个 implemented mode 通过同一受限 workflow、Provider 注入、失败恢复与审计路径运行。
5. 本次没有新增真实 LLM 调用；Relationship Signal 仍不写 StoryBible。
```

### 1. event_extraction

中文名：事件抽取

当前状态：已完成

开发文件：

```text
comic_agent/agents/event_extraction.py
tests/test_event_extraction_agent.py
```

功能：

```text
从 SourceChunk 中抽取“发生了什么事”。
```

未来输出：

```text
EventProposalBatchV1
```

输出内容：

```text
事件类型
事件摘要
参与者 ids
地点 id
现实层级
证据 EvidenceRef
置信度
```

`event_extraction` 统一返回一个 batch。batch 的 `events[]` 才是下游
Timeline / temporal solver / state-change agent 应消费的事件列表。一个 chunk
可以输出多个事件；多个 chunks 如果只叙述一个连续事件，也可以只输出一个事件。人工
评估应检查事件覆盖率、数量是否合理、是否去重、是否无臆造，以及每个 summary 是否
被自己的 quote_text 直接支持。

当前完成情况：

```text
prompt v0.1 已完成
LLMProvider 已接入
fake provider / fake HTTP 自动测试已完成
真实 LLM 1/2/3 chunk 手动测试已通过
AgentRun / Evidence 审计已接入
web_console 测试页面已接入
```

### 2. entity_extraction

中文名：实体抽取

当前状态：v0.1 已完成并强化，fake provider 自动测试、smoke dry-run/real opt-in 路径、统一 NarrativeAnalyst API/Console 路径、1/2/3 chunk 手动真实 LLM 评估均已通过。

开发文件：

```text
comic_agent/agents/entity_extraction.py
tests/test_entity_extraction_agent.py
scripts/smoke_real_entity_agent.py
tests/test_real_entity_smoke.py
```

功能：

```text
从原文中抽取人物、地点、物品、组织等对象。
```

输出：

```text
EntityProposalBatchV1
```

输出内容：

```text
实体 id
实体类型
标准名称
别名
证据 EvidenceRef
置信度
```

示例：

```text
人物: 林凡
地点: 咖啡店
物品: 水杯
组织: xx公司
```

完成步骤：

```text
1. entity_extraction.py 已创建
2. EntityExtractionAgent v0.1 已实现
3. prompt 要求 all significant distinct source-grounded entities
4. 输出 EntityProposalBatchV1，具体实体在 entities[]
5. FakeProvider 自动测试已实现
6. prompt 边界测试覆盖 no invention、evidence、JSON only、StoryBible 禁止项
7. 返回结果测试覆盖 EntityProposalBatchV1、entities[]、canonical_name、EvidenceRef
8. smoke dry-run 覆盖 TXT 导入、import idempotency、ContextBuilder、脱敏 summary
9. real smoke 只在 ENABLE_REAL_LLM=true 且显式 --enable-real-llm 时调用 provider
10. deepseek-v4-pro 手动真实 LLM 1/2/3 chunk eval 已通过
11. prompt 已强化 entity_type 决策、canonical_name、aliases、exact quote、no reasoning 规则
12. Narrative Analyst Console 已支持 entity_extraction，并提供 entity 人工评估 checklist
13. 不写 StoryBible
```

手动真实 LLM 评估结论：

```text
1. dry-run passed。
2. 1 chunk real eval passed。
3. 2 chunk real eval passed。
4. 3 chunk real eval passed。
5. 旧基线 output_schema=EntityProposalV1，provider/schema/evidence/quote validation 均通过。
6. 当前代码 contract 已升级为 EntityProposalBatchV1；下一轮人工真实 eval 需要按 entities[] 批量复核。
7. char_range_matched 在 quote_start/quote_end 省略时可以为 null。
8. 观察到 CHARACTER 和 ORGANIZATION；canonical_name 非空；本轮 aliases_count=0。
9. 只记录脱敏结果，不粘贴 API key、真实原文、长 quote、raw provider response 或 message.content。
```

人工评估 checklist：

```text
entities_cover_major_entities
entity_count_reasonable
no_duplicate_entities
entity_types_correct
names_and_aliases_not_invented
every_entity_has_supporting_evidence
manual_score
manual_issue
```

失败后 prompt triage：

```text
aliases 被编造 -> 修 aliases 规则
canonical_name 太长/编造 -> 修 canonical_name 规则
entity_type 错 -> 修 type decision table
quote_matched=false -> 修 exact quote
把事件/claim 当实体 -> 修 mode boundary
```

### 3. claim_extraction

中文名：主张抽取

当前状态：v0.1 已实现，已接入 NarrativeAnalyst mode shell，自动测试使用 fake provider。

开发文件：

```text
comic_agent/agents/claim_extraction.py
tests/test_claim_extraction_agent.py
scripts/smoke_narrative_analyst.py
```

功能：

```text
抽取角色、旁白、消息中提出的说法、判断、记忆、假设、预言等。
```

输出：

```text
ClaimProposalBatchV1
```

输出内容：

```text
主张 id
主张类型
主张文本
来源类型
来源 id
目标事件 id
验证状态
现实层级
证据 EvidenceRef
置信度
```

示例：

```text
“他不是凶手。”
“xx能逆转寿命。”
“xx隐瞒了真相。”
```

完成情况：

```text
1. claim_extraction.py 已创建
2. ClaimExtractionAgent v0.1 已实现
3. prompt 要求 all salient distinct claims
4. prompt 区分 claim 与 EventProposalV1 / EntityProposalV1
5. 输出 ClaimProposalBatchV1，具体主张在 claims[]
6. FakeProvider 自动测试已实现
7. NarrativeAnalyst.run("claim_extraction", input_context) 已接入
8. smoke_narrative_analyst.py 支持 --mode claim_extraction
9. 自动测试阶段不接真实 LLM
10. 真实 LLM eval 由负责人手动执行
11. 不写 StoryBible
```

### 4. knowledge_state_extraction

中文名：知识状态抽取

已实现并接入手动 workflow 与整文 worker。

开发文件：

```text
comic_agent/agents/knowledge_state_extraction.py
tests/test_knowledge_state_extraction_agent.py
```

功能：

```text
抽取某个角色知道、相信、怀疑或不知道什么。
```

输出：

```text
KnowledgeStateProposalBatchV1（`states[]` 中为 KnowledgeStateProposalV1）
```

输出内容：

```text
主体与目标可故意保持 unresolved；没有明确开始或结束依据时，时间锚点必须为空
认知状态与认知依据
现实层级
证据 EvidenceRef
置信度
```

示例：

```text
xx知道xx存在。
xx怀疑xx隐瞒真相。
反派不知道主角还活着。
```

完成步骤：

```text
1. 每个窗口输出一个 KnowledgeStateProposalBatchV1，可为空
2. 每个非空候选保留独立 EvidenceRefV1
3. 不从说话、看见、在场或沉默推断 KNOWS / UNAWARE；单纯断言也不推断 BELIEVES
4. 不伪造 Entity / Event / Claim / StoryBible id
5. 自动测试阶段仅使用 FakeProvider，不调用真实 LLM
6. 不写 StoryBible；后续 linker 才能显式关联 unresolved 锚点
```

### 5. state_change_extraction

中文名：状态变化抽取

`StateChangeExtractionAgent` 已注册为 Narrative Analyst 的 implemented mode。

开发文件：

```text
comic_agent/agents/state_change_extraction.py
tests/test_state_change_extraction_agent.py
```

功能：

```text
抽取人物、物品、地点等状态发生的变化。
```

输出：

```text
StateChangeProposalBatchV1（其中每项为 StateChangeProposalV1）
```

输出内容：

```text
事件摘要与可选 EventProposalV1 候选引用
目标原文名称、可持续对象分类与可选 EntityProposalV1 候选引用
受控属性路径：health.injury、life_status、location、possession.holder、physical.condition、accessibility、availability、quantity、role.status、appearance.clothing、appearance.hairstyle（后两者仅 CHARACTER）
旧值（null 仅表示原文未说明旧值）
新值（非 null 的稳定 JSON 标量）
持续性与其 Evidence 索引
现实层级
独立 EvidenceRef 与 new-value / persistence Evidence 索引
置信度
```

示例：

```text
角色受伤
角色失去武器
地点被毁

```

已完成 v1.3 source-first Schema 合同、`StateChangeExtractionAgent`、implemented mode
注册、手动 workflow、整文 worker、可恢复窗口链路、精确聚合与 Console 审计表。Agent
仅消费受限 SourceChunk，通过 Provider interface 输出 `StateChangeProposalBatchV1`，并
始终要求 unresolved Event/Target 引用；`changes=[]` 是成功结果。整文结果使用
`NarrativeAnalysisResultV1` v1.4 的 `state_changes` 与 `relationship_signals` 字段；v1.0-v1.3
结果仍可读并默认空列表。

Event 是瞬时原因，State Change 是动作后可供后续叙事使用的状态结果，两者可以同时
输出。v1.3 的 `appearance.clothing` 与 `appearance.hairstyle` 只接受人物明确完成的
换装/发型转换；计划、静态外貌、风吹、光照和短暂表情必须为空。连续“裂纹→崩塌”默认
只保留最终结果，只有有时间或独立反应分隔时才保留两条。`persistent=false` 仅表示
没有明确持续性证据，并不表示状态立即消失。

Prompt 约束 `persistent=true` 仅用于原文明确的持续、永久、从此、长期、稳定或等效
语义；崩塌、关闭、恢复、受伤、到达、取得、放入等结果词本身不构成持续性证据。未解析
target 的 `mention_text` 必须逐字出现在允许的 SourceChunk 中，Agent 不会把“他/她”改写
为窗口外的人名。`event_summary` 只保留当前变化的最小原因或局部上下文，不拼接其他
target 的状态结果。

整文窗口的 `chunk_ids` 是完整阅读上下文，`owned_chunk_ids` 是唯一输出责任边界；重叠
chunk 可以被多个窗口阅读，但只有 owner 的 Proposal 进入聚合。长度截断的 parent 只按
自身 owned chunks 创建 split child，并保留 parent/child lineage。State Change schema
恢复只传递安全 rule code（例如 `STATE_CHANGE_QUANTITY_MUST_BE_JSON_NUMBER`）和固定的
无源文本纠正标记，绝不保存 raw provider output。

状态变化的 `old_value` 只能来自本次选定 SourceChunk context 中明确出现的前值，或同一
context 内紧邻的、已审计的前一条变化；不得借用窗口外信息或常识。`木箱` 与 `箱盖` 是
不同的 OBJECT 提及，part-whole target resolution is intentionally out of scope。

仍未实施：StoryBible/CommitService/canonical state 写入、自动 Event/Entity 链接，以及
真实 LLM 小样本评测。本轮只使用 FakeProvider 测试，未调用真实 LLM。

### 6. relationship_signal_extraction

中文名：关系信号抽取

当前状态：`RelationshipSignalExtractionAgent` 已作为 implemented mode 接入。
`RelationshipSignalProposalV1` 与 `RelationshipSignalProposalBatchV1` Schema Contract v1.0
不变；受限单窗口 workflow、整文 worker、通用恢复/resume、ownership/split、精确聚合、API
与 Console 独立审计表均复用现有 Narrative Analyst 协议。Agent 仍只输出 source-first Proposal，
不写 StoryBible 或 canonical relationship。

已实现 Agent 文件：

```text
comic_agent/agents/relationship_signal_extraction.py
tests/test_relationship_signal_extraction_agent.py
```

功能：

```text
抽取角色或组织之间带证据、可审计的关系信号。
```

Schema 已定义的 Proposal-only 内容：

```text
关系双方（CHARACTER/ORGANIZATION）与解析状态
受控 relationship domain/kind/directionality
signal effect、assertion polarity、evidence basis、support level
可选 speaker、context event、temporal anchor
EvidenceRef、reality layer 与置信度
```

合同边界：

```text
对称关系按无序参与者对精确去重，有向关系保留反向候选；普通同场、看见、说话或一次
动作不自动构成关系信号。直接陈述/转述需 speaker，旁白/观察禁止 speaker，INFERRED
至少两条证据且只能 LIMITED。DENIAL 必须使用 DENIED；变化型 effect 必须有非空时间
锚点；亲属关系不允许 TERMINATION。未解析引用的 ID/schema 必须为 null，Schema 不查询
数据库、不自动链接、不写 StoryBible。
```

接入边界：

```text
1. mode 已注册为 implemented，并复用 workflow、worker、恢复和聚合测试路径
2. 自动测试阶段不接真实 LLM
3. 不写 StoryBible；无需数据库迁移
```

## 已实现 mode

```text
entity_extraction / event_extraction / claim_extraction / knowledge_state_extraction /
state_change_extraction / relationship_signal_extraction
```

## 硬性规则

```text
所有 mode 都只输出 Proposal。
所有 mode 都必须有 EvidenceRef。
所有 mode 的自动测试都使用 fake provider。
所有真实 LLM 测试都由负责人手动执行。
单元测试和 CI 不调用真实 LLM。
不要提交 API key、真实文本、.env、local_eval/、output/、tmp/ 或数据库文件。
不要写 canonical StoryBible data。
```

## Knowledge State offline semantic evaluation

`knowledge_state_extraction` has a separate offline evaluation surface. It consumes
only bundled synthetic/redacted cases plus an already structured
`KnowledgeStateProposalBatchV1`; it does not run a provider, inspect a project, or
write an AgentRun by default. The optional real-LLM route requires both an explicit
request and server-side `ENABLE_REAL_LLM`.

The strict evaluator preserves the extraction contract: exact auditable evidence,
stable minimal target text, unresolved references that are not upgraded, and distinct
target kinds/texts that are not fuzzily merged. Empty output is correct only for a
fixture that expects no state. Console manual review is browser-local and its export is
sanitized: fixture ID, evaluation result, and manual review fields only.

The same separate surface can build a transient `KnowledgeStateEvaluationReportV1`
from the latest browser-local Batch for each case. The report groups deterministic
case results by category and records status, target-kind, evidence, forbidden-state,
and unresolved-reference metrics. It is neither a new Agent mode nor a
whole-document aggregate, and report generation/export remains Provider-free.

Real LLM evaluation status is separate from semantic evaluation status. A provider or
schema failure is retained as a typed failed run and is not counted as an evaluated
case. Schema validation alone gets one bounded recovery request using the shared
provider recovery instruction; transport, timeout, HTTP, and configuration failures
do not retry. Reports therefore distinguish attempted, evaluated, and run-failed
cases and expose whether the run is complete and acceptance-eligible.
