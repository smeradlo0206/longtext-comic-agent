# Micro Cases Regression V1

测试范围：`tests/golden_corpus/micro_cases`

定义基线：`docs/domain_glossary.md` V1.9-draft、`docs/domain_rules.md` 第 17 节 Micro Case 边界校准规则，以及 V1.1-V1.8 已建立的身份、时间、RealityLayer、Claim/Knowledge、Storyboard QA、FactLock 和 STALE 规则。

总体结论：Q01-Q17、Q19-Q29 当前定义足够；未发现硬 Definition Gap。Ambiguous Definition 集中在 Q18 连续跨地点动作的 Scene 粒度，以及 Q30 story-within-story 的 RealityLayer/实体空间隔离表达。本轮只做文档层最小修订，不进入 Schema、Agent、数据库、真实 LLM 或自动 Scene 切分器实现。

| 编号 | 案例名 | 结论 | 涉及对象 | 确定性 | 当前定义是否足够 | 是否 Definition Gap | 是否 Ambiguous Definition | 是否需要文档修订 | 备注 |
|---|---|---|---|---|---|---|---|---|---|
| Q01 | 同一事故的三次叙述 | 1 个 Event，3 个 NarrativeMention，回指同一 Canonical Event | Event, NarrativeMention, EvidenceRef | CONFIRMED | YES | 否 | 否 | 否 | V1.3/V1.7 已覆盖。 |
| Q02 | 梦里白发 | DREAM 白发不改 PRIMARY，醒后心神不宁可为 PRIMARY 状态变化 | RealityLayer, CharacterState, Scene | CONFIRMED | YES | 否 | 否 | 否 | V1.4 已覆盖。 |
| Q03 | 借来的雨衣 | 临时雨衣到归还结束，owner/holder 分离 | ObjectState, CharacterState, QAIssue | CONFIRMED | YES | 否 | 否 | 否 | V1.2/V1.6 已覆盖。 |
| Q04 | 未经证实的指控 | 指控是 Claim，管理员账号操作者 UNKNOWN | Claim, Account, Canonical Data | CONFIRMED/UNKNOWN | YES | 否 | 否 | 否 | V1.5 已覆盖。 |
| Q05 | 两个她 | “她”候选为林乔或苏晴，保持 UnresolvedReference | EntityMention, UnresolvedReference | UNCERTAIN | YES | 否 | 否 | 否 | 正确保留候选。 |
| Q06 | 网名被确认 | 北岸可确认为顾迟别名/账号线索，但 Account 与 Character 分离 | Account, EntityAlias, Character | CONFIRMED | YES | 否 | 否 | 否 | V1.1 已覆盖。 |
| Q07 | 周舟与周洲 | 不能合并，相似读音不是 Alias 证据 | Character, EntityMention, FactLock | CONFIRMED | YES | 否 | 否 | 否 | V1.8 已覆盖。 |
| Q08 | 回忆中的长发 | 回忆格查询历史 CharacterState，结束后恢复现实状态 | CharacterState, RealityLayer, Scene | CONFIRMED | YES | 否 | 否 | 否 | V1.4/V1.6 已覆盖。 |
| Q09 | 预言并未发生 | 预言是 DialogueUnit + Claim，不是 Canonical Event 或真实 FLASH_FORWARD | Claim, DialogueUnit, RealityLayer | CONFIRMED | YES | 否 | 否 | 否 | V1.4 已覆盖。 |
| Q10 | 同一时刻 | 两事件 SIMULTANEOUS，但不同地点不是同一 Scene，不能互知 | TemporalRelation, Scene, KnowledgeState | CONFIRMED | YES | 否 | 否 | 否 | V1.3/V1.5 已覆盖。 |
| Q11 | 前一天是谁的前一天 | 锚点不明，保留 3月1日/3月4日候选或 UNKNOWN | StoryTime, TemporalRelation | UNCERTAIN | YES | 否 | 否 | 否 | 正确保留 candidate_anchors。 |
| Q12 | 剪发 | 周三仍短发，一月后新 StateChange | StateChange, CharacterState | CONFIRMED | YES | 否 | 否 | 否 | 状态延续规则足够。 |
| Q13 | 摘下眼镜 | 可见佩戴状态结束，holder 仍在方启口袋 | ObjectState, CharacterState | CONFIRMED | YES | 否 | 否 | 否 | owner/holder/in_use_by 分离足够。 |
| Q14 | 借书与归还 | owner 一直陈禾，holder 借出后归还 | ObjectState | CONFIRMED | YES | 否 | 否 | 否 | V1.2 已覆盖。 |
| Q15 | 读者知道，人物不知道 | StoryBible 可保存钥匙位置，林真 KnowledgeState 不知道 | KnowledgeState, NarrativePerspective | CONFIRMED | YES | 否 | 否 | 否 | V1.5 已覆盖。 |
| Q16 | 表面和解 | 公开态度、合作和信任分维度 | RelationshipState, Claim | CONFIRMED | YES | 否 | 否 | 否 | V1.2 已覆盖。 |
| Q17 | 同一车站的回忆 | 同地点但 RealityLayer/StoryTime 变化，应切 Scene | Scene, RealityLayer, CharacterState | CONFIRMED | YES | 否 | 否 | 否 | V1.4/V1.6 已覆盖。 |
| Q18 | 跨门追逐 | 地点变化强切分，但连续动作需相邻 Scene/StoryBeat 序列保持连贯 | Scene, StoryBeat, PanelSpec, LocationState | UNCERTAIN | PARTIAL | 否 | 是 | 是 | V1.9 补 continuous_action_group 候选说明。 |
| Q19 | 喝水是不是剧情节拍 | 信息发现和决策构成 Beat，单纯喝水可并入 | StoryBeat, Event, KnowledgeState | CONFIRMED | YES | 否 | 否 | 否 | V1.6 已覆盖。 |
| Q20 | 摔杯 | 可拆多 Beat/Panel，是否单格取决于是否保留动作因果 | StoryBeat, PanelSpec, Event | UNCERTAIN | YES | 否 | 否 | 否 | 正确保留分镜粒度弹性。 |
| Q21 | 必须出现的钥匙 | must_show 钥匙、插锁、开门因果 | PanelSpec, ObjectState, QAIssue | CONFIRMED | YES | 否 | 否 | 否 | V1.6 已覆盖。 |
| Q22 | 追兵尚未出现 | 追兵完整外貌 must_not_show，可视觉化脚步声 | PanelSpec, QAIssue | CONFIRMED | YES | 否 | 否 | 否 | V1.6 已覆盖。 |
| Q23 | 漂亮但画错 | 状态和道具错误 hard failure，光影是 soft issue | QAIssue, QAResult | CONFIRMED | YES | 否 | 否 | 否 | V1.6 已覆盖。 |
| Q24 | 两个Agent相反结论 | 保留冲突 Proposal，Canonical 最多存相似背影 | Proposal, CommitService, Canonical Data | UNKNOWN | YES | 否 | 否 | 否 | V1.5 已覆盖。 |
| Q25 | 不知道还是不确定 | 精确年龄 UNKNOWN，外观二十多岁可为 UNCERTAIN 范围 | CharacterState, Claim, Confidence | UNKNOWN/UNCERTAIN | YES | 否 | 否 | 否 | V1.5 已覆盖。 |
| Q26 | 先后不等于因果 | 可建 BEFORE，不可建 CausalRelation | TemporalRelation, CausalRelation | CONFIRMED/UNKNOWN | YES | 否 | 否 | 否 | V1.3 已覆盖。 |
| Q27 | 部分错误的记忆 | 不整段作废，雨夜被否定，红车有支持 | Claim, NarrativeMention, RealityLayer | CONFIRMED | YES | 否 | 否 | 否 | V1.4/V1.5 已覆盖。 |
| Q28 | 不可改写的证词 | 关键证词不可改写，改写为 hard failure | DialogueUnit, FactLock, QAIssue | CONFIRMED | YES | 否 | 否 | 否 | V1.6/V1.8 已覆盖。 |
| Q29 | 剪发时间被修正 | 第三、四章短发状态和依赖产物 STALE，局部重算 | CharacterState, DependencyEdge, RepairPlan | CONFIRMED | YES | 否 | 否 | 否 | V1.7 已覆盖。 |
| Q30 | 角色讲述的虚构故事 | 童话事件不进 PRIMARY，嵌入实体与主线隔离 | RealityLayer, Event, Entity, NarrativePerspective | UNCERTAIN | PARTIAL | 否 | 是 | 是 | V1.9 补 story-within-story，不新增 FICTIONAL_STORY。 |

