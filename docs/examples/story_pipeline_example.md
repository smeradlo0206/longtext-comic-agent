# 完整流水线示例

示例原文：

> “十年后，林晓剪去了长发，带着父亲留下的怀表回到旧车站。钟声响起时，她想起大学时期第一次见到顾远的下午。”

本示例展示两个 Scene：

- 场景 A：十年后的旧车站现实主线。
- 场景 B：大学时期第一次见到顾远的回忆。

## 1. SourceChunk

```json
{
  "chunk_id": "chunk-linxiao-001",
  "order": 0,
  "text": "十年后，林晓剪去了长发，带着父亲留下的怀表回到旧车站。钟声响起时，她想起大学时期第一次见到顾远的下午。"
}
```

## 2. EvidenceRef

```json
{
  "chunk_id": "chunk-linxiao-001",
  "quote_text": "林晓剪去了长发，带着父亲留下的怀表回到旧车站"
}
```

## 3. Character

- `char-linxiao`：林晓。
- `char-guyuan`：顾远。

二者都必须从 SourceChunk 的 EvidenceRef 建立，不因为视觉需要新增人物。

## 4. Location

- `loc-old-station`：旧车站。
- `loc-university`：大学时期场景，原文未给出具体地点，精度标记为 UNKNOWN 或 “大学时期下午”背景。

## 5. StoryObject

- `obj-watch`：父亲留下的怀表。

## 6. Event

- `event-haircut`：林晓剪去长发。
- `event-return-station`：林晓带着怀表回到旧车站。
- `event-bell-rings`：钟声响起。
- `event-first-meet`：大学时期林晓第一次见到顾远。
- `event-remember`：林晓想起大学时期下午。

## 7. NarrativeMention

- NarrativeMention 1：原文直接叙述十年后林晓回旧车站。
- NarrativeMention 2：原文通过“她想起”叙述大学时期第一次见顾远。

`event-first-meet` 是被回忆的过去 Event；“她想起”本身是现实主线的 `event-remember`。

## 8. NarrativeOrder

文本出现顺序：

1. 十年后现实主线；
2. 钟声响起；
3. 林晓想起大学时期第一次见顾远。

## 9. StoryTime

故事发生顺序：

1. 大学时期第一次见顾远；
2. 十年后剪去长发；
3. 十年后带怀表回旧车站；
4. 钟声响起并触发回忆。

## 10. TemporalRelation

```json
[
  {
    "source_event_id": "event-first-meet",
    "target_event_id": "event-return-station",
    "relation": "BEFORE",
    "evidence_refs": [{"chunk_id": "chunk-linxiao-001", "quote_text": "十年后"}]
  },
  {
    "source_event_id": "event-bell-rings",
    "target_event_id": "event-remember",
    "relation": "BEFORE",
    "evidence_refs": [{"chunk_id": "chunk-linxiao-001", "quote_text": "钟声响起时，她想起"}]
  }
]
```

## 11. RealityLayer

- 场景 A：`PRIMARY`，十年后的现实主线。
- 场景 B：`FLASHBACK`，林晓记忆中的大学时期。

## 12. StateChange

- `statechange-hair-short`：林晓剪去长发后，`appearance.hair` 从长发变短发。
- `statechange-watch-owned`：林晓在十年后持有父亲留下的怀表。
- `statechange-memory-focus`：钟声触发林晓回忆顾远。

## 13. CharacterState

现实主线 CharacterState：

```json
{
  "character_state_id": "state-linxiao-adult-primary",
  "character_id": "char-linxiao",
  "story_time_ref": "ten-years-later",
  "reality_layer": "PRIMARY",
  "appearance": {"age_stage": "成年", "hair": "短发"},
  "inventory_ids": ["obj-watch"]
}
```

大学回忆 CharacterState：

```json
{
  "character_state_id": "state-linxiao-student-flashback",
  "character_id": "char-linxiao",
  "story_time_ref": "university-afternoon",
  "reality_layer": "FLASHBACK",
  "appearance": {"age_stage": "学生时期", "hair": "长发"},
  "inventory_ids": []
}
```

