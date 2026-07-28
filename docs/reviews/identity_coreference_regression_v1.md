# Identity Coreference Regression V1

测试范围：Golden Corpus V1 `tests/golden_corpus/01_identity_coreference`，并复测指定微案例。  
定义基线：`docs/domain_glossary.md` V1.1-draft 与 `docs/domain_rules.md` 第 7 节。  
结论：V1.1-draft 已消除身份层级、账号/消息、Claim、KnowledgeState、NarrativePerspective 和未解析群体的定义缺口。部分答案仍保持 UNKNOWN、UNCERTAIN 或 UNRESOLVED，这是证据不足导致，不是定义缺失。

## Q1-Q15 回归结果

| 题号 | 结论 | EvidenceRef | 新术语使用 | 状态 | Definition Gap | Ambiguous Definition |
|---|---|---|---|---|---|---|
| Q1 | 可确认 Characters：唐宁、林乔、乔临、赵衡、齐桥。林乔与“乔姐”“林助教”可建 EntityAlias；“小林”需按上下文处理。林乔与乔临不得合并。 | P02、P07、P10、P11 | Character、EntityAlias、EntityMention、UnresolvedReference | CONFIRMED | 否 | 否 |
| Q2 | “灰桥”在 P01 是署名/文本提及或作者线索，P08/P09 是论坛 Account。只能确认乔临经营论坛账号，不能确认第一张照片作者。 | P01、P08、P09、P11 | Account、Message、AuthorshipClaim、EntityMention | UNCERTAIN | 否 | 否 |
| Q3 | “北岸”应建为邮件 Account；邮件真实发送者保持 UNKNOWN，不能合并为 Character。 | P04 | Account、Message、AuthorshipClaim、UnresolvedReference | UNKNOWN | 否 | 否 |
| Q4 | P05 的“她”是 EntityMention，候选包括唐宁、林乔等；证据不足，保持 UnresolvedReference。 | P05 | EntityMention、UnresolvedReference、NarrativePerspective | UNCERTAIN | 否 | 否 |
| Q5 | P07 “小林”不能作为稳定全局 EntityAlias；P10 支持它通常指林乔，但 P07 同时回头导致该处仍需上下文解析。 | P07、P10 | EntityMention、EntityAlias、UnresolvedReference | UNCERTAIN | 否 | 否 |
| Q6 | 可确认乔临经营论坛账号“灰桥”；林乔知道密码可作为 SUPPORTED 的 AccountAccessRelation；第一张照片作者和署名 Q 邮件发送者仍未确认。 | P09、P10、P11 | AccountAccessRelation、AuthorshipClaim、Claim | CONFIRMED/UNRESOLVED | 否 | 否 |
| Q7 | “第一张照片发布者”“Q 邮件发送者”“论坛账号经营者”是三个独立身份问题，不能相互覆盖。 | P01、P04、P08、P09、P11 | Account、Message、AuthorshipClaim | CONFIRMED | 否 | 否 |
| Q8 | 灰色指环是弱证据，只能支持 HYPOTHESIS Claim，不能确认林乔发送照片。 | P06 | Claim、AuthorshipClaim、EvidenceRef | UNCERTAIN | 否 | 否 |
| Q9 | “他们”应保持 UnresolvedGroupReference，不得默认解析为 Organization。 | P07、P08 | UnresolvedGroupReference、Organization | UNKNOWN | 否 | 否 |
| Q10 | 发布时间与乔临对话重叠不足以排除乔临；定时发布是 HYPOTHESIS Claim，仍 UNVERIFIED。 | P08 | Claim、AuthorshipClaim、AccountAccessRelation | UNCERTAIN | 否 | 否 |
| Q11 | 唐宁草稿从“灰桥警告我”改为“尚未确认身份的人”，说明角色把未验证 Claim 从 Canonical Fact 中撤回。 | P12 | Claim、KnowledgeState、Canonical Data | CONFIRMED | 否 | 否 |
| Q12 | 难点包括林乔别名、林乔/乔临近音、账号经营者与消息作者分离、Q 的多候选。新定义均可承载。 | P02、P04、P07、P09、P10、P11 | EntityAlias、Account、AuthorshipClaim、UnresolvedReference | CONFIRMED | 否 | 否 |
| Q13 | 唐宁的 KnowledgeState 随线索更新：见照片后不知道作者；收邮件后 HEARD 邮件 Claim；见登录后 KNOWS 乔临经营账号；结尾仍不知道照片作者。 | P01、P04、P09、P11、P12 | KnowledgeState、EpistemicStatus、Claim | CONFIRMED | 否 | 否 |
| Q14 | 读者、唐宁、林乔、乔临的知识不能混用。匿名邮件和受限听觉场景必须由 NarrativePerspective 限定可见性。 | P04、P05、P11、P12 | NarrativePerspective、KnowledgeState | CONFIRMED | 否 | 否 |
| Q15 | 新定义已经区分 Account、Character、Message、AccountAccessRelation 和 AuthorshipClaim，可回答账号/作者身份题。 | P01、P04、P08、P09 | Account、Message、AuthorshipClaim | CONFIRMED | 否 | 否 |

## 微案例复测

| 微案例 | 已解决的定义问题 | 仍保持 UNKNOWN/UNCERTAIN | 冲突 |
|---|---|---|---|
| 05_ambiguous_pronoun.md | EntityMention 与 UnresolvedReference 可表达歧义代词，不再把代词当 EntityAlias。 | 当候选代词对象缺少唯一证据时仍 UNKNOWN 或 UNCERTAIN。 | 无定义冲突。 |
| 06_alias_confirmed.md | EntityAlias 的 CONFIRMED/PROPOSED/REJECTED 状态可区分已确认别名和候选别名。 | 弱证据昵称仍只能 PROPOSED。 | 无定义冲突。 |
| 07_similar_names_not_merge.md | 近音、同名和拼写相似被明确排除为自动合并依据。 | 需要额外行为、关系或直接说明才能确认合并。 | 无定义冲突。 |
| 15_knowledge_leak.md | KnowledgeState、EpistemicStatus 与 NarrativePerspective 可阻止读者信息泄漏给角色。 | 角色是否真正知道某 Claim 仍取决于原文证据。 | 无定义冲突。 |
| 24_proposal_conflict.md | Claim verification_status 与 Proposal/Canonical Data 边界可保留互斥主张。 | 未审核冲突保持 UNRESOLVED。 | 无定义冲突。 |
| 25_unknown_vs_uncertain.md | UnresolvedReference、AuthorshipClaim 和 verification_status 区分 UNKNOWN、UNCERTAIN、UNRESOLVED。 | 完全无候选用 UNKNOWN；有候选但证据不足用 UNCERTAIN/UNRESOLVED。 | 无定义冲突。 |

## 剩余问题

- 证据阈值仍需后续黄金集校准，例如 AccountAccessRelation 从 SUPPORTED 升级为 CONFIRMED 的标准。
- AuthorshipClaim、Claim 和 AccountAccessRelation 未来可在 Schema 层共享 verification_status 枚举，但本次不修改 Schema。
- “小林”这类上下文称呼需要在 Agent 提示词中强制引用当前 Scene 的候选对象，不应只查全局 alias。
