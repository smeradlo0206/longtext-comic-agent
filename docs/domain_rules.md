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

## 14. Storyboard QA 与修复规则

1. RealityLayer 改变、StoryTime 跳跃或地点明显改变时通常必须切 Scene；回忆、梦境、想象或假设插入前后必须与现实主线分 Scene。
2. 过渡段可按页面节奏保留粒度弹性，但不得让不同 RealityLayer、地点或 StoryTime 的 CharacterState、ObjectState 混用。
3. StoryBeat 不是 Panel；一个 StoryBeat 可以拆多个 Panel，多个简单 StoryBeat 也可以在不丢事实的前提下合入一格。
4. 连续动作若包含多个关键时刻、信息揭示、决策变化或物体转移，不得随意压成一格。
5. 连续动作若用单格表达，必须通过明确运动线、构图或因果连续性表现起点、过程和结果，不能让道具无因出现在新 holder 手中。
6. PanelSpec 的 must_show 和 must_not_show 是故事忠实度硬约束；违反时应产生 hard_failure。
7. 原文明示“没有进入画面”“尚未出现”“不得出现”的人物、物体或状态，应进入 PanelSpec.must_not_show。
8. 原文明示必须清楚显示的关键人物、手部动作、道具、文字或状态，应进入 PanelSpec.must_show。
9. 回忆画面必须绑定过去 StoryTime 与对应 RealityLayer 的 CharacterState/CharacterVisualVariant；当前服装、发型、伤势或道具状态不得污染回忆。
10. 原文未说明的回忆发型、配饰、材质等细节保持 UNKNOWN 或风格补全标记，不能写入 Canonical。
11. 原文明示必须逐字保留的关键 DialogueUnit 不得缩写、改写或移到旁白；相同文本但不同说话者、StoryTime 或 RealityLayer，应建立不同 DialogueUnit。
12. 关键道具 ObjectState 的 holder、location、in_use_by 必须按最新 EvidenceRef 更新；不得把旧 holder 或旧位置静默延续到结束态。
13. 人物状态错误、回忆现实状态混用、关键道具缺失、违反 must_not_show、关键对白错误等 hard_failure 不能被构图漂亮、画风一致或视觉质量高抵消。
14. RepairPlan 选择策略：缺少或错误 PanelSpec 约束时先修 PanelSpec；小范围局部事实错误优先局部重绘；主体构图依赖错误对象或多处事实错误时整格重生成；阅读顺序、气泡或文字区域被破坏时才重新排版。
15. 关键道具颜色或材质被原文明确、多次强调，且该道具唯一或影响剧情功能时，颜色/材质错误应判为 high severity，通常 hard_failure。
16. 关键道具轻微色偏且不影响识别和剧情功能时，可判为 medium 或 soft issue，但必须记录 QAIssue 并复检。

## 15. 综合小说链路一致性规则

