# Storyboard QA Regression V1

测试范围：`tests/golden_corpus/06_storyboard_qa`

定义基线：`docs/domain_glossary.md` V1.6-draft 与 `docs/domain_rules.md` 第 14 节 Storyboard QA 与修复规则。

总体结论：本轮无硬 Definition Gap。存在 Ambiguous Definition：Scene 粒度、RepairPlan 策略阈值、关键道具颜色/材质错误严重性。适合做文档层最小修订，不进入完整 Schema、真实 QA Agent 或图像修复实现。

| 问题编号 | 结论 | 原文依据 | 涉及对象 | 确定性 | 是否 Definition Gap | 是否 Ambiguous Definition | 是否影响 Schema 候选 | 备注 |
|---|---|---|---|---|---|---|---|---|
| Q1 | 推荐切为地下走廊建立、五年前回忆、地下展厅撤离、一楼大厅出口等 Scene；回忆前后必须分 Scene，P09 过渡段可有粒度弹性。 | P01-P03, P09-P11 | Scene, RealityLayer, StoryTime | UNCERTAIN | 否 | 是 | 是 | Scene 粒度需给“通常必须切”和“过渡弹性”边界。 |
| Q2 | StoryBeat 应围绕目标建立、状态建立、回忆交钥匙、钥匙交接、熄灯摔倒、开柜揭示、取图犹豫、手电筒转移、撤离开门等变化；普通走路不独立成 Beat。 | P01-P11 | StoryBeat, Event, StateChange | CONFIRMED | 否 | 否 | 是 | 当前 StoryBeat 定义足够，补充示例即可。 |
| Q3 | P07 至少拆成开柜揭示、取地图、看照片/犹豫/催促等多个 Panel；不能把四个信息点随意压成一格。 | P06, P07 | PanelSpec, StoryBeat, ObjectState | CONFIRMED | 否 | 否 | 是 | 需要明确连续动作和信息揭示的 Panel 拆分纪律。 |
| Q4 | 抛出和接住可作为一个“手电筒转移”Beat；一个 Panel 必须有运动线或因果连续性，否则拆成抛出/接住两个 Panel。 | P08 | StoryBeat, PanelSpec, ObjectState | CONFIRMED | 否 | 否 | 是 | 影响运动线或多时刻表达候选字段。 |
| Q5 | P04 PanelSpec must_show 黄铜钥匙、季川递出、安遥接收、两人手清楚可见、交接方向明确。 | P02, P04 | PanelSpec, ObjectState | CONFIRMED | 否 | 否 | 是 | must_show 是硬约束。 |
| Q6 | P06 must_not_show 完整闯入者、闯入者脸、可识别楼梯上人物；可表现脚步声或角色反应。 | P06, P09 | PanelSpec, QAIssue | CONFIRMED | 否 | 否 | 是 | 原文明示尚未出现的人物应进 must_not_show。 |
| Q7 | 回忆中的安遥绑定五年前 FLASHBACK 的年轻/校服 CharacterState 与历史 CharacterVisualVariant；当前短发和防水外套不得污染回忆，未说明发型保持 UNKNOWN。 | P03, P12 | CharacterState, CharacterVisualVariant, RealityLayer | CONFIRMED | 否 | 否 | 是 | 强化历史状态绑定。 |
| Q8 | 旧伤发作和再次扭伤是同一右脚 InjuryState 生命周期中的不同变化；再次扭伤是后续状态更新或新受伤事件。 | P02, P05 | InjuryState, StateChange, Event | CONFIRMED | 否 | 否 | 是 | 现有 InjuryState 规则足够。 |
| Q9 | “别管我，地图比我重要”必须逐字保留，不得缩写、改写或移到旁白。 | P05 | DialogueUnit, PanelSpec, QAIssue | CONFIRMED | 否 | 否 | 是 | text_must_be_exact 应明确进入 PanelSpec。 |
| Q10 | P03 父亲对白与 P10 安遥对白文本相同，但说话者、StoryTime、RealityLayer 不同，应建立两个 DialogueUnit，可记录呼应关系。 | P03, P10 | DialogueUnit, RealityLayer, StoryTime | CONFIRMED | 否 | 否 | 是 | 影响 DialogueUnit 关系候选字段。 |
| Q11 | 结束态：地图 holder=季川；照片 holder=安遥；钥匙 location=门锁且不继续 holder=安遥；手电筒 holder=季川；owner 未明保持 UNKNOWN。 | P08, P10, P11 | ObjectState | CONFIRMED | 否 | 否 | 是 | 需要强调结束态按最新证据更新。 |
| Q12 | 三处错误都是 QAIssue 且 hard failure：回忆状态错、黄铜钥匙漏、P06 完整闯入者提前出现。 | P03, P04, P06, P09, P12 | QAIssue, QAResult | CONFIRMED | 否 | 否 | 是 | issue_type 枚举暂不固定。 |
| Q13 | 构图漂亮不能抵消故事事实 hard failure。 | P12 | QAResult, QAIssue | CONFIRMED | 否 | 否 | 否 | hard failure 优先级需显眼。 |
| Q14 | 修复策略：约束缺失先改 PanelSpec；局部事实错优先局部重绘；主体构图依赖错误对象或多处错则整格重生成；阅读/文字区域坏才重新排版。 | P12 | RepairPlan, QAIssue, PanelSpec | UNCERTAIN | 否 | 是 | 是 | 当前缺少策略阈值，需要文档补充。 |
| Q15 | 黄铜钥匙画成银色是 OBJECT_ATTRIBUTE_MISMATCH；若原文明确、多次强调且道具唯一/影响剧情功能，high severity 且通常 hard failure；轻微色偏可降级并复检。 | P02, P04, P10 | QAIssue, VisualAsset, PanelSpec | UNCERTAIN | 否 | 是 | 是 | 颜色/材质严重性阈值需文档补充。 |

## 06 主题结论

- Scene、StoryBeat、PanelSpec、DialogueUnit、ObjectState、QAIssue 和 RepairPlan 已能表达本轮主要问题。
- Q1、Q14、Q15 暴露的是阈值歧义，不是硬定义缺口。
- must_show / must_not_show、关键对白、回忆状态、关键道具结束态和 hard failure 优先级需要写得更可执行。
- 本轮只做文档层最小修订，不进入完整 Schema、真实 QA Agent、真实局部重绘或 VisualBible/VisualAsset 管理系统。

## 微型回归测试建议

- Scene 切分：RealityLayer 改变、地点改变、StoryTime 跳跃、过渡段粒度。
- Panel 拆分：连续动作的多个关键时刻和物体转移。
- PanelSpec：must_show/must_not_show 违反即 hard failure。
- DialogueUnit：相同文本不同说话者或时间不能合并。
- ObjectState：结束态不得静默延续旧 holder/location。
- RepairPlan：局部重绘、整格重生成、重新排版的策略边界。

## 剩余问题

- `QAIssue.issue_type` 完整枚举、严重性评分阈值、RepairPlan 类型枚举和多时刻 Panel 表达字段需后续 Schema 设计。
- 本轮未修改 Schema、Agent、数据库、真实 QA 或图像修复能力。
