# RelationshipState、ObjectState 与 InjuryState 示例

本文示例抽象自 Golden Corpus V1 `02_relationship_state`，用于说明人物关系、道具、伤势和视觉状态如何避免过度推断。

## 1. 持续发型 StateChange

陆岚的海报旧照片是长发，但当前本人已经是齐耳短发。短发属于持续 CharacterState，除非后文出现“重新留长”或其他发型变化，否则保持生效。

```yaml
state_change:
  target: 陆岚
  attribute: appearance.hair
  from: long
  to: short_bob
  effective_from: before_P01
  effective_until: UNKNOWN
  evidence_refs: [P01, P12]
```

## 2. 临时礼服状态

银色礼服只用于当晚彩排和演出，不能延续到次日。

```yaml
character_state:
  character: 陆岚
  clothing:
    current_outfit: silver_dress
    effective_from: P03
    effective_until: after_anniversary_performance
    evidence_refs: [P03]
```

P11 应解析为：

```yaml
character_state:
  character: 陆岚
  clothing:
    current_outfit: black_coat
    evidence_refs: [P11]
```

## 3. 左手 InjuryState 生命周期

```yaml
injury_states:
  - character: 陆岚
    body_part: left_hand
    injury_type: cut
    phase: ACUTE
    visible_markers: [fresh_cut]
    treatment: none
    effective_from: P05_rotating_stage_jam
    evidence_refs: [P05]
  - character: 陆岚
    body_part: left_hand
    injury_type: cut
    phase: FIRST_AID
    visible_markers: [handkerchief_bandage]
    treatment: handkerchief_wrap
    evidence_refs: [P05]
  - character: 陆岚
    body_part: left_hand
    injury_type: cut
    phase: MEDICALLY_TREATED
    visible_markers: [medical_bandage, stitches]
    functional_limitations: [no_water_for_three_days]
    treatment: three_stitches
    evidence_refs: [P05, P11]
  - character: 陆岚
    body_part: left_hand
    injury_type: cut
    phase: HEALED_WITH_MARK
    visible_markers: [shallow_scar]
    treatment: stitches_removed
    evidence_refs: [P12]
```

包扎和缝针是同一伤势的阶段，不是新的独立伤势。浅疤是活动性伤势结束后的持续视觉状态。

## 4. 胸针 ObjectState

```yaml
object_state:
  object: 铜制胸针
  owner_id: 苏闻或UNKNOWN
  holder_id: 陈默
  in_use_by_id: null
  evidence_refs: [P04]

transitions:
  - event: 陈默交给陆岚
    holder_id: 陆岚
    owner_id: unchanged
    evidence_refs: [P04]
  - event: 陆岚第二幕前佩戴
    in_use_by_id: 陆岚
    holder_id: 陆岚
    evidence_refs: [P04]
  - event: 陆岚归还苏闻
    holder_id: 苏闻
    in_use_by_id: null
    evidence_refs: [P09, P11]
```

交给、佩戴和归还都不等于所有权转移。

## 5. 陆岚与陈默的多维 RelationshipState

```yaml
relationship_state:
  pair: [陆岚, 陈默]
  structural_relation:
    value: FORMER_PARTNERS
    evidence_refs: [P02]
  interaction_state:
    value: COOPERATING
    evidence_refs: [P08, P11]
  trust_state:
    value: DISTRUSTS
    evidence_refs: [P08, P12]
  communication_access:
    value: REMOVED
    evidence_refs: [P11]
```

“完成默契谢幕”只支持 `interaction_state=COOPERATING`，不支持 `trust_state=TRUSTS`，也不支持恢复过去关系。

## 6. 对白与内心状态

原文对白：

```text
我可以和你把这场演完，但这不等于我原谅你。
```

应拆为：

```yaml
dialogue_unit:
  speaker: 陆岚
  text: 我可以和你把这场演完，但这不等于我原谅你。
  evidence_refs: [P08]

expressed_stances:
  - stance_type: WILL_COOPERATE_TEMPORARILY
    target: 陈默
    supports:
      relationship_dimension: InteractionState
      value: COOPERATING
  - stance_type: REFUSES_FORGIVENESS
    target: 陈默
    does_not_support:
      relationship_dimension: TrustState
      value: TRUSTS
```

这句对白不能把陆岚真实内心写成已经信任陈默，也不能恢复通讯录好友权限。

## 7. VisualVariant 与临时状态组合

基础 CharacterVisualVariant：

- 陆岚旧海报长发版本；
- 陆岚当前短发版本；
- 陆岚拆线后浅疤长期版本。

临时视觉状态：

- 当晚银色礼服；
- 手帕包扎；
- 医用绷带；
- 临时佩戴胸针。

生成 P05 或 P11 的 Panel 前，可派生 ResolvedCharacterAppearance：

```yaml
resolved_character_appearance:
  base_variant: 陆岚当前短发版本
  character_state: 当前服装和左手伤势
  object_state: 是否佩戴或持有胸针
  temporary_overlays: [silver_dress, handkerchief_bandage]
```

临时礼服和绷带不应为陆岚创建大量永久 CharacterVisualVariant。
