# Golden Corpus Handoff Summary

这个文件用于给团队快速了解每轮 Golden Corpus 压测后的交接信息。详细证据仍以各 `*_regression_v1.md` 为准；本文件只保存简明摘要、Schema 候选点、暂缓点和后端/QA 注意事项。

## 01_identity_coreference

本轮测试：
Golden Corpus V1 `tests/golden_corpus/01_identity_coreference`，聚焦身份共指、账号/消息作者、未解析指代、Claim、KnowledgeState 和 NarrativePerspective。

发现的问题：
`Character`、`EntityAlias`、`EntityMention`、`UnresolvedReference` 的边界需要明确；`Account`、`Message`、`AccountAccessRelation`、`AuthorshipClaim` 不能互相替代；“她”“他们”“小林”“灰桥”“北岸”“Q”等指代或署名不能强行合并。角色听闻、怀疑、知道和读者视角事实也必须分离。

采用的修改：
V1.1-draft 补充身份层级、账号和消息语义，引入 `Claim`、`KnowledgeState`、`NarrativePerspective`、`UnresolvedGroupReference` 和作者身份主张边界；示例文档补充账号经营者、消息作者、邮件 Claim 和 KnowledgeState 的拆分方式。

没有采用的修改：
没有把弱证据昵称、近音姓名、账号名、签名或代词升级为全局别名或 Canonical 身份；没有把 UNKNOWN、UNCERTAIN、UNRESOLVED 视为失败结果。

影响 Schema 的候选点：
`EntityMention`、`UnresolvedReference`、`UnresolvedGroupReference`、`Account`、`Message`、`AccountAccessRelation`、`AuthorshipClaim`、`Claim`、`KnowledgeState`、`NarrativePerspective`；`Claim.verification_status` 和 `EpistemicStatus` 需要稳定枚举。

暂不进入 Schema 的点：
复杂证据阈值、Claim 冲突自动裁决策略、人工解除 unresolved 的完整流程、消息作者与账号访问关系的高级置信度模型。

建议后端/QA 注意：
后端提交前必须保留 EvidenceRef、候选对象和排除项，不允许 Agent 直接写 Canonical Data。QA 需要检查人物身份、账号身份、消息作者、读者知识和角色知识是否混用；合理 UNKNOWN/UNCERTAIN/UNRESOLVED 不应被强行补全。

相关文件：
`docs/reviews/identity_coreference_regression_v1.md`；`docs/examples/identity_account_claim_example.md`；`docs/domain_glossary.md`；`docs/domain_rules.md` 第 7 节。

测试结果：
回归评审记录为 V1.1-draft 已消除身份层级、账号/消息、Claim、KnowledgeState、NarrativePerspective 和未解析群体的定义缺口；部分答案保留 UNKNOWN、UNCERTAIN 或 UNRESOLVED。

## 02_relationship_state

本轮测试：
Golden Corpus V1 `tests/golden_corpus/02_relationship_state`，聚焦关系状态、道具状态、伤势生命周期、临时视觉状态和行为/内心边界。

发现的问题：
`RelationshipState` 不能压缩成单一“朋友/敌人/和解”标签；`StructuralRelation`、`InteractionState`、`TrustState`、`CommunicationAccess` 需要独立记录。`ObjectState` 必须区分 owner、holder、authorized_user、in_use_by、location、condition；`InjuryState` 需要表达受伤、包扎、治疗、恢复和疤痕阶段。默契合作不等于信任恢复，记忆和否认仍是 Claim。

采用的修改：
V1.2-draft 多维化 `RelationshipState`，细化 `ObjectState` 和 `InjuryState`，澄清 `CharacterVisualVariant` 与临时礼服、绷带、胸针、血迹等临时状态的边界；示例文档补充礼服有效期、胸针持有/佩戴、左手伤势生命周期和 ExpressedStance。

没有采用的修改：
没有把临时礼服、临时绷带、胸针等组合爆炸式建成永久 `CharacterVisualVariant`；没有把公开合作、默契动作或一句态度对白升级为真实信任恢复；没有把未证实记忆或否认提交为 Canonical Event。

