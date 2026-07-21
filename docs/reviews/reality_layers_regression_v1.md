# Reality Layers Regression V1

测试范围：Golden Corpus V1 `tests/golden_corpus/04_reality_layers`。
定义基线：`docs/domain_glossary.md` V1.4-draft 与 `docs/domain_rules.md` 第 12 节 RealityLayer 判定与隔离规则。
结论：V1.4-draft 能表达设备画面、梦境、想象、污染记忆、预测模拟、现实状态隔离、相似道具误认、系统日志冲突和 Claim/Canonical Data 分离。合理 UNKNOWN/UNCERTAIN 保留。

## Q1-Q15 回归结果

| 题号 | 结论 | EvidenceRef | 使用概念 | 确定性 | Definition Gap | Ambiguous Definition | 备注 |
|---|---|---|---|---|---|---|---|
| Q1 | P02 不应直接定为 MEMORY 或 FLASH_FORWARD；可用 UNKNOWN 并保留 DREAM、UNRELIABLE_MEMORY、HYPOTHETICAL 候选。 | P01、P02、P04 | RealityLayer、NarrativeMention、Claim | UNCERTAIN | 否 | 否 | 设备会混入想象，任何画面不能直接当事实。 |
| Q2 | 梦中白发、右肩伤和红钥匙不修改 2029 年 PRIMARY 的 CharacterState 或 ObjectState。 | P02、P03 | CharacterState、ObjectState、RealityLayer | CONFIRMED | 否 | 否 | P03 明确黑发、无伤、无钥匙。 |
| Q3 | 醒来后的恐惧属于 PRIMARY，是现实后续 StateChange 或 CharacterState。 | P03 | StateChange、CharacterState、RealityLayer | CONFIRMED | 否 | 否 | 梦内容不继承，梦醒后的反应可以进入现实。 |
| Q4 | 许遥的说法是 HYPOTHESIS Claim，不是未来 Event。 | P04 | Claim、HYPOTHESIS、Event | CONFIRMED | 否 | 否 | 原文明确“只是推测，没有实验数据支持”。 |
| Q5 | 想象交付是 IMAGINATION 场景或 NarrativeMention；现实中不产生交付 Event，也不改变 ObjectState。 | P05 | IMAGINATION、NarrativeMention、ObjectState | CONFIRMED | 否 | 否 | 现实中没有钥匙，也没有交付动作。 |
| Q6 | 童年片段应为 UNRELIABLE_MEMORY 或 UNCERTAIN MEMORY；可确认设备出现该画面和叶澄确信，亲哥哥和挂件事实不能确认。 | P01、P06、P07 | UNRELIABLE_MEMORY、Claim、NarrativeMention | UNCERTAIN | 否 | 否 | V1.4 明确 UNRELIABLE_MEMORY 文档语义可用。 |
| Q7 | “哥哥”称谓不足以建立亲属 EntityRelation。 | P06、P07 | EntityRelation、UnresolvedReference、Claim | CONFIRMED | 否 | 否 | 可能是邻居家孩子，亲属关系保持 UNKNOWN。 |
| Q8 | 童年塑料挂件和现实金属钥匙不应自动合并为同一 StoryObject。 | P07、P08、P09 | StoryObject、Claim、ObjectState | UNKNOWN/UNCERTAIN | 否 | 否 | 相似外观和角色确信只能建立候选关联。 |
| Q9 | 可确认韩策发现现实红色金属钥匙、有人在 17:00-17:10 进入实验室；进入者身份 UNKNOWN。 | P08 | Event、ObjectState、UnresolvedReference | CONFIRMED/UNKNOWN | 否 | 否 | 未知进入者可用 actor=UNKNOWN 或 actor_ref=UnresolvedReference。 |
| Q10 | 叶澄认定同一把钥匙只能作为 Claim/KnowledgeState，不能覆盖对象身份判断。 | P09 | Claim、KnowledgeState、StoryObject | UNCERTAIN | 否 | 否 | 梦境可能影响识别。 |
| Q11 | 预测模拟不进入已发生 StoryTime；优先标记为 HYPOTHETICAL，不直接作为 FLASH_FORWARD。 | P10 | HYPOTHETICAL、StoryTime、RealityLayer | CONFIRMED | 否 | 否 | 日志标记为预测模拟而非记忆重放。 |
| Q12 | 日志被修改的争议保存为冲突 Claim；签名记录只支持生成后未修改，不能证明初始分类正确。 | P11 | Claim、EvidenceRef、Canonical Data | UNCERTAIN | 否 | 否 | 系统标签本身不是不可质疑事实。 |
| Q13 | P12 与梦境部分相似，不建立 CausalRelation，也不验证梦境为准确预见。 | P12 | Event、CausalRelation、Claim | CONFIRMED | 否 | 否 | 原文直接否定准确预见结论。 |
| Q14 | 非 PRIMARY 层状态不得跨层继承；只有梦醒后的现实反应、回避或行动可作为 PRIMARY 后续状态。 | P02、P03、P05、P10、P12 | RealityLayer、CharacterState、ObjectState | CONFIRMED | 否 | 否 | 外貌、伤势、道具隔离；恐惧反应进入现实。 |
| Q15 | 不新增 SIMULATION；预测模拟用 HYPOTHETICAL + source_medium/source_label/verification_status 表达。 | P10、P11 | RealityLayer、HYPOTHETICAL、Claim | CONFIRMED | 否 | 否 | 若后续大量出现设备模拟，再评审 Schema 枚举。 |

