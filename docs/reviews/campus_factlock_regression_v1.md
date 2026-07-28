# Campus FactLock Regression V1

测试范围：`tests/golden_corpus/08_campus_factlock`

定义基线：`docs/domain_glossary.md` V1.8-draft、`docs/domain_rules.md` 第 16 节通知类事实锁定规则，以及前序 Revision、Canonical Data、PanelSpec、QAIssue、DependencyEdge / STALE 规则。

总体结论：本轮无硬 Definition Gap。08 是通知/公告类事实锁定压力测试，主要暴露 FactLock 尚未正式定义、字段级 Revision 覆盖/继承/作废策略需要更显眼、信息省略是否 hard failure 取决于 PanelSpec 目标。本轮适合做文档层最小修订，不进入 FactLockV1 Schema、字段级 Revision 数据库、通知解析 Agent、真实 QA 或日历校验器实现。

| 问题编号 | 结论 | 原文依据 | 涉及对象 | 确定性 | 是否 Definition Gap | 是否 Ambiguous Definition | 是否影响 Schema 候选 | 备注 |
|---|---|---|---|---|---|---|---|---|
| Q1 | 时间字段必须分开：报名截止、材料截止、报到、开幕、展示、决赛日期不是同一字段 | P01, P03-P08, P12 | FactLock, StoryTime, Event, Canonical Data | HIGH | 否 | 否 | 是 | 需要字段级锁定，避免把材料截止当报名截止。 |
| Q2 | 最终决赛日期、主会场、报到地点来自更正后的有效 Revision | P05-P06, P12 | Revision, Canonical Data, Location, EvidenceRef | HIGH | 否 | 否 | 是 | 最终事实必须保留更正来源 EvidenceRef。 |
| Q3 | 旧海报中的日期、地点和30强名额已 STALE | P05, P07, P09, P12 | Revision, DependencyEdge, VisualAsset, QAIssue | HIGH | 否 | 否 | 是 | 旧海报可保留为历史资产，不可覆盖最终事实。 |
| Q4 | 30 与 36 都是队伍数，不能写成学生人数 | P02, P07, P12 | FactLock, Canonical Data, QAIssue | HIGH | 否 | 否 | 是 | 数字单位是 FactLock 的关键部分。 |
| Q5 | 周舟老师与周洲副院长不能合并 | P03, P10, P12 | Character, EntityMention, EntityAlias, Contact | HIGH | 否 | 否 | 是 | P10 已明确不是同一人。 |
| Q6 | 每队2至4人与最多36支队伍不能推出固定参赛人数 | P02, P07, P12 | Canonical Data, Confidence, UNKNOWN | HIGH | 否 | 否 | 否 | 只能推出容量范围，实际人数 UNKNOWN。 |
| Q7 | 18支获奖队伍不等于前18名学生 | P11 | FactLock, Canonical Data, QAIssue | HIGH | 否 | 否 | 是 | 奖项单位是队伍。 |
| Q8 | 通知关键字段应作为 FactLock 并要求 text_accuracy=1.00 | P03, P05-P08, P10-P12 | FactLock, PanelSpec, QAResult | HIGH | 否 | 是 | 是 | FactLock 本轮新增为文档层概念。 |
| Q9 | 报到和开幕不能画在同一地点 | P04-P06, P12 | Location, LocationState, PanelSpec, QAIssue | HIGH | 否 | 否 | 是 | 一楼大厅与二楼多功能厅必须分开。 |
| Q10 | “报名截止时间不变”继承初版具体值，并由更正说明确认继续有效 | P03, P05, P12 | Revision, EvidenceRef, Canonical Data | HIGH | 否 | 是 | 是 | 需要字段级 confirmed_unchanged 语义。 |
| Q11 | 第二份补充通知不覆盖第一份更正的会场信息 | P05-P08, P12 | Revision, Canonical Data, DependencyEdge | HIGH | 否 | 是 | 是 | 后续通知只覆盖或新增其明确字段。 |
| Q12 | 已提交报名表的队伍无需重复报名 | P07 | FactLock, Canonical Data, Process Rule | HIGH | 否 | 否 | 是 | 流程类关键事实可进入 FactLock 候选。 |
| Q13 | 11月17日星期六是日期/星期冲突，通常 hard failure | P05, P09, P12 | QAIssue, FactLock, text_accuracy | HIGH | 否 | 否 | 是 | 不能由视觉质量抵消。 |
| Q14 | 漏办公电话是否 hard failure 取决于 PanelSpec 目标 | P03, P12 | PanelSpec, FactLock, QAIssue | MEDIUM | 否 | 是 | 是 | 完整咨询信息漏电话可硬失败，背景板省略可为 completeness issue。 |
| Q15 | 初版、更正、补充通知应建立字段级 Revision 关系 | P01-P09, P12 | Revision, Canonical Data, DependencyEdge | HIGH | 否 | 是 | 是 | 不得整份覆盖或整份继承。 |

## 08 主题结论

- FactLock 是本轮新增的文档层概念，不是新的故事事实类型。
- 通知类日期、星期、时间、地点、数字单位、联系人、电话、邮箱和流程规则都可成为 FactLock 候选。
- 字段级 Revision 必须区分创建、覆盖、确认不变、新增和作废。
- 旧海报、旧通知和旧视觉资产中的过期字段应标记 STALE，不得覆盖最终 Canonical Data。
- 信息省略是否 hard failure 取决于 PanelSpec 的展示目标和完整性要求。

## 微型回归测试建议

- 数字单位：队伍数、学生数、奖项支数、视频时长必须分别锁定。
- 近似姓名：同音或近字人物不得因读音合并。
- 版本覆盖：后续补充通知只覆盖明确修改字段。
- STALE 传播：引用旧海报字段的 VisualAsset、PanelSpec、QAResult 应过期。
- text_accuracy：日期/星期、电话、邮箱、地点、数字单位错误应 hard failure。

## 剩余问题

- FactLockV1 是否进入正式 Schema，需要单独 Schema 轮次评审。
- 字段级 Revision 的数据库结构、覆盖枚举、继承算法和旧资产 STALE 调度暂缓。
- 完整日历校验器、通知解析 Agent、真实 QA Agent、公告管理系统均超出 V1.8 文档修订范围。