影响 Schema 的候选点：
`RelationshipStateV1`、`ObjectStateV1`、`InjuryStateV1`、`ExpressedStance`；关系维度可包含 structural_relation、interaction_state、trust_state、communication_access；伤势可包含 phase、body_part、visible_markers、treatment、effective_from/effective_until。

暂不进入 Schema 的点：
完整医学本体、复杂所有权本体、完整社会关系本体、关系强度分值、`ResolvedCharacterAppearance` 持久化；`ResolvedCharacterAppearance` 仍作为生成前派生结果。

建议后端/QA 注意：
后端状态编译要按维度和 EvidenceRef 独立更新，不能用 holder 改 owner，不能用 in_use_by 改 holder。QA 要把人物状态错误、道具错误和硬性证据缺失视为 hard failure；同时避免把软性画面质量抵消状态错误。

相关文件：
`docs/reviews/relationship_state_regression_v1.md`；`docs/examples/relationship_state_example.md`；`docs/domain_glossary.md`；`docs/domain_rules.md` 第 8-10 节。

测试结果：
回归评审记录为 V1.2-draft 能表达合作、疏远、不信任、通讯限制、道具临时持有、伤势阶段和临时视觉状态；姜芮是否改动机关、苏闻记忆真实性仍保持 UNVERIFIED/UNCERTAIN。

## 03_complex_timeline

本轮测试：
Golden Corpus V1 `tests/golden_corpus/03_complex_timeline`，聚焦复杂叙述顺序、相对时间、同时/重叠关系、道具未知区间、未知参与者和因果边界。

发现的问题：
`NarrativeOrder` 与 `StoryTime` 必须分离；相对时间需要锚点；`SIMULTANEOUS` 与 `OVERLAPS` 的边界需要明确；同一历史事件可以有多个 `NarrativeMention`；`ObjectState` 的离散状态点之间允许 UNKNOWN interval；actor UNKNOWN / `UnresolvedReference` 需要表达；`BEFORE` 不能自动推出 `CausalRelation`。

采用的修改：
V1.3-draft 补充 `StoryTime` precision、anchor_event、anchor_story_time、candidate_anchors、resolution_status 等语义说明，明确 `TemporalRelation` 中 SIMULTANEOUS/OVERLAPS 边界，补充同一事件多 NarrativeMention、ObjectState UNKNOWN interval、actor UNKNOWN 和 BEFORE 不等于 CausalRelation；示例文档补充相对锚点、监控区间覆盖、铁盒未知流转和未知放回者。

没有采用的修改：
没有新增顶层 `EventCluster` Schema；没有把 `AT_TIME`、`SAME_ANCHOR` 做成正式枚举；没有实现完整自动时间求解器、概率轨迹推断或复杂因果图。

影响 Schema 的候选点：
`StoryTime` 可候选包含 precision、anchor_event、anchor_story_time、candidate_anchors、resolution_status、time_kind、relative_time、time_interval；`TemporalRelation` 可细化 source_interval、target_time_point、relation、derived_note、evidence_refs；Event 可支持 actor=UNKNOWN 或 actor_ref=`UnresolvedReference`。

暂不进入 Schema 的点：
`EventCluster` 顶层概念、`AT_TIME`/`SAME_ANCHOR` 正式枚举、完整自动时间求解器、概率轨迹推断、复杂因果图谱。

建议后端/QA 注意：
后端时间查询必须用 StoryTime，不可按段落顺序推断状态；缺失流转区间要显式 UNKNOWN。QA 要检查相对时间锚点、同时/重叠关系、道具未知区间、未知参与者和因果误判，尤其防止“先后发生”被写成“导致”。

相关文件：
`docs/reviews/complex_timeline_regression_v1.md`；`docs/examples/complex_timeline_example.md`；`docs/domain_glossary.md`；`docs/domain_rules.md` 第 11 节。

测试结果：
回归评审记录为 V1.3-draft 能表达 NarrativeOrder 与 StoryTime 分离、相对时间锚点、SIMULTANEOUS/OVERLAPS 边界、ObjectState 未知区间、actor UNKNOWN 的状态变化事件，以及 BEFORE 不等于 CausalRelation。

