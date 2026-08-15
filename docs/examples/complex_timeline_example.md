# Complex Timeline 示例

本文示例抽象自 Golden Corpus V1 `03_complex_timeline`，用于说明复杂叙述顺序、相对时间锚点、同时/重叠关系、ObjectState 未知区间和因果边界。

## 1. NarrativeOrder vs StoryTime

NarrativeOrder 按文本出现顺序记录：

```text
P01 2028凌晨 -> P02 2018回忆 -> P03 2028凌晨 -> P04 2028-10-31 -> P05 2028-11-01 -> P06 2012童年 -> P07 2018-11-04 -> P08 2028-11-03 01:00
```

StoryTime 按故事真实发生顺序记录：

```text
2012夏看见铁盒
2018-11-03 交付铁盒
2018-11-04 20:00 打开铁盒
2018-11-04 21:07 钟楼停摆
2018-11-04 21:15 最后被看到
2028-10-31 收到短信
2028-11-01 21:00 并行事件
2028-11-03 01:00 找到铁盒
```

不能用段落顺序替代 StoryTime。

## 2. 相对时间锚点

```yaml
story_time:
  text: 三天前
  time_kind: relative_time
  anchor_story_time: 2028-11-03 凌晨
  resolved_value: 2028-10-31 下午
  resolution_status: CONFIRMED
  evidence_refs: [P03, P04]
```

```yaml
story_time:
  text: 明晚以前
  time_kind: relative_time
  anchor_event: 2018-11-03 交付铁盒
  resolved_deadline: before_2018-11-04_night
  resolution_status: CONFIRMED
  evidence_refs: [P02, P07]
```

```yaml
story_time:
  text: 前一天
  time_kind: relative_time
  candidate_anchors:
    - chapter_narration_day
    - father_disappearance_day
  resolution_status: UNCERTAIN
  evidence_refs: [P10]
```

锚点不唯一时保留候选，不强行推断唯一日期。

## 3. SIMULTANEOUS vs OVERLAPS

原文明确说“两个地点同时发生了事情”时，可以为同一叙述锚点建立 SIMULTANEOUS：

```yaml
temporal_relation:
  source_event: 医院查询旧病历
  target_event: 顾淮出现在便利店监控
  relation: SIMULTANEOUS
  anchor_story_time: 2028-11-01 21:00
  evidence_refs: [P05]
```

如果一个对象是区间，例如 20:58-21:12 的监控片段，则该区间覆盖 21:00：

```yaml
temporal_relation:
  source_interval: 顾淮便利店监控区间
  target_time_point: 2028-11-01 21:00
  relation: OVERLAPS
  derived_note: AT_TIME
  evidence_refs: [P05]
```

区间覆盖某时间点，不等于区间与另一个事件起止完全相同。

## 4. ObjectState 未知区间

```yaml
object_state_timeline:
  - object: 蓝色铁盒
    story_time: 2012夏
    holder_id: 程远舟
    owner_id: UNKNOWN
    location_id: 父亲书桌
    evidence_refs: [P06]
  - object: 蓝色铁盒
    story_time: 2018-11-03
    holder_id: 顾淮
    owner_id: UNKNOWN
    evidence_refs: [P02]
  - object: 蓝色铁盒
    story_time_interval: 2018-11-04_after_open_to_2028-10-31_before_office
    holder_id: UNKNOWN
    location_id: UNKNOWN
    evidence_refs: [P12]
  - object: 蓝色铁盒
    story_time: 2028-10-31
    holder_id: 顾淮
    location_id: 顾淮背包
    evidence_refs: [P04]
  - object: 蓝色铁盒
    story_time: 2028-11-03 01:00
    location_id: 废弃售票亭地下
    holder_id: 程砚
    condition: missing_tape_has_badge_and_new_ticket
    evidence_refs: [P08]
```

离散状态点之间允许 UNKNOWN interval，不自动填补十年流转。

## 5. actor UNKNOWN 的状态变化事件

```yaml
event:
  event_type: OBJECT_RETURNED_OR_PLACED
  object_id: 蓝色铁盒
  actor_ref: UNKNOWN
  result_state:
    location_id: 渡口或售票亭地下
  verification_status: SUPPORTED
  evidence_refs: [P08, P12]

claim:
  speaker: 顾淮
  claim_type: INTERPRETATION
  content: 有人在11月1日晚把铁盒放了回来
  verification_status: UNVERIFIED
  evidence_refs: [P08]
```

结果状态可由发现铁盒确认；放回者不能由角色解释升级为 Canonical participant。

## 6. BEFORE 不等于 CausalRelation

```yaml
temporal_relation:
  source_event: 钟楼停摆
  target_event: 程远舟最后被看到
  relation: BEFORE
  delta: 8_minutes
  evidence_refs: [P07]

causal_relation:
  source_event: 钟楼停摆
  target_event: 程远舟失踪
  relation: UNKNOWN
  reason: no_causal_evidence
  evidence_refs: [P07]
```

相隔八分钟、文本相邻和视觉暗示都不足以单独建立因果。
