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

## 7. 身份、账号和认知规则

1. Character、Account、Organization、StoryObject 和 Location 必须作为不同 Entity 类型处理，不能因名称相同或署名相同自动合并。
2. EntityMention 是一次文本出现；EntityAlias 是稳定名称映射。代词、一次性称呼、签名和缩写必须先作为 EntityMention 处理。
3. 相似读音、同名、同首字母、拼音中包含同一字母或同款物品不能单独作为身份合并证据。
4. 当一个 EntityMention 有多个合理候选且证据不足时，必须建立 UnresolvedReference，并保留候选、排除项和 EvidenceRef。
5. “他们”“那些人”等群体指代在成员和组织身份未明确前必须建立 UnresolvedGroupReference，不能强行升级为 Organization。
6. Organization 只有在存在稳定名称、职能、成员边界或发布主体证据时建立。
7. Account 是数字身份，Character 是人物；账号名不能默认作为人物别名。
8. AccountAccessRelation 只描述谁经营账号、知道密码、共享访问或可能访问账号，不证明某条 Message 的真实作者。
9. AuthorshipClaim 必须用于记录 Message、照片、帖子、邮件或署名文本的作者/发送者/发布者判断。
10. 可见发送账号、账号经营者、账号密码知情者和具体 Message Author 必须分开记录。
11. Message 中表达的内容必须抽取为 Claim；收到、看到或发布 Message 的行为才是 Event。
12. Claim 必须标记 claim_type 和 verification_status；角色的 ASSERTION、DENIAL、ACCUSATION、HYPOTHESIS、MEMORY、INTERPRETATION、PREDICTION 不能直接升级为 Canonical Data。
13. KnowledgeState 必须绑定 Character、StoryTime、RealityLayer、knowledge_target 和 EpistemicStatus，且不能从读者视角、旁白视角或其他角色视角泄漏信息。
14. NarrativePerspective 必须记录叙述来源和可见性边界；受限视角、匿名消息、草稿改写和不可靠记忆不得自动覆盖正式事实。
15. 当证据只支持“可能”“疑似”“无法判断”时，必须保留 UNKNOWN、UNCERTAIN 或 UNRESOLVED，不允许为了生成漫画连续性而补全身份事实。

## 8. 关系、道具和伤势细化规则

### RelationshipState 多维规则

1. RelationshipState 必须按 StructuralRelation、InteractionState、TrustState 和 CommunicationAccess 等维度分别记录。
2. COOPERATING 不等于 TRUSTS。
3. 动作默契不等于恢复信任，也不等于 RECONCILED。
4. 一句“我原谅你”首先是 DialogueUnit 和 Claim 或 ExpressedStance；只有额外证据支持时才能更新 TrustState。
5. 表面合作不自动恢复 StructuralRelation。
6. 通讯录好友权限不等于真实情感关系。
7. 每个关系维度必须具有独立 EvidenceRef。
8. 不允许一个维度的证据静默覆盖另一个维度。
9. 证据不足的维度保持 UNKNOWN。

示例：陆岚与陈默在谢幕时可记录为 `structural_relation=FORMER_PARTNERS`、`interaction_state=COOPERATING`、`communication_access=REMOVED`；“完成默契谢幕”只支持 COOPERATING，不支持 TRUSTS 或 RECONCILED。

### ObjectState 权利和使用规则

1. 交给某人不等于转移所有权。
2. 借用不等于拥有。
3. 佩戴不等于拥有。
4. 保管不等于拥有。
5. owner 证据不足时保持 UNKNOWN。
6. holder 变化不能静默修改 owner。
7. in_use_by 变化不能静默修改 holder。
8. 同一物体的权利关系和物理状态可以同时变化。

示例：陈默将胸针交给陆岚，支持 holder 变为陆岚；陆岚临时佩戴，支持 in_use_by 变为陆岚；归还苏闻后 holder 变为苏闻。不得仅因临时持有把 owner 改为陆岚。

