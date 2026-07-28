# Storyboard QA Example

本文示例抽象自 Golden Corpus V1 `06_storyboard_qa`，用于说明 Scene 切分、StoryBeat-to-Panel、PanelSpec 硬约束、关键对白、ObjectState 结束态、QAIssue 与 RepairPlan 的最小表达方式。

## 1. 推荐 Scene 切分

```yaml
scenes:
  - scene_id: underground_corridor_setup
    source_refs: [P01, P02]
    reality_layer: PRIMARY
    location: 地下走廊
    goal: 十分钟内取出纸质地图
  - scene_id: five_year_flashback
    source_refs: [P03]
    reality_layer: FLASHBACK
    story_time: 五年前
    goal: 父亲交付黄铜钥匙并留下对白
  - scene_id: underground_showcase_escape
    source_refs: [P04, P05, P06, P07, P08, P09]
    reality_layer: PRIMARY
    location: 地下走廊和地下展厅
    goal: 取出地图并撤离
    note: P09 是撤离过渡段，可按页面节奏决定是否细切
  - scene_id: first_floor_exit
    source_refs: [P10, P11]
    reality_layer: PRIMARY
    location: 一楼大厅
    goal: 打开安全门并转移地图
```

P12 是制作后的 QA 反馈，不是故事世界 Scene。

## 2. StoryBeat 示例

```yaml
story_beats:
  - beat: 发现地下展厅进水，建立十分钟目标
    evidence_refs: [P01]
  - beat: 三人初始状态：安遥披防水外套，季川持黄铜钥匙，老许右脚旧伤发作
    evidence_refs: [P02]
  - beat: 五年前父亲交钥匙并说关键对白
    evidence_refs: [P03]
  - beat: 季川把钥匙递给安遥
    evidence_refs: [P04]
  - beat: 熄灯、老许摔倒并再次扭伤
    evidence_refs: [P05]
  - beat: 安遥开柜并看到地图和照片
    evidence_refs: [P06]
  - beat: 老许抛出手电筒，季川接住
    evidence_refs: [P08]
```

普通走路、无信息量转头或背景水流变化可作为 PanelSpec 动作细节，不必独立成 StoryBeat。

## 3. P07 Panel 拆分示例

P07 包含“开柜”“看到照片”“犹豫”“取走地图”四个信息点，不宜全部压在一格中。

```yaml
panels:
  - panel_id: p07_a
    must_show: [安遥打开展柜, 展柜里的纸质地图, 父亲照片]
    focus_subject: 展柜内容揭示
  - panel_id: p07_b
    must_show: [安遥取出纸质地图, 黄铜钥匙仍由安遥持有]
    focus_subject: 地图转为安遥持有
  - panel_id: p07_c
    must_show: [安遥停顿看照片, 季川催促离开]
    focus_subject: 犹豫和催促
```

若压成单格，必须用构图分区或连续动作线清楚表达四个信息点，否则会造成关键动作或信息揭示缺失。

## 4. P04 must_show 示例

```yaml
panel_spec:
  source_chunk_ids: [P04]
  must_show:
    - 黄铜钥匙
    - 季川递出钥匙
    - 安遥接收钥匙
    - 两人的手清楚可见
    - 钥匙交接方向明确
  must_not_show:
    - 闯入者进入画面
```

手部和钥匙是后续 ObjectState 的证据链，不是普通构图偏好。

## 5. P06 must_not_show 示例

```yaml
panel_spec:
  source_chunk_ids: [P06]
  must_show:
    - 季川听见楼梯脚步后的反应
    - 安遥打开的展柜
    - 纸质地图
    - 父亲照片
  must_not_show:
    - 完整闯入者
    - 闯入者脸
    - 可识别的楼梯上人物
```

P06 只能表现脚步声、音效或角色反应；闯入者影子首次出现应等到 P09。

## 6. P03/P10 DialogueUnit 分离示例

```yaml
dialogue_units:
  - dialogue_id: father_flashback_do_not_turn
    speaker: 父亲
    text: 门打开以后，不要回头。
    story_time: 五年前
    reality_layer: FLASHBACK
    evidence_refs: [P03]
  - dialogue_id: anyao_primary_do_not_turn
    speaker: 安遥
    text: 门打开以后，不要回头。
    story_time: 一楼安全门打开前
    reality_layer: PRIMARY
    echoes_dialogue_id: father_flashback_do_not_turn
    evidence_refs: [P10]
```

相同文本因为说话者、StoryTime 和 RealityLayer 不同，不能合并为一个 DialogueUnit。

## 7. P11 ObjectState 结束态示例

```yaml
object_states_at_end:
  - object: 纸质地图
    holder_id: 季川
    evidence_refs: [P11]
  - object: 父亲照片
    holder_id: 安遥
    evidence_refs: [P11]
  - object: 黄铜钥匙
    location_id: 一楼大厅安全门锁上
    holder_id: null
    in_use_by_id: null
    evidence_refs: [P11]
  - object: 手电筒
    holder_id: 季川
    evidence_refs: [P08, P10]
```

结束态必须按最新证据更新，不能把“安遥刚才开门”静默延续为她仍持有钥匙。

## 8. P12 QAIssue 与 RepairPlan 示例

```yaml
qa_issues:
  - issue_type: STATE_MISMATCH
    expected: 年轻安遥穿校服，FLASHBACK CharacterState
    observed: 成年短发安遥穿防水外套
    hard_failure: true
    evidence_refs: [P03, P12]
    repair_plan:
      repair_type: LOCAL_REGENERATE_CHARACTER_REGION
      instruction: 使用五年前 CharacterState 和对应 CharacterVisualVariant 局部重绘安遥人物区域
  - issue_type: MUST_SHOW_VIOLATION
    expected: 地下展柜格显示黄铜钥匙
    observed: 漏掉黄铜钥匙
    hard_failure: true
    evidence_refs: [P04, P12]
    repair_plan:
      repair_type: UPDATE_PANEL_SPEC_THEN_LOCAL_REPAINT
      instruction: 先补 must_show=黄铜钥匙，再局部重绘钥匙区域
  - issue_type: MUST_NOT_SHOW_VIOLATION
    expected: P06 不出现完整闯入者
    observed: 闯入者在 P06 被完整画出
    hard_failure: true
    evidence_refs: [P06, P09, P12]
    repair_plan:
      repair_type: LOCAL_REPAINT_OR_FULL_REGENERATE
      instruction: 若闯入者只是局部多余对象则局部移除；若主体构图依赖闯入者则整格重生成
```

构图漂亮是软性质量，不能抵消 hard failure。

## 9. 黄铜钥匙画成银色的严重性

```yaml
qa_issue:
  issue_type: OBJECT_ATTRIBUTE_MISMATCH
  expected: 黄铜钥匙
  observed: 银色钥匙
  severity: HIGH
  hard_failure: true
  reason: 黄铜材质被多次强调，钥匙是唯一关键道具且影响开柜和开门功能
  evidence_refs: [P02, P04, P10]
```

若只是轻微色偏，且读者仍能稳定识别为同一黄铜钥匙，可降为 medium 或 soft issue，但必须记录并复检。