## 04_reality_layers

本轮测试：
Golden Corpus V1 `tests/golden_corpus/04_reality_layers`，聚焦梦境、想象、假设、预测模拟、不可靠记忆、现实状态隔离和相似事件/道具误认。

发现的问题：
需要明确 `RealityLayer` 判定矩阵，包括 `PRIMARY`、`DREAM`、`IMAGINATION`、`HYPOTHETICAL`、`FLASHBACK`、`FLASH_FORWARD`、`UNRELIABLE_MEMORY`、`UNKNOWN`。设备画面、角色确信、系统日志标签和 Canonical Data 必须分离；梦中状态不能污染 PRIMARY；梦醒后的恐惧可以进入 PRIMARY；预测模拟优先用 HYPOTHETICAL；相似道具不能自动合并。

采用的修改：
V1.4-draft 统一 `PRIMARY` 作为现实主线命名，补充 RealityLayer 判定矩阵，明确 `UNRELIABLE_MEMORY` 与 `FLASH_FORWARD` 在文档语义中可用，预测模拟用 `HYPOTHETICAL` + source 信息表达；新增跨 RealityLayer 状态隔离和 Claim/系统标签/Canonical Data 分离规则；示例文档补充设备画面、梦醒恐惧、想象交付、候选道具关联、预测模拟和日志冲突。

没有采用的修改：
没有新增正式 `SIMULATION` RealityLayer；没有把设备画面、角色确信、系统日志标签或研究员推测升级为 Canonical 事实；没有让梦中白发、伤口、钥匙污染 PRIMARY。

影响 Schema 的候选点：
`RealityLayer` enum 映射；candidate_layers、source_medium、source_label、verification_status、reliability_reason、evidence_refs；对象身份可候选支持 candidate_link 或 object_identity=UNCERTAIN。

暂不进入 Schema 的点：
`SIMULATION` 正式层级、完整设备可信度模型、日志签名证据等级模型、复杂预言/模拟验证关系。

建议后端/QA 注意：
后端状态编译必须按 RealityLayer 隔离，非 PRIMARY 外貌、伤势、道具不默认写入 PRIMARY。QA 要检查梦境元素污染、预测模拟误当未来事实、系统标签越级、角色确信覆盖对象身份、相似现实事件被误作验证或因果。

相关文件：
`docs/reviews/reality_layers_regression_v1.md`；`docs/examples/reality_layer_example.md`；`docs/domain_glossary.md`；`docs/domain_rules.md` 第 12 节。

测试结果：
回归评审记录为 V1.4-draft 能表达设备画面、梦境、想象、污染记忆、预测模拟、现实状态隔离、相似道具误认、系统日志冲突和 Claim/Canonical Data 分离；合理 UNKNOWN/UNCERTAIN 保留。

## 05_claims_knowledge

本轮测试：
Golden Corpus V1 `tests/golden_corpus/05_claims_knowledge`，聚焦未经证实指控、否认、猜测、暗示、读者可见事实、人物 KnowledgeState、ObjectState 未知移动链和冲突 Agent Proposal。

发现的问题：
未经证实指控、否认、猜测、暗示和 Agent Proposal 不能升级为 Canonical；读者可见事实与人物 KnowledgeState 必须分离；后续证据不能反向修改历史 KnowledgeState；ObjectState 只能记录被证据支持的位置/持有状态，不能补偷窃或栽赃；未知参与者应使用 UnresolvedReference 或 actor=UNKNOWN；CommitService 面对冲突 Proposal 只能提交中性已证事实。

采用的修改：
V1.5-draft 强化 Claim、KnowledgeState、NarrativePerspective 与 Canonical Data 的边界，补充读者可见事实不等于角色知道、后续证据不反向改写历史认知、ObjectState 不自动补全移动链、CommitService 保留冲突 Proposal 并只提交中性事实；新增 05 回归评审和 claims/knowledge 示例。

