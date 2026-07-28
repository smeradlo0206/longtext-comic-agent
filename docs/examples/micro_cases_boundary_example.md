# Micro Cases Boundary Example

本示例基于 `tests/golden_corpus/micro_cases` 的只读压力测试反馈，记录 V1.9-draft 对微型边界案例的最小校准。它只说明领域语义，不实现 Schema、Agent、数据库、自动 Scene 切分器或 Panel 连续动作求解器。

## 已稳定覆盖的规则清单

| 范围 | 已覆盖边界 |
|---|---|
| Q01 | 同一 Event 可以有多个 NarrativeMention，监控、回忆、转述不制造重复 Canonical Event |
| Q02, Q08, Q17 | DREAM/FLASHBACK 与 PRIMARY 状态隔离，历史状态按 StoryTime + RealityLayer 查询 |
| Q03, Q12-Q14 | 临时状态结束、持久状态延续、ObjectState owner/holder/in_use_by 分离 |
| Q04, Q09, Q24 | Claim/Proposal 不直接进入 Canonical Data，冲突保持 UNKNOWN/UNRESOLVED |
| Q05-Q07 | EntityMention、EntityAlias、Account、Character 不因相似名称或账号线索强合并 |
| Q10-Q11, Q26 | SIMULTANEOUS、相对时间锚点、BEFORE 不等于 CausalRelation |
| Q15-Q16 | 读者可见信息不进入人物 KnowledgeState，RelationshipState 多维化 |
| Q19-Q23, Q28 | StoryBeat、PanelSpec must_show/must_not_show、精确对白、QA hard/soft 边界 |
| Q25, Q27, Q29 | UNKNOWN/UNCERTAIN、不可靠记忆部分支持、DependencyEdge / STALE 重算 |

## Q18 连续跨地点动作

原文：

- `[P01]` 林岚从办公室冲进走廊追人。
- `[P02]` 她没有停顿，目标和动作连续。
- `[P03]` 追逐一直延续到楼梯口。

推荐表达：

```yaml
continuous_action_group: chase-linlan-001
scenes:
  - scene_id: chase-office
    location_id: office
    story_beats:
      - "林岚从办公室冲出"
    evidence_refs: [P01]
  - scene_id: chase-corridor
    location_id: corridor
    story_beats:
      - "林岚在走廊继续追人，没有停顿"
    evidence_refs: [P01, P02]
  - scene_id: chase-stairs
    location_id: stairwell
    story_beats:
      - "追逐延续到楼梯口"
    evidence_refs: [P03]
panel_continuity:
  - "相邻格保持运动方向一致"
  - "用门框、走廊透视、楼梯口标识承接动作"
  - "每格保留自己的 location_id"
```

错误示例：

- 把办公室、走廊、楼梯口画成同一地点，只说“连续追逐所以一个 Scene”。
- 为了保持动作连贯，省略所有 location_id。
- 把跨地点动作切散后丢失追逐目标和连续方向。

推荐原则：地点变化是强切分信号，但连续性可以通过相邻 Scene、StoryBeat 序列和 PanelSpec 连续动作说明保持，不需要牺牲地点准确性。

## Q30 Story-within-story

原文：

- `[P01]` 作家给孩子讲“月亮王国”童话。
- `[P02]` 童话里的国王被巨龙带走。
- `[P03]` 主线现实中不存在国王和巨龙。

推荐表达：

```yaml
primary_event:
  type: DialogueUnit_or_NarrationUnit
  summary: "作家给孩子讲月亮王国童话"
  reality_layer: PRIMARY
  evidence_refs: [P01]

embedded_story_visualization:
  source: "作家的童话讲述"
  narrative_perspective: storyteller
  reality_layer: UNKNOWN
  candidate_layers: [IMAGINATION, HYPOTHETICAL]
  narrative_mentions:
    - "童话里的国王被巨龙带走"
  evidence_refs: [P02]
  primary_canonical_effect: none

embedded_entities:
  - name: 国王
    scope: embedded_story
    merge_with_primary_entities: false
  - name: 巨龙
    scope: embedded_story
    merge_with_primary_entities: false
```

错误示例：

- 把“国王被巨龙带走”写成 PRIMARY Canonical Event。
- 在主线 StoryBible 中创建现实存在的国王和巨龙。
- 新增正式 `FICTIONAL_STORY` RealityLayer 来解决本轮问题。

推荐原则：角色讲述的童话、寓言、剧本或小说片段可被视觉化，但必须与主线实体、事件和 ObjectState 隔离。RealityLayer 证据不足时使用 `UNKNOWN` + candidate_layers，而不是强行选择唯一层。

## QA 对照

| 错误 | 推荐 QAIssue |
|---|---|
| 追逐格把办公室和楼梯口画成同一地点 | location_state_mismatch / scene_boundary_error |
| 跨地点动作切分后丢失追逐连续性 | continuity_loss / storybeat_sequence_error |
| 童话巨龙出现在主线现实街道 | reality_layer_leakage |
| 国王被写入主线人物关系网 | entity_scope_mismatch |

这些 issue_type 名称仅作说明性候选，不在 V1.9 固定正式枚举。
