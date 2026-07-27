# Integrated Novel Regression V1

测试范围：`tests/golden_corpus/07_integrated_novel`

定义基线：`docs/domain_glossary.md` V1.7-draft、`docs/domain_rules.md` 第 15 节综合小说链路一致性规则，以及 01-06 已建立的身份、关系、时间线、RealityLayer、Claim/Knowledge、Storyboard QA 规则。

总体结论：本轮无硬 Definition Gap。07 是综合压力测试，主要暴露已有概念在长链路中需要更显眼的执行纪律：共享账号不等于人物，读者可见不等于角色所知，梦境和不确定未来片段不污染 PRIMARY，临时状态必须结束，冲突 Claim 不得升级为 Canonical，DependencyEdge / STALE 需要文档层语义。适合做 V1.7-draft 最小文档修订，不进入完整 Schema、Agent、数据库、真实 QA 或图像修复实现。

| 问题编号 | 结论 | 原文依据 | 涉及对象 | 确定性 | 是否 Definition Gap | 是否 Ambiguous Definition | 是否影响 Schema 候选 | 备注 |
|---|---|---|---|---|---|---|---|---|
| Q1 | 共享账号、账号名和人物身份必须分离 | P03, P09, P21, P22, P29, P36 | Character, Account, EntityAlias, EntityMention, UnresolvedReference, AuthorshipClaim | HIGH | 否 | 否 | 是 | 白栖、Q-Zhou、Q 都不能直接合并为 Character。 |
| Q2 | NarrativeOrder 不能替代 StoryTime，必须结合 RealityLayer 与 Perspective | P01-P10, P19-P20, P37 | NarrativeOrder, StoryTime, RealityLayer, NarrativePerspective | HIGH | 否 | 否 | 是 | 需要在综合链路中持续检查四者边界。 |
| Q3 | 多次叙述同一历史夜晚不重复建 Canonical Event | P05-P07, P18-P25, P32-P33 | Event, NarrativeMention, Claim | HIGH | 否 | 否 | 否 | 记录、录像、录音、回忆各自形成 mention/claim/evidence。 |
| Q4 | 录像、录音、记录是证据或 Message，不等于完整历史事实 | P21, P23-P24, P32 | EvidenceRef, Message, Event, Claim | HIGH | 否 | 否 | 是 | 只提交其直接支持的事实范围。 |
| Q5 | CharacterState 必须按 StoryTime + RealityLayer 查询 | P02, P05, P10-P12, P16, P34 | CharacterState, InjuryState, RealityLayer | HIGH | 否 | 否 | 是 | 2023、2030、DREAM、2031 状态互不污染。 |
| Q6 | ObjectState 必须记录结束态和 UNKNOWN interval | P03, P15-P17, P25-P28, P34 | ObjectState, StoryObject, RealityLayer | HIGH | 否 | 否 | 是 | 安全背心归还、钥匙转移、学生证位置都不能静默延续或过度推断。 |
| Q7 | 冲突指控与记忆仍是 Claim | P18, P25-P26 | Claim, Canonical Data, CommitService | HIGH | 否 | 否 | 是 | 周璐前后说法冲突，不提交“顾舟捡钥匙”为事实。 |
| Q8 | Gu POV 记忆不等于 Canonical DialogueUnit | P19-P20 | NarrativePerspective, Claim, DialogueUnit | HIGH | 否 | 否 | 是 | 顾舟记忆中的沈岑原话先保留为 MEMORY Claim。 |
| Q9 | reader_visible 不等于 character_known | P04, P19-P21, P33 | NarrativePerspective, KnowledgeState | HIGH | 否 | 否 | 是 | 沈雾和周璐不能提前知道顾舟副本。 |
| Q10 | DREAM 不污染 PRIMARY，但可触发现实怀疑 | P10-P11, P30 | RealityLayer, Claim, KnowledgeState, ObjectState | HIGH | 否 | 否 | 是 | 梦中钥匙转移无 PRIMARY ObjectState 效果。 |
| Q11 | 共享账号消息作者保持候选或 UNRESOLVED | P03, P09, P21-P22, P29, P36 | Account, AccountAccessRelation, AuthorshipClaim | HIGH | 否 | 否 | 是 | 三人在场不能排除定时或预设消息。 |
| Q12 | P25-P27 关键动作需拆分或显式 must_show | P25-P27 | Scene, StoryBeat, PanelSpec, ObjectState | HIGH | 否 | 是 | 是 | 钥匙取出、交接、放入槽、墙体开启不可糊成一格。 |
| Q13 | 关键 Panel 必须含 must_not_show 约束 | P25-P27, P30 | PanelSpec, RealityLayer, ObjectState | HIGH | 否 | 否 | 是 | 不得把梦中丢钥匙或旧 holder 带入现实格。 |
| Q14 | Scene/StoryBeat 粒度在综合段落仍需保留弹性 | P25-P27 | Scene, StoryBeat, PanelSpec | MEDIUM | 否 | 是 | 是 | 粒度阈值仍属 QA 校准点。 |
| Q15 | RealityLayer 混用是 QA hard failure | P10-P11, P30 | QAIssue, QAResult, RealityLayer | HIGH | 否 | 否 | 是 | 梦境状态污染现实不能被画面质量抵消。 |
| Q16 | 临时装备状态延续错误是 QA hard failure | P03, P34 | ObjectState, QAIssue, RepairPlan | HIGH | 否 | 否 | 是 | 归还安全背心后仍穿着是状态过期。 |
| Q17 | 继续调查不等于信任恢复或原谅 | P31, P35 | RelationshipState, ExpressedStance, Claim | HIGH | 否 | 否 | 是 | “继续查”不是 forgiveness。 |
| Q18 | 学生证 + 外套不能证明死亡 | P28, P38 | EvidenceRef, ObjectState, Claim | HIGH | 否 | 否 | 否 | 只确认物件位置和身份线索。 |
| Q19 | 录像只证明 23:06 离开泵房 | P32-P33, P38 | EvidenceRef, Event, KnowledgeState | HIGH | 否 | 否 | 否 | 不证明 23:06 后最终去向。 |
| Q20 | timed message 不排除预设作者 | P36 | Message, AuthorshipClaim, AccountAccessRelation | HIGH | 否 | 否 | 是 | 共同在场不是排除证据。 |
| Q21 | P37 不新增 AUTHOR_FORESHADOW，保留 UNKNOWN/candidate_layers | P37 | RealityLayer, NarrativePerspective | MEDIUM | 否 | 是 | 是 | FLASH_FORWARD 仅在明确真实未来时使用。 |
| Q22 | EvidenceRef 与 UNKNOWN/UNCERTAIN 需要范围化 | P21-P24, P28, P32-P38 | EvidenceRef, Confidence, Canonical Data | HIGH | 否 | 否 | 是 | 每条证据只支持直接结论。 |
| Q23 | 上游事实变更需标记下游 STALE | P25-P27, P34 | DependencyEdge, PanelSpec, PromptSpec, QAResult, RepairPlan | MEDIUM | 否 | 是 | 是 | V1.7 只做文档语义，不实现完整 DependencyGraph。 |
| Q24 | 下游错误传播应作为 QA 风险处理 | P10-P11, P30, P34 | QAIssue, RepairPlan, DependencyEdge | HIGH | 否 | 否 | 是 | 错误 RealityLayer 或 ObjectState 会污染视觉生产。 |
| Q25 | 多个悬疑裁决超出 MVP | P18, P21-P22, P28-P38 | CommitService, Claim, KnowledgeState | HIGH | 否 | 否 | 否 | 不自动裁决共享账号作者、最终去向或完整嫌疑链。 |