没有采用的修改：
没有新增 ReaderKnowledge、ReaderVisibleFact、ObjectIdentity 顶层概念；没有实现 Schema、Agent 或数据库；没有把角色指控、猜测、暗示、否认或 Agent Proposal 升级为 Canonical 事实。

影响 Schema 的候选点：
`Claim.verification_status`、`KnowledgeState.visible_to_character_ids` 或相关可见性字段、`NarrativePerspective.visible_to_reader`、`Proposal.conflict_group`、`CommitResult` 冲突/审核状态、`ObjectState` 未知移动链表达。

暂不进入 Schema 的点：
完整自动真相裁决、复杂嫌疑推理、完整证据等级模型、ReaderKnowledge 顶层概念、ObjectIdentity 顶层概念。

建议后端/QA 注意：
后端 CommitService 不得在互斥 Proposal 中选边提交，只能提交证据支持的中性事实并保留冲突。QA 要检查 Claim 越级、读者知识泄漏、后续证据回填历史 KnowledgeState、ObjectState 自动补偷窃/栽赃、未知参与者被强行新建 Character。

相关文件：
`docs/reviews/claims_knowledge_regression_v1.md`；`docs/examples/claims_knowledge_example.md`；`docs/domain_glossary.md`；`docs/domain_rules.md` 第 13 节。

测试结果：
回归评审记录为 V1.5-draft 能表达未经证实 Claim、读者可见事实与人物知识分离、历史 KnowledgeState 不回填、未知参与者、ObjectState 未知移动链和冲突 Proposal 提交纪律；合理 UNKNOWN/UNCERTAIN/UNRESOLVED 保留。

## 06_storyboard_qa

本轮测试：
Golden Corpus V1 `tests/golden_corpus/06_storyboard_qa`，聚焦 Scene 粒度、StoryBeat-to-Panel 拆分、PanelSpec must_show/must_not_show、关键 DialogueUnit、回忆状态绑定、ObjectState 结束态、QAIssue hard failure 和 RepairPlan 策略。

发现的问题：
Scene 粒度规则需要更显眼，尤其 RealityLayer 改变、StoryTime 跳跃、地点明显改变和过渡段弹性；StoryBeat 不是 Panel，连续动作若包含多个关键时刻、信息揭示或物体转移不能随意压成一格；must_show/must_not_show 是故事忠实度硬约束；回忆画面不能被当前 CharacterState 污染；关键对白必须逐字保留；ObjectState 结束态不能静默延续旧 holder；hard failure 不能被视觉质量抵消；RepairPlan 策略和关键道具颜色/材质严重性阈值需要补清。

采用的修改：
V1.6-draft 补充 Storyboard QA、PanelSpec、QAIssue 和 RepairPlan 语义，细化 Scene、StoryBeat、DialogueUnit、CharacterVisualVariant、VisualAsset、PanelSpec、ObjectState、QAIssue 和 RepairPlan 的边界；`docs/domain_rules.md` 新增第 14 节；新增地下展厅示例和 06 回归评审文档。

没有采用的修改：
没有修改 `tests/golden_corpus/06_storyboard_qa/source.md`、`questions.md` 或 `expected.json`；没有实现 PageSpec、PanelSpec、QAResult、QAIssue、RepairPlan 完整 Schema；没有新增真实 QA Agent、图像局部重绘、整格重生成或完整 VisualBible/VisualAsset 管理系统；没有一次性固定完整 QAIssue issue_type 枚举。

影响 Schema 的候选点：
Scene 粒度标记、StoryBeat-to-Panel 映射、多时刻 Panel 或 motion_line 表达、PanelSpec.must_show/must_not_show、DialogueUnit echo/repetition 关系、ObjectState 结束态校验、QAIssue severity/hard_failure/issue_type、RepairPlan repair_type/target_region/recheck_required、关键道具视觉属性约束。

暂不进入 Schema 的点：
完整 PageSpec/PanelSpec/QAResult/QAIssue/RepairPlan Schema 实现、真实 QA Agent、真实图像修复能力、完整 QAIssue issue_type 枚举、完整 VisualBible 和 VisualAsset 管理系统。

