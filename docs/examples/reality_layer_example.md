# RealityLayer 示例

本文示例抽象自 Golden Corpus V1 `04_reality_layers`，用于说明设备画面、梦境、想象、污染记忆、预测模拟、Claim 和 Canonical Data 的边界。

## 1. 设备画面 UNKNOWN 或 UNRELIABLE_MEMORY

设备画面显示角色站在未来日期的白色走廊中，但设备被说明会把想象混进记忆。因此画面本身不能直接提交为未来事实。

```yaml
narrative_mention:
  content: 角色在设备画面中看见未来日期、白发、右肩渗血和红钥匙
  reality_layer: UNKNOWN
  candidate_layers: [DREAM, UNRELIABLE_MEMORY, HYPOTHETICAL]
  reliability_reason: device_may_mix_imagination_into_memory
  evidence_refs: [P01, P02, P04]
```

若后续证据支持这是受污染的记忆重放，可改为：

```yaml
narrative_mention:
  reality_layer: UNRELIABLE_MEMORY
  verification_status: UNVERIFIED
  evidence_refs: [P01, P02]
```

## 2. 梦中状态不污染 PRIMARY

```yaml
character_state:
  character: 叶澄
  reality_layer: PRIMARY
  story_time: 2029_after_waking
  appearance:
    hair: black
  injuries:
    right_shoulder: none
  evidence_refs: [P03]

object_state:
  object: 红钥匙
  reality_layer: PRIMARY
  holder_id: null
  presence: absent_from_yecheng_hand
  evidence_refs: [P03]
```

设备画面或梦中白发、伤口、钥匙只能留在非 PRIMARY 层或 UNKNOWN 候选层，不修改 2029 年现实状态。

## 3. 梦醒后恐惧进入 PRIMARY

```yaml
state_change:
  target: 叶澄
  attribute: fear_response.white_corridor
  to: heart_rate_spikes_when_seeing_hospital_corridor
  reality_layer: PRIMARY
  effective_from: after_waking_in_2029
  evidence_refs: [P03]
```

梦境内容不继承到现实，但梦醒后的恐惧反应是在现实中发生的状态变化。

## 4. 想象交付不改变现实 ObjectState

```yaml
scene:
  reality_layer: IMAGINATION
  content: 叶澄想象把红钥匙交给韩策
  evidence_refs: [P05]

object_state:
  object: 红钥匙
  reality_layer: PRIMARY
  holder_id: UNKNOWN
  note: 现实中叶澄没有钥匙，也没有交付动作
  evidence_refs: [P05]
```

想象中的交付不是现实 Event，不能把现实红钥匙 holder 改为韩策。

## 5. 塑料挂件与金属钥匙保持候选关联

```yaml
story_objects:
  - id: dream_red_key
    reality_layer: UNKNOWN
    material: UNKNOWN
    evidence_refs: [P02]
  - id: childhood_plastic_keychain
    reality_layer: UNRELIABLE_MEMORY
    material: plastic
    evidence_refs: [P06, P07]
  - id: real_metal_red_key
    reality_layer: PRIMARY
    material: metal
    evidence_refs: [P08]

candidate_link:
  objects: [childhood_plastic_keychain, real_metal_red_key]
  relation: VISUALLY_SIMILAR_OR_THEMATICALLY_RELATED
  verification_status: UNRESOLVED
  evidence_refs: [P07, P09]
```

颜色相同、形状相似或角色确信都不能单独合并 StoryObject。

## 6. 预测模拟归入 HYPOTHETICAL

```yaml
narrative_mention:
  content: 2031年的自己把钥匙插入白色走廊尽头的门
  reality_layer: HYPOTHETICAL
  source_medium: DEVICE_LOG
  source_label: 预测模拟
  verification_status: UNVERIFIED
  enters_elapsed_story_time: false
  evidence_refs: [P10]
```

预测模拟是可能性画面，不是已发生事件，也不能自动作为 `FLASH_FORWARD`。

## 7. 系统日志被质疑时保存冲突 Claim

```yaml
claims:
  - speaker: 许遥
    claim_type: ACCUSATION
    content: 日志标签是韩策后来改的
    verification_status: UNVERIFIED
    evidence_refs: [P11]
  - speaker: 韩策
    claim_type: DENIAL
    content: 自己没有修改日志标签
    verification_status: UNVERIFIED
    evidence_refs: [P11]
  - source: 自动签名记录
    claim_type: ASSERTION
    content: 文件生成后没有被修改
    verification_status: SUPPORTED
    evidence_refs: [P11]
```

自动签名记录只证明其直接覆盖的完整性范围，不能证明系统最初分类一定正确。

## 8. 相似现实事件不建立因果或验证关系

```yaml
event:
  id: hospital_corridor_visit
  reality_layer: PRIMARY
  content: 两周后经过白色医院走廊，右肩擦破，未白发且未携带红钥匙
  evidence_refs: [P12]

causal_relation:
  source: device_vision_or_dream
  target: hospital_corridor_visit
  relation: UNKNOWN
  reason: similarity_is_not_causal_evidence
  evidence_refs: [P12]

verification_relation:
  claim: dream_was_accurate_prediction
  status: NOT_CONFIRMED
  evidence_refs: [P12]
```

现实事件与非 PRIMARY 画面部分相似，只能作为视觉呼应或候选关联，不能反向证明梦境或模拟是准确预见。
