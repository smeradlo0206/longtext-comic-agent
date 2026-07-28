# Integrated Novel Example

本示例基于 `tests/golden_corpus/07_integrated_novel` 的钟楼案例，展示 V1.7-draft 如何把身份、时间、RealityLayer、知识、道具状态、分镜 QA 和依赖过期放在同一条链路中处理。它只说明领域语义，不实现 Schema、Agent、数据库或真实图像修复。

## 1. Character / Account / UnresolvedReference

| 原文线索 | 推荐表达 | 不应表达为 |
|---|---|---|
| 沈雾、小雾、沈编辑 | 同一 Character 的 EntityAlias / EntityMention | 多个 Character |
| 白栖 | Account | Character |
| 周璐是白栖主要使用者 | AccountAccessRelation(PRIMARY_OPERATOR) | 周璐发送所有白栖消息 |
| 社团成员共享密码 | AccountAccessRelation(SHARED_ACCESS) | 每条消息作者已知 |
| 第二条白栖消息作者 | AuthorshipClaim + UnresolvedReference | 直接绑定周璐或顾舟 |
| “Q-Zhou” 修改巡逻记录 | Account / Message / AuthorshipClaim 候选 | 某个姓 Zhou 的 Character |
| “他答应过会把阿岑带回来” | UnresolvedReference(candidate: 顾舟、其他社团成员、沈岑) | 强行绑定顾舟 |

## 2. NarrativeOrder vs StoryTime

| NarrativeOrder | StoryTime | RealityLayer | 说明 |
|---|---|---|---|
| P01-P04 | 2030-09-18 傍晚 | PRIMARY | 沈雾进入钟楼调查 |
| P05-P07 | 2023-09-18 夜 | FLASHBACK / MEMORY | 失踪夜回忆 |
| P10 | 2030 昏迷期间 | DREAM | 梦中钥匙转移不进入 PRIMARY |
| P19-P20 | 2030 地下档案室期间 | PRIMARY + Gu POV memory | 读者知道顾舟保存副本，沈雾和周璐不知道 |
| P37 | 2031 春候选片段 | UNKNOWN | 可能是真实未来、想象或章节预告，不新增 AUTHOR_FORESHADOW |

## 3. 同一历史夜晚的多次提及

失踪夜可作为同一历史事件组，而不是每次出现都创建新的失踪 Event。

| 来源 | 推荐对象 | 备注 |
|---|---|---|
| 沈雾记得第二次钟声前看到周璐从地下楼梯跑上来 | NarrativeMention + MEMORY Claim | 可支持周璐当晚从地下方向上来 |
| 周璐说顾舟捡起钥匙 | Claim(CONFLICTED) | 后续与周璐取出钥匙冲突 |
| 巡逻表副本 | Evidence / NarrativeMention | 只确认记录内容，不确认账号操作者 |
| 旧录像 | Evidence / Event | 只确认沈岑 23:06 独自离开泵房 |
| 录音自动播放 | Message / NarrativeMention | 不确认沈岑是否仍存活或谁设置播放 |

## 4. CharacterState 隔离

| 角色 | StoryTime / RealityLayer | 状态 |
|---|---|---|
| 沈雾 | 2023 FLASHBACK | 17 岁、长发、白色校服、右膝擦伤 |
| 沈雾 | 2030 PRIMARY | 短发、左眉浅疤、黄色安全背心，直到 P34 归还 |
| 沈雾 | P10 DREAM | 长发、七年前白校服、无眉疤 |
| 顾舟 | 2030 PRIMARY P16 后 | 左脚扭伤，直到离开钟楼前需要搀扶 |
| 顾舟 | P10 DREAM | 手臂流血，只在 DREAM 层有效 |

梦中白发、伤口、钥匙转移或顾舟台词不污染 PRIMARY。梦醒后沈雾开始怀疑周璐，可以作为 PRIMARY 的 KnowledgeState / Claim / CharacterState 变化。

## 5. ObjectState 链

