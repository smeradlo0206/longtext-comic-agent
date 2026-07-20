# 领域业务规则 V1

本文记录领域词汇之外的核心业务规则。词汇定义请以 [领域词汇表](domain_glossary.md) 为准，本文只描述行为约束。

## 1. 状态生效规则

1. 状态变化从触发 Event 之后开始生效。
2. 持续性状态保持到下一次同属性 StateChange。
3. 临时状态必须具有结束 Event、结束 StoryTime 或结束 Scene。
4. 状态不能向 StoryTime 的过去反向传播。
5. 不同 RealityLayer 的状态不能默认互相继承。
6. 证据不足时使用 UNKNOWN，不允许强行推断。
7. 同一属性发生冲突时不能静默覆盖，必须产生 QAIssue 或人工审核项。
8. 状态必须保留来源 EvidenceRef。
9. 人物状态查询必须基于 StoryTime，而不是 SourceChapter 或 NarrativeOrder。
10. 视觉生成查询 CharacterState 时，还必须指定 RealityLayer。

示例：

- 长发变短发：原文“林晓剪去了长发”产生 StateChange，`appearance.hair` 从长发变短发，自剪发 Event 之后生效。
- 戴假发后摘下：戴假发是临时外观状态，必须有摘下 Event、结束 Scene 或明确结束时间。
- 受伤后包扎：受伤和包扎是两个不同 StateChange，包扎不能删除“曾经受伤”的历史事实。
- 临时穿雨衣：雨衣状态只在雨中 Scene 或明确时间段内生效，不能延续到无证据的后续 Scene。
- 获得和丢失怀表：获得怀表后 ObjectState 归属为林晓；丢失 Event 后不能继续在 PanelSpec 中默认 must_show 怀表。

## 2. 梦境、回忆、想象和假设处理规则

### FLASHBACK

- 回忆通常引用过去发生的真实事件。
- 回忆画面必须使用该过去 StoryTime 对应的历史 CharacterState。
- 回忆中的人物不能使用当前成年状态。
- 回忆内容真实性不足时标记为 UNCERTAIN。

### DREAM

- 梦境内部 Event 默认不修改现实主线状态。
- 梦境外观变化不在醒来后延续。
- 梦醒后产生的恐惧、受伤或行动，需要作为新的 PRIMARY Event 记录。

### IMAGINATION 与 HYPOTHETICAL

- 想象和假设不能直接成为 Canonical 现实事实。
- 它们可以作为视觉 Scene 生成。
- 它们必须明确标记 RealityLayer。

### UNRELIABLE_MEMORY

- 不可靠记忆保存叙述者和来源。
- 在获得更强证据前不能覆盖 Canonical Data。

### FLASH_FORWARD

- 明确发生的未来 Event 可以进入 StoryTime 图。
- 预想、预言或可能性不能直接视为已发生 Event。
- 必须区分“未来真实片段”和“人物想象的未来”。

## 3. Scene 切分规则

应切分 Scene 的信号：

- 地点明显改变；
- StoryTime 跳跃；
- RealityLayer 改变；
- NarrativePerspective 改变；
- 主要行动目标改变；
- 连续动作被明显中断。

不应机械切分的情况：

- 单纯换段不一定切 Scene；
- 同一地点中的连续对话通常仍属于一个 Scene；
- 一个 Scene 可以包含多个 StoryBeat。

## 4. StoryBeat 识别规则

StoryBeat 必须表达至少一种变化：

- 行动变化；
- 情绪变化；
- 信息揭示；
- 决策变化；
- 关系变化；
- 场景关注点变化；
- 剧情推进。

普通无意义动作不一定建立独立 StoryBeat。例如角色短暂眨眼、无信息量的转头、没有状态影响的背景移动，通常并入相邻 StoryBeat 或只作为 PanelSpec 的动作细节。

## 5. PanelSpec 约束

PanelSpec 至少需要以下信息。

### 故事依据

- `panel_id`
- `scene_id`
- `source_chunk_ids`
- `story_time_ref`
- `reality_layer`
- `location_id`

### 人物绑定

每个出场人物至少关联：

- `character_id`
- `character_state_id`
- `visual_variant_id`
- `action`
- `emotion`
- `position` 或构图角色

### 视觉硬约束

- `must_show`
- `must_not_show`
- `focus_subject`
- `shot_type`
- `camera_angle`
- `composition_goal`

### 文字与排版

- `dialogue_unit_ids`
- `narration_unit_ids`
- `reserved_text_regions`
- `reading_order`
- `text_must_be_exact`

### PanelSpec 中禁止出现

- API Key
- `provider`
- `model_name`
- `provider_prompt`
- 模型专属采样参数
- Token 信息
- 供应商专属字段

## 6. QA 判定规则

### 硬性错误

出现任意硬性错误时，`passed` 必须为 `false`。硬性错误至少包括：

- 原文未支持的新 Event；
- 原文未支持的新 DialogueUnit；
- 人物身份错误；
- 人物数量错误；
- 人物状态错误；
- 回忆和现实状态混用；
- 梦境元素污染现实；
- 道具提前出现或错误归属；
- 关键动作缺失；
- 人名、日期、地点和数字错误；
- 关键对白文字错误；
- 违背 `must_not_show` 约束。

### 软性质量

软性质量包括：

- 构图；
- 动作自然度；
- 情绪表达；
- 人体结构；
- 画面清晰度；
- 画风一致性；
- 页面阅读顺序；
- 气泡位置；
- 信息表达效率。

### 推荐通过逻辑

通过条件应表达为：

- `hard_failures` 为空；
- 所有关键维度达到最低阈值；
- 综合质量达到页面要求。

不要把具体阈值写成不可修改的行业标准。MVP 初始建议值如下，后续必须通过黄金测试集校准：

- `source_fidelity >= 0.90`
- `character_identity >= 0.88`
- `state_consistency >= 0.95`
- `text_accuracy = 1.00`
- `visual_quality >= 0.75`
