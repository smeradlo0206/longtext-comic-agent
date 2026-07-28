# Claims Knowledge Regression V1

测试范围：`tests/golden_corpus/05_claims_knowledge`

定义基线：`docs/domain_glossary.md` V1.5-draft 与 `docs/domain_rules.md` 中 Claim、KnowledgeState、NarrativePerspective、ObjectState、CommitService 相关规则。

总体结论：本轮无硬 Definition Gap，主要是强化 Claim / KnowledgeState / Canonical Data / CommitService 的执行纪律。现有概念可以表达未经证实指控、读者可见事实、角色知识边界、未知参与者、ObjectState 未知移动链和冲突 Proposal。

| 题号 | 结论 | EvidenceRef | 使用概念 | 确定性 | Definition Gap | Ambiguous Definition | 备注 |
|---|---|---|---|---|---|---|---|
| Q1 | “程放拿卡”只能作为林祁的 ACCUSATION Claim 或 Agent Proposal，不能直接提交 Canonical Event。 | P02, P12 | Claim, Proposal, Canonical Data, Event | 高 | 否 | 否 | Canonical 只支持“有人在停电前拿走门禁卡”。 |
| Q2 | 林祁的指控不能改变门禁卡 ObjectState。 | P01, P02, P04 | Claim, ObjectState | 高 | 否 | 否 | 只能记录原在值班桌、后在林祁外套；中间 UNKNOWN。 |
| Q3 | 灰外套人应记录为 EntityMention 或 UnresolvedReference，不新建 Character。 | P03 | EntityMention, UnresolvedReference | 高 | 否 | 否 | 程放和林祁都穿灰外套，身份不足。 |
| Q4 | 门禁卡从林祁外套掉出只确认该时间点位置/holder。 | P04 | ObjectState, EvidenceRef | 高 | 否 | 否 | 不证明偷窃、栽赃、动机或移动路径。 |
| Q5 | 证明林祁偷卡需要直接行为、时间、意图、路径或排他性机会等证据。 | P04, P05, P12 | Claim, ObjectState, UNKNOWN | 高 | 否 | 否 | 当前证据不足，应保持 UNCERTAIN。 |
| Q6 | 读者可见黑手套拿卡可进入 Canonical/StoryBible，但不进入角色 KnowledgeState。 | P06 | NarrativePerspective, KnowledgeState, Canonical Data | 中高 | 否 | 是 | 需要强化 reader_visible 与 visible_to_character_ids 边界。 |
| Q7 | 黑手套手不是独立 Character，只能是 actor=UNKNOWN 或 UnresolvedReference。 | P06 | Event, UnresolvedReference | 高 | 否 | 否 | 不能仅凭身体局部新建人物。 |
| Q8 | 沈策知道备用出口，学生当时不知道。 | P07 | KnowledgeState | 高 | 否 | 否 | 隐瞒信息不得自动传播。 |
| Q9 | 周芮当时是猜测/怀疑，后续监控不能反向改为 KNOWS。 | P08 | Claim, KnowledgeState, StoryTime | 中高 | 否 | 是 | 需显眼化历史 KnowledgeState 不回填规则。 |
| Q10 | 维修单信息只传播给程放和沈策，不自动传播给其他人。 | P09 | KnowledgeState, NarrativePerspective | 高 | 否 | 否 | 沈策宣布结果可改变公开知识，但不公开维修单细节。 |
| Q11 | 林祁的暗示是 Claim 或 ExpressedStance，不生成可验证因果链。 | P10 | Claim, CausalRelation | 高 | 否 | 否 | 没有说明“为什么”，缺少可验证内容。 |
| Q12 | 湿黑手套与拿卡黑手套只能保持候选关联。 | P06, P11, P12 | StoryObject, ObjectState, Claim | 中 | 否 | 否 | 外观相似不足以合并。 |
| Q13 | “有人拿卡”可确认，参与者保持 UNKNOWN。 | P06, P12 | Event, UnresolvedReference | 高 | 否 | 否 | actor=UNKNOWN。 |
| Q14 | 冲突 Agent Proposal 应由 CommitService 保留冲突并提交中性事实。 | P02, P04, P06, P12 | Proposal, CommitService, Claim | 中高 | 否 | 是 | 需要补充冲突 Proposal 的提交规则。 |
| Q15 | 需分离读者可见事实、角色知识、猜测和未证实 Claim。 | P02-P12 | NarrativePerspective, KnowledgeState, Claim, Canonical Data | 中高 | 否 | 是 | 不新增 ReaderKnowledge 顶层概念。 |

## 05 主题结论

- 指控、否认、猜测、暗示、调查推论和 Agent Proposal 都不能直接升级为 Canonical Data。
- 读者可见事实可以作为客观叙述证据进入 StoryBible / Canonical Data，但不自动进入任何 Character 的 KnowledgeState。
- 后续证据只能确认事实本身，不能反向修改角色在过去 StoryTime 的认知状态。
- ObjectState 只记录证据支持的位置、holder、owner、condition 等，不补全偷窃、栽赃、动机或未知移动链。
- 参与者未知时使用 actor=UNKNOWN 或 UnresolvedReference，合理保留 UNKNOWN / UNCERTAIN / UNRESOLVED。
- CommitService 面对互斥 Proposal 时只提交中性已证事实，并保留冲突或生成审核项。

## 微型回归测试建议

- `tests/golden_corpus/micro_cases/04_false_claim_not_fact.md`
- `tests/golden_corpus/micro_cases/05_ambiguous_pronoun.md`
- `tests/golden_corpus/micro_cases/15_knowledge_leak.md`
- `tests/golden_corpus/micro_cases/24_proposal_conflict.md`
- `tests/golden_corpus/micro_cases/25_unknown_vs_uncertain.md`
- `tests/golden_corpus/micro_cases/26_causality_vs_precedence.md`
- `tests/golden_corpus/micro_cases/27_unreliable_memory_partial.md`

## 剩余问题

- `Claim.verification_status`、`KnowledgeState.visible_to_character_ids`、`Proposal.conflict_group` 和 `CommitResult` 审核状态可作为后续 Schema 候选。
- 完整自动真相裁决、复杂嫌疑推理、完整证据等级模型和 ReaderKnowledge 顶层概念暂缓。
- 本轮未修改 Schema、Agent 或数据库。
