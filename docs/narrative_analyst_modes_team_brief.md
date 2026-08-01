# Narrative Analyst Modes Team Brief


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

## Mode 分工

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

输出：

```text
EventProposalV1
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

当前状态：v0.1 已完成，fake provider 自动测试、smoke dry-run/real opt-in 路径、1/2/3 chunk 手动真实 LLM 评估均已通过。

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
EntityProposalV1
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
3. prompt 要求 exactly one source-grounded entity
4. 输出 EntityProposalV1
5. FakeProvider 自动测试已实现
6. prompt 边界测试覆盖 no invention、evidence、JSON only、StoryBible 禁止项
7. 返回结果测试覆盖 EntityProposalV1、canonical_name、EvidenceRef
8. smoke dry-run 覆盖 TXT 导入、import idempotency、ContextBuilder、脱敏 summary
9. real smoke 只在 ENABLE_REAL_LLM=true 且显式 --enable-real-llm 时调用 provider
10. deepseek-v4-pro 手动真实 LLM 1/2/3 chunk eval 已通过
11. 不写 StoryBible
```

手动真实 LLM 评估结论：

```text
1. dry-run passed。
2. 1 chunk real eval passed。
3. 2 chunk real eval passed。
4. 3 chunk real eval passed。
5. output_schema=EntityProposalV1，provider/schema/evidence/quote validation 均通过。
6. char_range_matched 在 quote_start/quote_end 省略时可以为 null。
7. 观察到 CHARACTER 和 ORGANIZATION；canonical_name 非空；本轮 aliases_count=0。
8. 只记录脱敏结果，不粘贴 API key、真实原文、长 quote、raw provider response 或 message.content。
```

### 3. claim_extraction

中文名：主张抽取

开发文件：

```text
comic_agent/agents/claim_extraction.py
tests/test_claim_extraction_agent.py
```

功能：

```text
抽取角色、旁白、消息中提出的说法、判断、记忆、假设、预言等。
```

输出：

```text
ClaimProposalV1
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

完成步骤：

```text
1. 新建 claim_extraction.py
2. 参照 event_extraction.py 编写 ClaimExtractionAgent
3. prompt 要求 exactly one claim
4. 不把 claim 当成客观事实
5. 输出 ClaimProposalV1
6. 编写 FakeProvider 测试
7. 测试 claim_text、claim_type、source_type、evidence_refs
8. 自动测试阶段不接真实 LLM
9. 自动测试通过后，再由负责人手动做真实 LLM 小规模评估
10. 不写 StoryBible
```

### 4. knowledge_state_extraction

中文名：知识状态抽取

在 `entity_extraction` 和 `claim_extraction` 完成后开发。

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
KnowledgeStateProposalV1
```

输出内容：

```text
角色 id
知识目标 id
认知状态
来源 claim id
生效事件 id
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
1. 新建 knowledge_state_extraction.py
2. 参照 event_extraction.py 编写 KnowledgeStateExtractionAgent
3. prompt 要求 exactly one knowledge state
4. 不发明角色认知
5. 输出 KnowledgeStateProposalV1
6. 编写 FakeProvider 测试
7. 测试 epistemic_status、character_id、knowledge_target_id
8. 自动测试阶段不接真实 LLM
9. 自动测试通过后，再由负责人手动做真实 LLM 小规模评估
10. 不写 StoryBible
```

### 5. state_change_extraction

中文名：状态变化抽取

在 `event_extraction` 和 `entity_extraction` 稳定后开发。

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
StateChangeProposalV1
```

输出内容：

```text
事件 id
目标实体 id
属性路径
旧值
新值
是否持续
现实层级
证据 EvidenceRef
置信度
```

示例：

```text
角色受伤
角色失去武器
地点被毁

```

完成步骤：

```text
1. 新建 state_change_extraction.py
2. 参照 event_extraction.py 编写 StateChangeExtractionAgent
3. prompt 要求 exactly one state change
4. 输出 StateChangeProposalV1
5. 编写 FakeProvider 测试
6. 测试 event_id、target_entity_id、attribute_path、old_value/new_value
7. 自动测试阶段不接真实 LLM
8. 自动测试通过后，再由负责人手动做真实 LLM 小规模评估
9. 不写 StoryBible
```

### 6. relationship_signal_extraction

中文名：关系信号抽取

当前状态：暂缓。当前还没有专门 schema。

开发文件：

```text
comic_agent/agents/relationship_signal_extraction.py
tests/test_relationship_signal_extraction_agent.py
```

功能：

```text
抽取角色之间关系变化的线索。
```

可能输出内容：

```text
关系双方
关系类型
变化方向
证据 EvidenceRef
置信度
```

示例：

```text
信任增加
产生敌意
结盟
背叛
师徒关系确认
```

开发前置：

```text
1. 先确认是否需要新增 RelationshipSignalProposalV1
2. 如果新增 schema，必须更新 schema_version 和 migration notes
3. 先写 schema 测试
4. 再写 agent 和 FakeProvider 测试
5. 自动测试阶段不接真实 LLM
6. 不写 StoryBible
```

## 推荐开发顺序

```text
1. event_extraction: 已完成
2. entity_extraction: 已完成
3. claim_extraction
4. knowledge_state_extraction
5. state_change_extraction
6. relationship_signal_extraction
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
