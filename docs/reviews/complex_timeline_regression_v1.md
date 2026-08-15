# Complex Timeline Regression V1

测试范围：Golden Corpus V1 `tests/golden_corpus/03_complex_timeline`。
定义基线：`docs/domain_glossary.md` V1.3-draft 与 `docs/domain_rules.md` 第 11 节复杂时间线规则。
结论：V1.3-draft 能表达 NarrativeOrder 与 StoryTime 分离、相对时间锚点、SIMULTANEOUS/OVERLAPS 边界、ObjectState 未知区间、actor UNKNOWN 的状态变化事件，以及 BEFORE 不等于 CausalRelation。合理 UNKNOWN/UNCERTAIN 保留。

## Q1-Q15 回归结果

| 题号 | 结论 | EvidenceRef | 使用概念 | 确定性 | Definition Gap | Ambiguous Definition | 备注 |
|---|---|---|---|---|---|---|---|
| Q1 | NarrativeOrder 为 P01-P12；StoryTime 应按 2012、2018、2028 的实际发生顺序重排。 | P01-P12 | NarrativeOrder、StoryTime、TemporalRelation | CONFIRMED | 否 | 否 | V1.3 明确段落顺序不能替代 StoryTime。 |
| Q2 | “父亲失踪之夜”多次提及；应建立多个 NarrativeMention、Claim 或相关 Event，回指同一夜晚事件簇，而不是多个失踪 Event。 | P01、P07、P09、P10、P11 | Event、NarrativeMention、Claim | CONFIRMED | 否 | 否 | EventCluster 作为组织粒度，不新增顶层 Schema。 |
| Q3 | P03 的“三天前”对应 2028-10-31 下午，锚点是 2028-11-03 凌晨。 | P03、P04 | StoryTime、TemporalRelation | CONFIRMED | 否 | 否 | relative_time 需记录 anchor_story_time。 |
| Q4 | P05 的同步声明支持同一锚点 SIMULTANEOUS；20:58-21:12 监控区间覆盖 21:00 时可记 OVERLAPS/AT_TIME。 | P05 | TemporalRelation、StoryTime | CONFIRMED | 否 | 否 | V1.3 已消除 SIMULTANEOUS/OVERLAPS 边界歧义。 |
| Q5 | 监控确认顾淮 20:58-21:12 在便利店监控区间；不能确认他是否移动铁盒或九点整具体动作。 | P05、P08 | Event、LocationState、ObjectState、UNKNOWN | CONFIRMED/UNKNOWN | 否 | 否 | 区间覆盖时间点不等于参与放回事件。 |
| Q6 | “明晚以前”锚定 2018-11-03 交盒事件；2018-11-04 20:00 打开铁盒满足该相对截止。 | P02、P07 | StoryTime、TemporalRelation、Claim | CONFIRMED | 否 | 否 | relative_time 记录 anchor_event。 |
| Q7 | “前一天”存在讲述日和失踪日两个候选锚点；保持 candidate_anchors 与 UNCERTAIN，不强行定为唯一日期。 | P10 | StoryTime、TemporalRelation、KnowledgeState | UNCERTAIN | 否 | 否 | V1.3 补充相对锚点不唯一处理。 |
| Q8 | 程砚童年、十五岁、成年状态应按 StoryTime 查询，分别对应 2012、2018、2028。 | P06、P02、P01、P03、P08、P09、P12 | CharacterState、StoryTime、CharacterVisualVariant | CONFIRMED | 否 | 否 | 防止按 NarrativeOrder 错用年龄状态。 |
| Q9 | 铁盒可确定离散状态点；2018-2028 中间完整流转为 UNKNOWN interval。 | P06、P02、P07、P04、P08、P12 | ObjectState、StoryObject、StateChange | CONFIRMED/UNKNOWN | 否 | 否 | V1.3 明确不自动填补 holder/location/owner。 |
| Q10 | “铁盒被带回/放回”可作为 actor UNKNOWN 或 UnresolvedReference 的 Event 候选；顾淮对放回者的解释仍是 Claim。 | P08、P12 | Event、ObjectState、Claim、UnresolvedReference | CONFIRMED/UNKNOWN | 否 | 否 | 结果状态可确认，participant 不可补写。 |
| Q11 | 顾淮称未照做与铁盒被发现回到渡口不构成直接矛盾；可能是他人、其他时间或说法不实。 | P03、P08、P12 | Claim、Event、ObjectState | UNCERTAIN | 否 | 否 | 保留多候选，不判定顾淮说谎。 |
| Q12 | 病历只确认 2018-11-04 19:40 已处理手臂伤口；受伤发生在 19:40 前，且去码头前已受伤；原因 UNKNOWN。 | P09、P07 | InjuryState、TemporalRelation、UNKNOWN | CONFIRMED/UNKNOWN | 否 | 否 | BEFORE 关系可建，精确受伤时刻不可补。 |
| Q13 | 钟楼停摆 BEFORE 程远舟最后被看到，间隔八分钟；不能建立 CausalRelation。 | P07 | TemporalRelation、CausalRelation | UNKNOWN | 否 | 否 | V1.3 强化 BEFORE 不支持因果。 |
| Q14 | 不应自动填补铁盒十年间所有位置；只连接证据明确的 ObjectState 节点，中间保留 UNKNOWN interval。 | P06、P02、P07、P04、P08、P12 | ObjectState、TemporalRelation、UNKNOWN | CONFIRMED | 否 | 否 | 连续性不能覆盖证据缺口。 |
| Q15 | 精确日期、相对关系和 UNKNOWN 应分层记录；铁盒最初所有者、放回者、受伤原因、因果关系等保持 UNKNOWN。 | P01-P12 | StoryTime、TemporalRelation、ObjectState、Claim | CONFIRMED/UNKNOWN | 否 | 否 | time_kind 与 resolution_status 支撑分类。 |