### InjuryState 生命周期规则

1. 同一伤势可以经过多个 phase。
2. 包扎不是新的独立伤势，而通常是原伤势的处理阶段。
3. 后续再次受伤时，只有明确新伤害才建立新伤势事件。
4. “伤口愈合但留下浅疤”表示活动性伤势结束。
5. 疤痕作为持续视觉状态继续存在。
6. 不根据治疗方式自动推断医学严重程度。
7. 原文未说明的医学结论保持 UNKNOWN。

示例：左手划伤为 ACUTE，手帕包扎为 FIRST_AID，缝三针为 MEDICALLY_TREATED，拆线并留下浅疤为 HEALED_WITH_MARK。

## 9. 视觉版本与临时状态规则

1. 长期年龄、基础脸部、体型、长期发型和持久疤痕阶段变化可以建立新的 CharacterVisualVariant。
2. 单场临时服装、临时包扎、血迹、污渍、暂时持有的道具和单场首饰不应导致视觉版本组合爆炸。
3. 反复使用且经过审核的经典服装可以保存为可复用 CostumeProfile；本阶段不要求作为 P0 顶层 Schema。
4. 临时视觉状态不能反向修改故事事实。
5. PanelSpec 必须同时绑定 `character_state_id` 和 `visual_variant_id`。
6. 生成前可使用派生的 ResolvedCharacterAppearance，把基础 CharacterVisualVariant 与当前 CharacterState、ObjectState、InjuryState 和临时视觉约束合成完整外观。

## 10. Observable Behavior、Expressed Stance 与 Internal State 规则

1. 可观察行为可以成为 Canonical Event。
2. 人物说出的态度首先是 DialogueUnit 和 Claim 或 ExpressedStance。
3. 人物说“我原谅你”不自动证明真实信任已恢复。
4. 默契合作只能直接支持 InteractionState，不能直接支持 TrustState。
5. 哭泣可以确认可观察情绪表现，但不能证明人物对事件负有责任。
6. 内心意图只有在可靠 NarrativePerspective 明确呈现时才能进入 Canonical CharacterState。
7. 动作结果不能自动推断长期关系变化。
8. 角色记忆首先是 Claim 或 NarrativeMention，除非有其他证据确认。
9. 一项证据只能更新它直接支持的关系维度。

## 11. 复杂时间线规则

1. NarrativeOrder 只能表示文本出现顺序，不能替代 StoryTime。
2. 相对时间必须绑定 anchor_event 或 anchor_story_time；锚点不唯一时保留 candidate_anchors，并将 resolution_status 标记为 UNCERTAIN 或 UNKNOWN。
3. “三天前”“明晚以前”“前一天”等表达不得脱离叙述锚点单独解析。
4. SIMULTANEOUS 用于两个事件或状态共享同一明确时间点、同一叙述锚点或原文同步声明。
5. OVERLAPS 用于两个时间区间存在交集，但起止不完全相同，或只能确认区间重叠。
6. 时间区间覆盖某个时间点时，可记录 AT_TIME 或 SAME_ANCHOR 派生说明，但不要强行改写为完全 SIMULTANEOUS。
7. 同一历史夜晚被多次回忆、转述、病历记录或客观叙述时，应建立多个 NarrativeMention、Claim 或相关 Event，并回指同一 Event 或事件簇。
8. 角色记忆和讲述中的时间信息先作为 Claim 或 NarrativeMention；只有证据支持时才提交为 Canonical StoryTime。
9. 观察到某物在某地，可以确认该时间点的 ObjectState 或 observation Event；不能自动确认移动者、完整移动路径或中间持有者。
10. 已知离散 ObjectState 之间允许存在 UNKNOWN interval，不得为了连续性自动填补 owner、holder 或 location。
11. 结果由原文确认但参与者未知的状态变化，可以建立 actor=UNKNOWN 或 actor_ref=UnresolvedReference 的 Event 候选；角色对参与者的解释仍是 Claim。
12. TemporalRelation BEFORE、文本相邻、短时间间隔或视觉并置都不能单独支持 CausalRelation。
13. 时间图中缺失的区间应显式保留 UNKNOWN，不得用最邻近状态静默延展到无证据范围。