建议后端/QA 注意：
后端在生成 PanelSpec 时要按 Scene 的 StoryTime、RealityLayer 和 Location 查询状态，不能让回忆和现实状态混用。QA 要把人物状态错误、关键道具缺失、must_not_show 违反、关键对白错误和关键道具材质错误按 hard failure 优先处理；视觉质量只能影响软性评分，不能抵消故事事实错误。

相关文件：
`docs/reviews/storyboard_qa_regression_v1.md`；`docs/examples/storyboard_qa_example.md`；`docs/domain_glossary.md`；`docs/domain_rules.md` 第 14 节。

测试结果：
回归评审记录为 V1.6-draft 能表达 Scene 切分、StoryBeat-to-Panel 拆分、must_show/must_not_show、关键 DialogueUnit、回忆状态绑定、ObjectState 结束态、QAIssue hard failure 和 RepairPlan 策略；Q1、Q14、Q15 仍保留阈值弹性，不进入完整 Schema 实现。

## 07_integrated_novel

本轮测试：
Golden Corpus V1 `tests/golden_corpus/07_integrated_novel`，聚焦身份、共享账号、复杂时间线、RealityLayer、Claim/Knowledge、ObjectState、Storyboard QA、DependencyEdge / STALE 和综合链路一致性。

发现的问题：
共享账号、账号名、主要使用者和消息作者容易被误合并；NarrativeOrder、StoryTime、RealityLayer、NarrativePerspective 在倒叙、梦境、Gu POV 和未来片段中需要联合判断；同一历史夜晚会被记录、录像、录音、回忆和角色 Claim 多次提及；读者可见事实不能泄漏为人物 KnowledgeState；DREAM 与不确定未来片段不能污染 PRIMARY；临时安全背心、铜钥匙 holder、顾舟伤势等状态必须有结束态；冲突 Claim 和记忆 Claim 不能升级为 Canonical；上游事实变更需要让下游分镜、提示、视觉资产、QA 和 RepairPlan 过期或重算。

采用的修改：
`docs/domain_glossary.md` 更新为 V1.7-draft，补充共享账号、账号作者候选、同一历史事件多 NarrativeMention、Gu POV 可见性、P37 RealityLayer UNKNOWN/candidate_layers、ObjectState 离散状态与临时装备结束态、QAIssue dependency_mismatch 和 DependencyEdge / STALE 语义；`docs/domain_rules.md` 新增第 15 节综合小说链路一致性规则；新增 07 钟楼综合示例和 07 回归评审文档。

没有采用的修改：
没有修改 `tests/golden_corpus/07_integrated_novel/source.md`、`questions.md` 或 `expected.json`；没有新增 TemporalGraph、StoryBible、VisualBible、AUTHOR_FORESHADOW、完整 DependencyGraph 或证据排名系统；没有实现共享账号归因算法、真相裁决器、Schema、Agent、数据库、真实 QA、真实图像修复或自动最优 RepairPlan。

影响 Schema 的候选点：
Account shared_access / primary_operator、AuthorshipClaim candidate_author_ids / excluded_author_ids / scheduled_send_status、NarrativePerspective visible_to_reader / visible_to_character_ids、RealityLayer candidate_layers、StoryTime / RealityLayer 联合状态查询、ObjectState UNKNOWN interval 和 effective_until、QAIssue dependency_mismatch / stale_reason、DependencyEdge stale_status / recompute_required。

暂不进入 Schema 的点：
TemporalGraph、EventCluster 顶层概念、AUTHOR_FORESHADOW RealityLayer、完整共享账号作者归因、复杂嫌疑/动机推理、沈岑最终去向裁决、完整证据等级排名、完整 DependencyGraph、自动重算调度和自动最优 RepairPlan。

建议后端/QA 注意：
后端在查询人物、关系、道具和视觉状态时必须同时带 StoryTime 与 RealityLayer；共享账号消息只提交可见发送方和候选作者，不直接绑定人物。QA 要把 RealityLayer 混用、梦境污染、临时装备静默延续、关键 ObjectState 过期、must_show/must_not_show 错误和上游依赖过期当作 hard failure 或 STALE 风险处理。