## 14. Scene

场景 A：

- `scene-old-station-primary`
- StoryTime：十年后
- RealityLayer：PRIMARY
- Location：旧车站
- Character：成年短发林晓
- StoryObject：怀表

场景 B：

- `scene-university-flashback`
- StoryTime：大学时期
- RealityLayer：FLASHBACK
- Character：学生时期长发林晓、顾远
- StoryObject：无怀表

## 15. StoryBeat

场景 A StoryBeat：

1. 林晓以成年短发状态回到旧车站；
2. 怀表建立父亲线索；
3. 钟声触发回忆。

场景 B StoryBeat：

1. 学生时期林晓第一次看见顾远；
2. 该信息解释现实主线回忆来源。

## 16. StoryBible

StoryBible 应冻结以下事实：

- 林晓十年后为成年短发；
- 林晓十年后持有父亲留下的怀表；
- 大学时期林晓仍是长发学生；
- 大学时期第一次见顾远发生在十年后旧车站场景之前；
- 回忆属于 FLASHBACK，不直接改写 PRIMARY 当前状态。

## 17. CharacterVisualVariant

- `variant-linxiao-adult-short-hair`：成年、短发、可持有怀表，用于 PRIMARY。
- `variant-linxiao-student-long-hair`：学生时期、长发、无怀表，用于 FLASHBACK。

## 18. PageSpec

```json
{
  "page_id": "page-001",
  "reading_order": "LTR",
  "panel_ids": ["panel-001", "panel-002", "panel-003"],
  "page_goal": "建立现实主线并转入大学回忆"
}
```

## 19. PanelSpec

现实主线 Panel：

```json
{
  "panel_id": "panel-001",
  "scene_id": "scene-old-station-primary",
  "source_chunk_ids": ["chunk-linxiao-001"],
  "story_time_ref": "ten-years-later",
  "reality_layer": "PRIMARY",
  "character_bindings": {
    "char-linxiao": {
      "character_state_id": "state-linxiao-adult-primary",
      "visual_variant_id": "variant-linxiao-adult-short-hair",
      "action": "回到旧车站",
      "emotion": "克制、怀旧"
    }
  },
  "must_show": ["旧车站", "短发林晓", "怀表"],
  "must_not_show": ["大学时期校服", "长发林晓"]
}
```

回忆 Panel：

```json
{
  "panel_id": "panel-003",
  "scene_id": "scene-university-flashback",
  "source_chunk_ids": ["chunk-linxiao-001"],
  "story_time_ref": "university-afternoon",
  "reality_layer": "FLASHBACK",
  "character_bindings": {
    "char-linxiao": {
      "character_state_id": "state-linxiao-student-flashback",
      "visual_variant_id": "variant-linxiao-student-long-hair",
      "action": "第一次见到顾远",
      "emotion": "惊讶、好奇"
    }
  },
  "must_show": ["学生时期长发林晓", "顾远"],
  "must_not_show": ["成年短发林晓", "怀表"]
}
```

## 20. QAResult

错误案例：回忆中的林晓被画成成年短发版本。

```json
{
  "qa_result_id": "qa-panel-003-character-state",
  "target_type": "PanelSpec",
  "target_id": "panel-003",
  "issues": [
    {
      "issue_type": "STATE_MISMATCH",
      "expected": "学生时期长发",
      "observed": "成年短发",
      "hard_failure": true
    }
  ],
  "hard_failures": ["STATE_MISMATCH"],
  "passed": false
}
```

## 21. RepairPlan

```json
{
  "repair_plan_id": "repair-panel-003-state",
  "target_id": "panel-003",
  "repair_type": "LOCAL_REGENERATE_CHARACTER_REGION",
  "instruction": "使用大学时期 CharacterVisualVariant variant-linxiao-student-long-hair，对林晓人物区域局部重生成；修复后重新执行人物状态 QA。",
  "max_attempts": 2
}
```

修复后必须重新运行人物状态 QA，确认回忆 Scene 使用 `state-linxiao-student-flashback`，不能混用现实主线成年短发状态。