1. 共享账号、账号名、账号密码知情者、主要使用者和具体 Message 作者必须分开记录；不得把 Account 合并为 Character。
2. 账号名或日志名与人物姓名相似，只能支持 AuthorshipClaim 候选或 UnresolvedReference，不能直接确认操作者或作者。
3. 定时消息、共享账号消息或匿名消息只确认 Message 存在和可见发送方；作者、预设者和实际登录者证据不足时保持 UNKNOWN/UNRESOLVED。
4. 读者通过 Gu POV、全知叙述、客观画面或未公开材料知道的信息，不自动进入其他角色 KnowledgeState。
5. 后续证据只能从角色取得证据的 StoryTime 起更新 KnowledgeState，不能反向改写历史 SUSPECTS、BELIEVES、HEARD、UNAWARE 或 UNKNOWN。
6. NarrativeOrder 不能替代 StoryTime；倒叙、梦境、未来片段和视角切换必须同时检查 StoryTime、RealityLayer 与 NarrativePerspective。
7. 多个 NarrativeMention、Claim、巡逻表、录像、录音、设备材料或记忆指向同一历史夜晚时，应回指同一事件组或相关 Event，不得重复制造 Canonical Event。
8. 角色记忆、冲突指控、否认和解释先进入 Claim；除非有独立证据支持，不得升级为 Canonical Event、Canonical DialogueUnit 或 Canonical participant。
9. DREAM、IMAGINATION、HYPOTHETICAL、UNRELIABLE_MEMORY 或 UNKNOWN RealityLayer 中的外貌、伤势、道具转移和对白不默认污染 PRIMARY。
10. 梦醒后产生的恐惧、怀疑、行动或 Claim 可以成为 PRIMARY 的后续 CharacterState、KnowledgeState 或 Event，但梦中事实本身不进入 PRIMARY。
11. 未明确为真实未来的未来片段不得强行标记为 FLASH_FORWARD；可用 RealityLayer=UNKNOWN 和 candidate_layers 表达，不新增 AUTHOR_FORESHADOW 枚举。
12. CharacterState 和 ObjectState 查询必须绑定 StoryTime 与 RealityLayer；临时装备、伤势、持有物和位置在最新证据给出结束态后不得静默延续。
13. 物体离散状态之间允许 UNKNOWN interval；不得为了叙事闭合补全完整移动链、隐藏者、偷窃、栽赃、死亡或最终去向。
14. 关系状态必须多维判断；继续合作、共同调查、道歉或继续对话不等于 TrustState 恢复，也不等于 forgiveness。
15. 证据推断必须限于直接支持范围：学生证和外套不能证明死亡；录像只证明画面时间范围内的行为；共同在场不能排除提前预设的消息。
16. 上游事实、状态或分镜约束改变时，依赖它的 Scene、StoryBeat、PanelSpec、PromptSpec、VisualAsset、QAResult 和 RepairPlan 应标记 STALE 或重新计算。
17. 关键抽取错误若传播到后续分镜或视觉生产，应作为 QA hard failure 或 dependency_mismatch 记录，不得只用最终画面评分掩盖。
18. MVP 不负责自动裁决复杂悬疑真相、完整嫌疑链、共享账号真实作者、最终去向、证据等级排名或最优 RepairPlan；证据不足时保留 UNKNOWN、UNCERTAIN 或 UNRESOLVED。

## 16. 通知类事实锁定规则

1. 通知、公告、海报和报名说明中的关键字段应建立 FactLock 候选；FactLock 是 Canonical Data、PanelSpec 和 QA 上的精确性约束，不是新的故事事实类型。
2. 时间字段必须按业务语义分开：报名截止、材料截止、报到时间、开幕时间、展示时间、决赛日期、发布日期和更正发布日期不能混用。
3. 日期和星期必须成对准确；若最终事实为“11月17日 星期日”，写成“11月17日 星期六”属于 text_accuracy 事实错误，通常 hard failure。
4. 地点字段必须按业务语义分开：报到地点、开幕地点、主会场、材料提交渠道和办公地点不能混画或互相替代。
5. 同一建筑不同楼层、不同大厅或不同功能厅可构成不同 Location 或 LocationState；漫画不得把“科创中心一楼大厅报到”和“二楼多功能厅开幕”画成同一地点。
6. 数字必须保留单位语义：队伍数不等于学生人数，奖项支数不等于获奖学生数，材料时长不等于报名截止。
7. “最多36支队伍，每队2至4名学生”只能推出容量范围或上限区间，不能推出固定参赛人数，也不能改写为“36名学生”。
8. 奖项“一等奖3支、二等奖6支、三等奖9支”只支持共 18 支获奖队伍，不支持“前18名学生”。
9. 近似姓名、同音姓名、相近职务或同单位任职不能自动合并联系人、致辞人或负责人；必须分别保留 EntityMention、Character/Contact 候选和 EvidenceRef。
10. 字段级 Revision 必须区分创建、覆盖、确认不变、新增和作废；后续通知未提及某字段时，不得整份覆盖或清空前一有效字段。
11. “报名截止时间不变”表示更正说明重新确认初版字段，应继承初版具体值，同时将更正说明作为继续有效的 EvidenceRef。
12. 补充通知只覆盖它明确修改的字段并新增其明确增加的字段；例如名额增加和材料要求新增，不覆盖先前已更正的会场与报到地点。
13. 旧海报、旧通知、旧视觉资产或旧 PromptSpec 中被更正覆盖的字段应标记 STALE，不得覆盖最新有效 Canonical Data。
14. FactLock 字段在通知主画面、海报正文、字幕或要求完整展示的 PanelSpec 中应满足 text_accuracy=1.00；日期、地点、数字、电话、邮箱和人名不得改写。
15. 信息省略与 hard failure 的边界取决于 PanelSpec 目标：若目标是完整咨询信息，漏办公电话可判 hard failure；若只是剧情背景板且未改写事实，可判 completeness issue 或 soft/medium issue。
16. 已报名队伍无需重复报名、材料提交截止、报名邮箱、咨询电话等流程类字段也可作为 FactLock 候选。
17. 下游产物使用旧字段时，应通过 DependencyEdge 将相关 PanelSpec、PromptSpec、VisualAsset、RenderedPanel、QAResult 或 RepairPlan 标记 STALE 或重新计算。
18. 本阶段不实现 FactLockV1 Schema、字段级 Revision 数据库、完整通知解析 Agent、真实 QA Agent、完整日历校验器或完整公告管理系统。