相关文件：
`docs/reviews/integrated_novel_regression_v1.md`；`docs/examples/integrated_novel_example.md`；`docs/domain_glossary.md`；`docs/domain_rules.md` 第 15 节。

测试结果：
回归评审记录为 V1.7-draft 能表达 07 的综合链路问题；共享账号真实作者、Q-Zhou 操作者、P37 真实层级、沈岑最终去向和完整依赖图仍保持 UNKNOWN/UNCERTAIN 或 MVP 暂缓。

## 08_campus_factlock

本轮测试：
Golden Corpus V1 `tests/golden_corpus/08_campus_factlock`，聚焦通知、公告和海报类文本的事实锁定，包括多版本通知、字段级 Revision、过期海报 STALE、数字单位、近似姓名、地点分离、日期/星期和 text_accuracy。

发现的问题：
报名截止、材料截止、报到、开幕、展示和决赛日期容易被混成一个时间字段；最终有效事实必须来自最新有效 Revision 并保留 EvidenceRef；旧海报、旧通知和旧视觉资产中的过期字段需要 STALE；队伍数、学生数、奖项支数和视频时长的单位不能改写；周舟老师和周洲副院长不能因读音相近合并；报到地点和主会场不能混画；“不变”需要字段级确认；信息省略是否 hard failure 取决于 PanelSpec 目标。

采用的修改：
`docs/domain_glossary.md` 更新为 V1.8-draft，新增 FactLock 文档层概念，并补充 Canonical Data、Revision、EvidenceRef、Character、Location、EntityMention、PanelSpec、QAIssue、DependencyEdge 的通知类事实锁定边界；`docs/domain_rules.md` 新增第 16 节通知类事实锁定规则；新增校园智能体创意赛 FactLock 示例和 08 回归评审文档。

没有采用的修改：
没有修改 `tests/golden_corpus/08_campus_factlock/source.md`、`questions.md` 或 `expected.json`；没有实现 FactLockV1 Schema、字段级 Revision 数据库、完整通知解析 Agent、真实 QA Agent、完整日历校验器、完整 QAIssue issue_type 枚举或公告管理系统。

影响 Schema 的候选点：
FactLockV1、PanelSpec.fact_locks、QAResult.fact_lock_checks、Canonical 字段级 revision_status、Revision action 枚举、EvidenceRef 多来源确认、DependencyEdge stale_reason、QAIssue text_accuracy/completeness/stale_fact 类型、Location 层级字段、Contact/role 字段。

暂不进入 Schema 的点：
FactLockV1 正式实现、字段级 Revision 数据库、通知解析 Agent、日历校验器、公告管理系统、完整联系人本体、完整 QAIssue issue_type 枚举和真实 QA 自动修复。

建议后端/QA 注意：
后端处理通知类文本时要按字段更新 Canonical Data，不要整份覆盖或整份继承；“不变”要同时引用初版具体值和更正说明。QA 要将日期/星期、地点、数字单位、人名、电话、邮箱和流程规则作为 text_accuracy 高优先级检查；旧海报或旧视觉资产继续使用过期字段时，应标记 STALE 或 hard failure。

相关文件：
`docs/reviews/campus_factlock_regression_v1.md`；`docs/examples/campus_factlock_example.md`；`docs/domain_glossary.md`；`docs/domain_rules.md` 第 16 节。

测试结果：
回归评审记录为 V1.8-draft 能表达 08 的通知类事实锁定问题；FactLock、字段级 Revision 和信息省略边界只进入文档层，未进入 Schema、Agent、数据库或真实 QA 实现。

## micro_cases

本轮测试：
Golden Corpus V1 `tests/golden_corpus/micro_cases`，覆盖 30 个微型边界案例，聚焦同一事件多次叙述、梦境隔离、临时状态、Claim/Proposal、共指、账号、回忆、预测、同时不同地点、相对时间、ObjectState、KnowledgeState、RelationshipState、PanelSpec、QA、UNKNOWN/UNCERTAIN、因果、不可靠记忆、精确对白、STALE，以及连续跨地点动作和 story-within-story。

