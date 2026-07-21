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
