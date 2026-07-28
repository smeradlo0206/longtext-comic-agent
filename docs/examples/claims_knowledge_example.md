# Claims Knowledge Example

本示例用于说明 05_claims_knowledge 的最小表达纪律：指控不等于事实，读者可见不等于角色知道，ObjectState 不自动补全动机或路径，CommitService 面对冲突 Proposal 只提交中性已证事实。

## 1. 指控 Claim 不等于 Canonical Event

原文：林祁说“我看见程放拿了卡”，但没有角度、时间或其他证据。

```yaml
claim:
  claim_type: ACCUSATION
  speaker_id: character_linqi
  content: "程放拿了门禁卡"
  verification_status: UNVERIFIED
  evidence_refs: ["P02"]

canonical_event:
  status: NOT_CREATED
  reason: "角色指控没有独立证据，不能提交为程放拿卡事件"
```

## 2. 卡在外套里不等于偷卡

原文：门禁卡从林祁外套内袋掉出。

```yaml
object_state:
  object_id: access_card
  holder_id: character_linqi
  location_id: linqi_coat_inner_pocket
  evidence_refs: ["P04"]

unknown_chain:
  object_id: access_card
  from_state: "值班桌"
  to_state: "林祁外套内袋"
  actor: UNKNOWN
  path: UNKNOWN
  motive: UNKNOWN
```

该状态不支持自动生成“林祁偷卡”“有人栽赃林祁”或完整移动路线。

## 3. 未知灰外套人

原文：周芮看见灰外套人靠近值班桌，但红色应急灯下看不清脸，程放和林祁都穿灰外套。

```yaml
unresolved_reference:
  ref_id: unresolved_gray_coat_person
  mention_text: "灰外套的人"
  candidate_character_ids:
    - character_chengfang
    - character_linqi
  resolution_status: UNRESOLVED
  evidence_refs: ["P03"]
```

不要因此新建一个确定 Character。

## 4. 读者看见不等于角色知道

原文：读者看到黑手套的手在停电前五分钟拿走门禁卡，但四个角色没有看到。

```yaml
narrative_perspective:
  perspective_type: OMNISCIENT
  visible_to_reader: true
  visible_to_character_ids: []
  evidence_refs: ["P06"]

event:
  event_type: TAKE_OBJECT
  actor: UNKNOWN
  actor_ref: unresolved_black_gloved_hand
  object_id: access_card
  story_time: "停电前五分钟"
  evidence_refs: ["P06"]

knowledge_states:
  - character_id: character_linqi
    knowledge_target_id: event_take_access_card
    epistemic_status: UNAWARE
  - character_id: character_chengfang
    knowledge_target_id: event_take_access_card
    epistemic_status: UNAWARE
```

## 5. 后续证据不反向修改历史 KnowledgeState

原文：周芮听见水声，猜一楼积水；后来监控恢复后确认一楼确有积水。

```yaml
knowledge_state_before_monitor:
  character_id: character_zhourui
  knowledge_target_id: first_floor_water
  epistemic_status: SUSPECTS
  source_claim_id: claim_heard_water
  valid_story_time: "监控恢复前"

canonical_location_state_after_monitor:
  location_id: first_floor
  condition: WATER_PRESENT
  evidence_refs: ["P08"]
```

监控确认事实本身，但不能把周芮在监控恢复前的 SUSPECTS 改成 KNOWS。

## 6. 信息传播只给可见角色

原文：程放读到维修单并告诉沈策，没有告诉另外两人。

```yaml
knowledge_states:
  - character_id: character_chengfang
    knowledge_target_id: safety_door_power_disconnected
    epistemic_status: KNOWS
    evidence_refs: ["P09"]
  - character_id: character_shence
    knowledge_target_id: safety_door_power_disconnected
    epistemic_status: KNOWS
    evidence_refs: ["P09"]
  - character_id: character_linqi
    knowledge_target_id: safety_door_power_disconnected
    epistemic_status: UNAWARE
  - character_id: character_zhourui
    knowledge_target_id: safety_door_power_disconnected
    epistemic_status: UNAWARE
```

## 7. 相似黑手套只建立候选关联

原文：门外有湿黑手套，但无法确认是否就是拿卡的黑手套。

```yaml
candidate_link:
  source_object_ref: unresolved_black_gloved_hand
  target_object_id: wet_black_glove
  relation: POSSIBLY_SAME_OR_RELATED
  confidence: LOW
  evidence_refs: ["P06", "P11", "P12"]
```

不能仅凭颜色相同合并 StoryObject。

## 8. 冲突 Proposal 的提交纪律

两个 Agent 输出互斥结论：一个认为程放拿卡，一个认为林祁自导自演。

```yaml
proposals:
  - proposal_id: proposal_chengfang_took_card
    status: CONFLICTING
  - proposal_id: proposal_linqi_staged_card
    status: CONFLICTING

commit_result:
  committed_facts:
    - "停电前有人拿走门禁卡"
    - "门禁卡后来出现在林祁外套内袋"
  retained_conflicts:
    - proposal_chengfang_took_card
    - proposal_linqi_staged_card
  review_required: true
```

CommitService 不为了让故事闭合而任选一方。