## 12. RealityLayer 判定与隔离规则

1. `PRIMARY` 是现实主线标准命名；`MAIN_REALITY` 仅作为旧称或说明性同义词。
2. 非 `PRIMARY` 层的外貌、伤势、道具状态不默认写入 `PRIMARY`。
3. 梦醒后的恐惧、回避、创伤反应或现实行动可以作为 `PRIMARY` 的后续 Event、StateChange 或 CharacterState。
4. 角色主动想象的交付、伤害、移动或对话不改变现实 ObjectState、CharacterState 或 Event 图。
5. 预测、预言、系统预测模拟和可能性画面不进入已发生 StoryTime；除非文本明确确认其为未来真实片段，否则不能标记为 `FLASH_FORWARD`。
6. 设备重放画面若存在污染、冲突、否认证据或来源不可靠，应标记为 `UNRELIABLE_MEMORY` 或保留 candidate_layers，并使用 `UNKNOWN`/`UNCERTAIN` 说明原因。
7. 画面内容、角色说法、系统日志标签和 Canonical Data 必须分离：画面可生成 NarrativeMention，角色说法进入 Claim/KnowledgeState，系统标签是 Evidence 线索或 Claim，Canonical Data 只能由证据检查后提交。
8. 系统日志标签被质疑时，应保留互斥 Claim；签名、时间戳或日志完整性证据只支持其直接证明的范围。
9. 梦中、回忆中、想象中或模拟中的道具，不能仅因颜色、形状、名称相近或角色确信自动合并为现实 StoryObject。
10. 相似现实事件不能反向证明梦境、污染记忆或预测模拟为准确预见，也不能单独建立 CausalRelation。
11. RealityLayer 不确定时保留候选层、证据来源和不确定原因，不得为了生成连续性强行选择唯一层。

## 13. Claim、KnowledgeState 与 CommitService 规则

1. 指控、否认、猜测、暗示、调查推论和 Agent 推理首先是 Claim 或 Proposal，不能直接升级为 Canonical Data。
2. “甲说乙拿了某物”只支持一条 ACCUSATION Claim，不支持“乙拿了某物”的 Canonical Event。
3. 读者通过全知旁白、客观画面或叙述机关看到的信息，可以作为 Canonical Data 的证据来源，但 visible_to_character_ids 为空时不得进入人物 KnowledgeState。
4. 后续监控、调查、旁白或证据确认事实后，不能反向把角色在过去 StoryTime 的 SUSPECTS、BELIEVES、HEARD 或 UNAWARE 改成 KNOWS。
5. 角色猜中真实事实时，历史 KnowledgeState 仍按其当时证据记录，直到角色获得足够证据才升级。
6. 物体出现在某人衣袋、房间或手边，只能确认该时间点的 ObjectState；不能自动推出偷窃、栽赃、动机、责任或完整移动路径。
7. 从一个离散 ObjectState 到另一个离散 ObjectState 之间缺少证据时，应显式保留 UNKNOWN 移动链。
8. 未知行动者使用 actor=UNKNOWN 或 actor_ref=UnresolvedReference；不得为身体局部、衣服颜色或模糊剪影强行新建 Character。
9. 相似手套、钥匙、衣物或其他道具只能建立 candidate_link 或 UNCERTAIN object_identity，不能仅凭外观相似自动合并 StoryObject。
10. 两个 Agent 输出互斥 Proposal 时，CommitService 不得任选其一；应保留冲突 Proposal/Claim，只提交证据支持的中性事实。
11. 冲突需要人工判断时，CommitService 应生成审核项或冲突状态，而不是为了叙事闭合写入未经证实的 Canonical 结论。