发现的问题：
Q01-Q17、Q19-Q29 当前 V1.8-draft 基本足够，只需归档回归结果。Q18 暴露连续动作跨地点时 Scene 粒度需要补清：地点变化通常是强切分信号，但追逐、移动、搬运、交接等动作可用相邻 Scene、StoryBeat 序列和 PanelSpec 连续动作说明保持连贯。Q30 暴露 story-within-story 边界需要补清：童话、寓言、剧本、小说片段等不进入 PRIMARY 主线 Canonical Event，嵌入故事中的 Entity/Event/ObjectState 与主线隔离。

采用的修改：
`docs/domain_glossary.md` 更新为 V1.9-draft，补充 Scene、StoryBeat、RealityLayer、NarrativePerspective、Event、Entity、Canonical Data、PanelSpec、QAIssue 的 micro case 边界；`docs/domain_rules.md` 新增第 17 节 Micro Case 边界校准规则；新增 micro_cases 边界示例和 Q01-Q30 回归评审文档。

没有采用的修改：
没有修改 `tests/golden_corpus/micro_cases/*.md`；没有自动填写 expected.json；没有实现 ActionSequenceV1、EmbeddedNarrativeScopeV1、FICTIONAL_STORY RealityLayer、自动 Scene 切分器、故事内故事实体库、完整 Panel 连续动作求解器、Schema、Agent、数据库或真实 LLM。

影响 Schema 的候选点：
Scene/StoryBeat 可候选支持 `continuous_action_group`、`continuous_action_note`、相邻 Scene 关系；PanelSpec 可候选支持逐格 `location_id` 校验和连续动作说明；RealityLayer 可候选继续支持 candidate_layers；QAIssue 可候选支持 `location_state_mismatch`、`scene_boundary_error`、`continuity_loss`、`reality_layer_leakage`、`entity_scope_mismatch`。

暂不进入 Schema 的点：
ActionSequenceV1、EmbeddedNarrativeScopeV1、FICTIONAL_STORY RealityLayer、故事内故事实体库、完整自动 Scene 切分器、完整 Panel 连续动作求解器和完整 QAIssue issue_type 枚举。

建议后端/QA 注意：
后端不要为了连续动作把不同 LocationState 合成一个地点；相邻 Scene 可用 StoryBeat 序列或候选 continuous_action_group 保持连续。QA 要同时检查动作连贯性和每格 location_id 准确性。故事内故事可视觉化，但嵌入实体和事件不得进入 PRIMARY 主线 StoryBible 或 Canonical Event。

相关文件：
`docs/reviews/micro_cases_regression_v1.md`；`docs/examples/micro_cases_boundary_example.md`；`docs/domain_glossary.md`；`docs/domain_rules.md` 第 17 节。

测试结果：
回归评审记录为 V1.9-draft 能表达 micro_cases 的 30 个边界案例；Q18 和 Q30 的歧义已做文档层最小修订；合理 UNKNOWN/UNCERTAIN 保留；未进入 Schema、Agent、数据库或自动化实现。

## 05以后维护规则

1. 每完成一篇 Golden Corpus 测试，必须在本文件追加同格式摘要。
2. 追加位置在对应编号小节之后，例如完成 05 后新增 `## 05_claims_knowledge`。
3. 摘要只写团队交接信息，不替代详细 review 文档。
4. 详细问题、EvidenceRef 和 Q1-Q15 表格仍写入独立 `docs/reviews/*_regression_v1.md`。
5. 不要把 Codex 回答直接写入 `expected.json`。
6. 如果某轮没有修改 glossary/rules，也要说明“未修改领域定义，仅记录模型未遵守定义或证据不足”。
7. 每轮摘要必须明确：
   - 哪些点影响 Schema；
   - 哪些点暂不进入 Schema；
   - 后端需要注意什么；
   - QA 需要注意什么；
   - 是否修改了 Schema、Agent、数据库。