## 03 主题结论

- NarrativeOrder 与 StoryTime 的边界足以支撑非线性叙事。
- StoryTime 的 `precision`、`anchor_event`、`anchor_story_time`、`candidate_anchors` 和 `resolution_status` 能表达相对时间锚点。
- SIMULTANEOUS 与 OVERLAPS 的边界已明确：同步声明/同一时间点 vs 区间交集。
- 同一历史夜晚多次提及不重复创建核心失踪 Event，而是用多个 NarrativeMention、Claim 或相关 Event 回指同一事件簇。
- ObjectState 可以记录离散状态点和 UNKNOWN interval，不自动补全铁盒十年流转。
- actor UNKNOWN 的状态变化事件可记录结果，不补写参与者。
- BEFORE、短间隔、文本相邻和视觉暗示都不自动生成 CausalRelation。

## 微型回归测试建议

| 微案例 | 回归结论 | 合理 UNKNOWN/UNCERTAIN | 新增冲突 |
|---|---|---|---|
| 01_same_event_multiple_mentions.md | 一个爆炸 Canonical Event，三个 NarrativeMention；监控录像不是第二次爆炸。 | 若三次描述细节冲突，冲突字段保持 UNCERTAIN。 | 无。 |
| 10_simultaneous_different_locations.md | 20:00 买票与签字是 SIMULTANEOUS，但不同 Location，不是同一 Scene。 | 两人是否互知对方行为为 UNKNOWN。 | 无。 |
| 11_relative_time_anchor.md | “前一天”锚点不唯一，应保留讲述日/回忆日候选，不能强推 3月1日或 3月4日。 | 正确输出为 candidate_anchors + UNCERTAIN。 | 无。 |
| 25_unknown_vs_uncertain.md | 完全没有年龄为 UNKNOWN；“看起来二十多岁”可保存为 fuzzy/range Claim 或视觉线索。 | 精确年龄仍 UNKNOWN。 | 无。 |
| 26_causality_vs_precedence.md | 停电 BEFORE 门打开可以建立；CausalRelation 必须 UNKNOWN。 | “停电导致门打开”不可写入 QA 或摘要。 | 无。 |
| 29_dependency_stale_recompute.md | 新证据修正剪发 StoryTime 后，第三/第四章依赖短发状态的 Panel/图片变 STALE；局部重算即可。 | 若缺少依赖图，具体受影响页面列表 UNKNOWN。 | 无。 |

## 剩余问题

- V1.3 只做领域语义说明，未实现 StoryTime/TemporalRelation Schema 字段。
- EventCluster 暂作为组织粒度说明，不新增顶层概念或持久化对象。
- `AT_TIME`、`SAME_ANCHOR` 作为派生说明，不作为正式枚举。
- 完整自动时间求解器、概率轨迹推断和复杂因果图谱推迟到后续阶段。