## 主题结论

- 当前定义足以回答 Q01-Q17、Q19-Q29。
- 未发现硬 Definition Gap。
- Ambiguous Definition 为 Q18 和 Q30。
- 正确保留 UNKNOWN/UNCERTAIN 的案例包括 Q05、Q11、Q18、Q20、Q24、Q25、Q26 的因果关系和 Q30。
- Q18 的修订重点是允许相邻 Scene 保持连续动作，而不是用单一 Scene 混淆地点。
- Q30 的修订重点是嵌入故事与主线 PRIMARY 的实体、事件和状态隔离。

## 回归建议

- 修改 Scene 规则后，回归 Q17、Q18、Q20、Q21、Q22，确认场景切分、连续动作和 PanelSpec 约束一致。
- 修改 story-within-story 规则后，回归 Q02、Q09、Q15、Q27、Q30，确认非 PRIMARY 层和角色知识不污染主线。
- 修改 QAIssue 说明后，回归 Q23、Q28、Q29，确认 hard failure、text_accuracy 和 STALE 传播仍然稳定。

## 剩余问题

- `continuous_action_group`、`ActionSequenceV1`、`EmbeddedNarrativeScopeV1` 和故事内故事实体库均为后续候选，不进入 V1.9。
- 不新增正式 `FICTIONAL_STORY` RealityLayer；使用 `IMAGINATION`、`HYPOTHETICAL` 或 `UNKNOWN` + candidate_layers 表达。
- 自动 Scene 切分器和完整 Panel 连续动作求解器仍超出 MVP。