```yaml
copper_key:
  2023_before_blackout:
    holder: Shen_Wu
    evidence: P05
  2023_after_blackout_to_2030_P25:
    holder: UNKNOWN
    note: 周璐后续承认保管，但完整取得和保管链不足
  2030_P25:
    holder: Zhou_Lu
    evidence: P25
  2030_P27:
    holder: Shen_Wu
    in_use_by: Shen_Wu
    location: archive_groove
    evidence: P27
  dream_P10:
    reality_layer: DREAM
    holder_transfer: Shen_Cen_to_Zhou_Lu
    canonical_primary_effect: none
```

黄色安全背心在 P03 交给沈雾，P34 归还顾舟。P34 之后若画面仍让沈雾穿背心，应判为临时装备状态延续错误。学生证在外套口袋里只能确认该时间点位置，不能确认沈岑死亡或外套七年连续持有。

## 6. Claim vs Canonical

| 说法 | 推荐表达 | Canonical 边界 |
|---|---|---|
| 周璐说顾舟捡起钥匙 | MEMORY / ACCUSATION Claim | 不确认顾舟捡钥匙 |
| 顾舟说自己在设备室恢复电力 | Claim，后续 Gu POV 部分支持 | 不自动证明全程位置 |
| 沈岑让周璐保管钥匙 | 周璐解释 Claim | 缺少独立证据，不确认委托 |
| 顾舟记得沈岑原话 | Gu POV memory Claim | 不创建 Canonical DialogueUnit |
| 白栖定时消息 | Message + AuthorshipClaim(UNRESOLVED) | 三人同在不排除预设 |

## 7. Reader Visible 不等于 Character Known

P19-P20 是 Gu POV。读者知道顾舟保存巡逻表副本，也知道他记得沈岑的某段话；沈雾和周璐在 P21 前仍不知道副本存在。P33 沈雾看到录像后，才更新为 KNOWS“沈岑 2023-09-18 23:06 后仍有活着离开泵房的证据”。

## 8. P25-P27 PanelSpec 示例

```yaml
panel_p25:
  must_show:
    - Zhou_Lu putting_first_aid_kit_down
    - copper_pendulum_key_from_inner_layer
  must_not_show:
    - Shen_Wu_already_holding_key
    - dream_well_key_throw

panel_p27:
  must_show:
    - Shen_Wu_taking_copper_key
    - key_transfer_Zhou_Lu_to_Shen_Wu
    - Shen_Wu_placing_key_into_pendulum_groove
    - wall_revealing_passage_to_old_well
    - Gu_Zhou_unable_to_walk_alone
  must_not_show:
    - Gu_Zhou_walking_normally
    - copper_key_still_held_by_Zhou_Lu_after_transfer
```

## 9. QAIssue 与 RepairPlan

| 错误 | QAIssue | RepairPlan |
|---|---|---|
| P30 把梦中周璐丢钥匙画成现实事实 | REALITY_LAYER_MIXING, hard_failure | 先修 PanelSpec，再整格重生成或局部替换错误动作 |
| P34 之后沈雾仍穿黄色安全背心 | OBJECT_STATE_STALE_CONTINUATION, hard_failure | 更新 ObjectState 结束态，标记依赖 PanelSpec/PromptSpec/QAResult 为 STALE |
| P27 漏掉铜钥匙交接 | MUST_SHOW_MISSING, hard_failure | 补 PanelSpec.must_show 后局部重绘或整格重生成 |
| 黄铜钥匙画成银色 | OBJECT_ATTRIBUTE_MISMATCH, high severity | 修复 VisualAsset / PromptSpec 并复检 |

视觉质量不能抵消 hard_failure。

## 10. DependencyEdge / STALE

当“沈雾已归还安全背心”或“铜钥匙 holder 已从周璐变为沈雾”被确认后，依赖旧状态的 Scene、StoryBeat、PanelSpec、PromptSpec、VisualAsset、QAResult 和 RepairPlan 都应标记 STALE 或进入重算。V1.7 只定义该语义，不实现完整 DependencyGraph。

## 11. MVP 暂缓项

- 不自动裁决第二条白栖消息作者。
- 不自动裁决 Q-Zhou 操作者。
- 不自动裁决沈岑最终去向。
- 不建立 AUTHOR_FORESHADOW RealityLayer。
- 不实现完整证据等级排名、嫌疑推理或最优 RepairPlan。