## 17. Micro Case 边界校准规则

1. Q01-Q17、Q19-Q29 覆盖的同一事件多次叙述、梦境隔离、临时状态结束、Claim 不越级、共指不强合并、账号与人物分离、历史状态查询、预测不等于未来事件、同时不同地点、相对时间锚点、持久状态、ObjectState owner/holder、KnowledgeState 防泄漏、关系多维、PanelSpec 硬约束、QA hard/soft、Proposal 冲突、UNKNOWN/UNCERTAIN、因果边界、不可靠记忆、精确对白和 STALE 重算规则，在 V1.8 中基本可表达。
2. 地点变化通常是 Scene 的强切分信号，尤其不同房间、走廊、楼梯、建筑或楼层对应不同 LocationState 时，不得为了动作连续而合并成一个含糊地点。
3. 连续追逐、移动、搬运、交接等跨地点动作可以拆成多个相邻 Scene；连续性通过 StoryBeat 序列、PanelSpec 连续动作说明、阅读顺序或候选 `continuous_action_group` 表达。
4. 相邻 Scene 表达同一连续动作时，每个 Scene 和 PanelSpec 仍必须保留自己的 `location_id`、StoryTime 范围和 EvidenceRef。
5. PanelSpec 可以使用运动方向、出入门框、速度线、视线方向、动作残影或跨格构图表现连续动作，但不能把办公室、走廊和楼梯口画成同一 Location。
6. 跨地点连续动作的 QA 应同时检查动作连贯性和地点准确性；连续性漂亮不能抵消 location_id 或 LocationState 错误。
7. 角色讲述的童话、寓言、剧本、小说片段或故事内故事不进入 `PRIMARY` 主线 Canonical Event。
8. 嵌入故事中的 Entity、Event、StoryObject、ObjectState 和 Location 默认与主线实体空间隔离；国王、巨龙、虚构王国等不能自动进入主线 StoryBible。
9. 故事内故事可根据证据表达为 DialogueUnit、NarrationUnit、Claim、NarrativeMention，或非 `PRIMARY` 的可视化 Scene。
10. RealityLayer 可按证据使用 `IMAGINATION`、`HYPOTHETICAL` 或 `UNKNOWN` + candidate_layers；证据不足时不得强行选择唯一层。
11. 本阶段不新增正式 `FICTIONAL_STORY` RealityLayer，不实现 `ActionSequenceV1`、`EmbeddedNarrativeScopeV1`、故事内故事实体库、完整 Scene 自动切分器或完整 Panel 连续动作求解器。
12. 若嵌入故事画面被错误写入主线 Canonical Data，或虚构实体被主线角色引用为现实存在，应产生 RealityLayer leakage 或 entity_scope_mismatch 类 QAIssue。
