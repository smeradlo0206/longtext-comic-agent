# 黄金测试语料覆盖矩阵

符号：

- `●`：主要测试目标
- `○`：顺带覆盖
- `—`：不是本案例重点

| 核心概念 | 01身份共指 | 02关系状态 | 03复杂时间 | 04现实层 | 05说法知识 | 06分镜QA | 07综合 | 08校园 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Entity / Character | ● | ○ | ○ | ○ | ○ | ○ | ● | ○ |
| EntityAlias / 共指 | ● | — | — | — | — | — | ● | ● |
| Event | ○ | ● | ● | ● | ● | ● | ● | ○ |
| NarrativeMention | ○ | ○ | ● | ● | ● | ○ | ● | — |
| NarrativeOrder | ○ | ○ | ● | ● | ○ | ○ | ● | ○ |
| StoryTime | ○ | ● | ● | ● | ○ | ● | ● | ● |
| TemporalRelation | — | ○ | ● | ○ | ○ | ○ | ● | ● |
| RealityLayer | — | — | ● | ● | ○ | ● | ● | — |
| StateChange | — | ● | ● | ● | ○ | ● | ● | — |
| CharacterState | ○ | ● | ● | ● | ○ | ● | ● | — |
| KnowledgeState | ● | ● | ○ | ● | ● | ○ | ● | ○ |
| RelationshipState | ○ | ● | — | ○ | ○ | ○ | ● | — |
| ObjectState | ○ | ● | ● | ● | ● | ● | ● | ○ |
| Scene | ○ | ○ | ● | ● | ○ | ● | ● | ○ |
| StoryBeat | — | ○ | ○ | ○ | ○ | ● | ● | ○ |
| PanelSpec | — | ○ | ○ | ○ | ○ | ● | ● | ● |
| QAResult / RepairPlan | ○ | ○ | ○ | ● | ○ | ● | ● | ● |
| Proposal / Canonical | ● | ● | ● | ● | ● | ○ | ● | ● |
| Revision / STALE | — | ○ | ○ | ○ | ○ | ○ | ● | ● |
| FactLock | — | — | — | — | — | — | ○ | ● |