## 07 主题结论

- 本轮主要是综合链路执行纪律，不需要新增顶层领域概念。
- 共享账号、账号名、主要使用者和具体消息作者必须通过 Account、AccountAccessRelation、AuthorshipClaim 与 UnresolvedReference 拆开。
- 同一历史夜晚可由多个 NarrativeMention、Claim、记录、录像和录音共同引用，不因此复制 Canonical Event。
- CharacterState、ObjectState 和 KnowledgeState 必须同时绑定 StoryTime 与 RealityLayer；后续证据不能回填历史认知。
- DREAM 与不确定未来片段不能污染 PRIMARY；P37 暂用 UNKNOWN + candidate_layers，不新增 AUTHOR_FORESHADOW。
- DependencyEdge / STALE 是 Schema 候选语义，但完整 DependencyGraph 与自动重算调度暂缓。

## 微型回归测试建议

- 复查共享账号作者归属与账号名歧义：`05_ambiguous_pronoun.md`、`24_proposal_conflict.md`。
- 复查读者可见信息不泄漏到角色知识：`15_knowledge_leak.md`。
- 复查 RealityLayer 与梦境状态隔离：`02_dream_state_leak.md`、`27_unreliable_memory_partial.md`。
- 复查相似时间或先后不自动推出因果：`26_causality_vs_precedence.md`。
- 复查状态变更后的下游重算：`29_dependency_stale_recompute.md`。

## 剩余问题

- 是否在后续 Schema 中显式加入 `candidate_layers`、`candidate_author_ids`、`scheduled_send_status`、`stale_status` 等字段，需要 Schema 轮次单独评审。
- 是否实现完整 DependencyGraph、证据等级排名、嫌疑推理或自动 RepairPlan 策略，均超出 V1.7 文档修订范围。
- P37 的叙事性质仍保持 UNKNOWN/UNCERTAIN；不以文档方式替作者或模型裁决。