## 04 主题结论

- `PRIMARY` 是现实主线标准命名，`MAIN_REALITY` 只作旧称或说明性同义词。
- 设备画面不能因出现未来日期、角色确信或系统标签而直接成为 Canonical 事实。
- DREAM、IMAGINATION、HYPOTHETICAL、UNRELIABLE_MEMORY、FLASHBACK、FLASH_FORWARD 和 UNKNOWN 的判定边界已在 V1.4 文档语义中明确。
- `UNRELIABLE_MEMORY` 与 `FLASH_FORWARD` 在文档语义中可用；Schema 是否已有对应枚举由后续映射处理。
- 预测模拟优先使用 `HYPOTHETICAL`，不新增正式 `SIMULATION` 层。
- 非 PRIMARY 层的外貌、伤势和道具状态不污染 PRIMARY；梦醒后的恐惧等现实反应可以进入 PRIMARY。
- 角色 Claim、系统日志标签、画面内容和 Canonical Data 必须分离。
- 梦中红钥匙、童年塑料挂件和现实红色金属钥匙不能仅因相似自动合并。
- 相似现实事件不能反向证明梦境或模拟为真实预见，也不能单独建立 CausalRelation。

## 微型回归测试建议

| 微案例 | 回归结论 | 合理 UNKNOWN/UNCERTAIN | 新增冲突 |
|---|---|---|---|
| 02_dream_state_leak.md | 梦里白发不修改 PRIMARY；醒后心神不宁是 PRIMARY 后续状态；梦境、醒后现实应分 Scene。 | 梦境具体来源若未明可 UNKNOWN。 | 无。 |
| 04_false_claim_not_fact.md | “陈川删文件”是 Claim；管理员账号不能自动绑定陈川；Canonical 最多确认管理员账号删除文件且操作者 UNKNOWN。 | 操作者身份 UNKNOWN。 | 无。 |
| 08_flashback_historical_state.md | 回忆格查询大学当天历史 CharacterState；回忆结束恢复当前短发医生状态；同一地点不阻止 RealityLayer 切 Scene。 | 若回忆可靠性未被挑战，可用 FLASHBACK。 | 无。 |
| 09_prediction_not_future_event.md | 预言不是 Canonical Event；桥未断；绕路是 PRIMARY Event。 | 预言准确性为 CONTRADICTED 或 NOT_CONFIRMED。 | 无。 |
| 17_same_location_reality_switch.md | 同一车站也要按现实、童年回忆、回到现实切分 Scene；状态按各自 StoryTime 和 RealityLayer 查询。 | 童年细节不足的外观字段保持 UNKNOWN。 | 无。 |
| 25_unknown_vs_uncertain.md | 完全未给年龄为 UNKNOWN；“看起来二十多岁”可作为范围或视觉线索，不得指定精确年龄。 | 精确年龄 UNKNOWN。 | 无。 |
| 27_unreliable_memory_partial.md | 部分错误记忆不整体作废；雨夜 Claim 被气象记录反证，红车 Claim 被监控支持。 | 事故其他细节仍 UNCERTAIN。 | 无。 |
| 30_story_within_story.md | 童话事件不进入主线 Canonical Event；可作为 HYPOTHETICAL/IMAGINATION 或故事内叙述层；实体空间与主线隔离。 | 若需具体层名，可保留 candidate_layers。 | 无。 |

## 剩余问题

- 是否未来在 Schema enum 中新增 `SIMULATION` 仍可作为 P1/P2 议题，但 V1 暂缓。
- `source_medium`、`source_label`、`candidate_layers`、`reliability_reason` 等字段目前是文档语义建议，尚未实现 Schema。
- 系统日志签名、设备可信度和实验数据等级属于更完整的证据模型，本轮只规定其不能直接越级为 Canonical Data。
