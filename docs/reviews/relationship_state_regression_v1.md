# Relationship State Regression V1

测试范围：Golden Corpus V1 `tests/golden_corpus/02_relationship_state`，并复测指定微案例。
定义基线：`docs/domain_glossary.md` V1.2-draft 与 `docs/domain_rules.md` 第 8-10 节。
结论：V1.2-draft 能表达合作、疏远、不信任、通讯限制、道具临时持有、伤势阶段和临时视觉状态；姜芮是否改动机关、苏闻记忆真实性仍应保持 UNVERIFIED/UNCERTAIN。

## Q1-Q15 回归结果

| 题号 | 结论 | EvidenceRef | 使用概念 | 确定性 | Definition Gap | Ambiguous Definition | 细化维度 |
|---|---|---|---|---|---|---|---|
| Q1 | 陆岚长发是过去 CharacterState；短发是持续 StateChange 后的当前状态；银色礼服是 P03 到当晚演出结束的临时服装；黑色外套 P03 锁入柜子、P11 换回。 | P01、P03、P11、P12 | CharacterState、StateChange、CharacterVisualVariant | CONFIRMED | 否 | 否 | 视觉：短发用基础 Variant；礼服/外套是临时服装状态。 |
| Q2 | 银色礼服不持续到 P11，因为 P03 明确只用于当晚彩排和演出，P11 明确换回黑色外套；短发无结束事件且 P12 继续成立。 | P03、P11、P12 | CharacterState、StateChange、ResolvedCharacterAppearance | CONFIRMED | 否 | 否 | 视觉：礼服是临时 overlay，不建永久 Variant。 |
| Q3 | 建 4 个主要 Event：划伤、手帕包扎、缝三针、拆线；同一 InjuryState 经 ACUTE、FIRST_AID、MEDICALLY_TREATED、HEALED_WITH_MARK 阶段。 | P05、P12 | Event、StateChange、InjuryState | CONFIRMED | 否 | 否 | 伤势 phase：ACUTE -> FIRST_AID -> MEDICALLY_TREATED -> HEALED_WITH_MARK。 |
| Q4 | 胸针的 owner、holder、authorized_user、in_use_by 必须分开；陈默交给陆岚只改 holder，第二幕佩戴改 in_use_by，归还苏闻改 holder。 | P04、P09、P11 | StoryObject、ObjectState、EntityRelation | CONFIRMED | 否 | 否 | 物体：owner=苏闻或 UNKNOWN；holder=陈默->陆岚->苏闻；in_use_by=陆岚临时佩戴。 |
| Q5 | P04 后陆岚知道胸针来自苏闻、陈默要求她第二幕结束前戴着；不知道背后刻着事故当晚机关编号。 | P04 | KnowledgeState、EpistemicStatus、ObjectState | CONFIRMED | 否 | 否 | 知识：KNOWS 可见交付和佩戴要求；UNAWARE 编号。 |
| Q6 | “不是你的错”不足以把陆岚与姜芮关系改为和解；它只停止姜芮继续道歉，愧疚仍存在。 | P06 | DialogueUnit、ExpressedStance、RelationshipState | CONFIRMED | 否 | 否 | 关系：InteractionState 可缓和；TrustState/StructuralRelation 无充分变化。 |
| Q7 | 陆岚与陈默可临时合作完成演出，但“不等于我原谅你”明确阻止 TrustState 升为 TRUSTS。 | P08、P11、P12 | DialogueUnit、ExpressedStance、RelationshipState | CONFIRMED | 否 | 否 | structural_relation=FORMER_PARTNERS；interaction_state=COOPERATING；trust_state=DISTRUSTS 或 UNKNOWN；communication_access=REMOVED。 |
| Q8 | 默契谢幕不能反向证明恢复信任，只支持 InteractionState=COOPERATING。 | P08、P11、P12 | Event、RelationshipState、Claim | CONFIRMED | 否 | 否 | 关系：COOPERATING 不覆盖 TrustState 和 CommunicationAccess。 |
| Q9 | 公开合作、私人信任、通讯录好友状态不能压缩成单字段；必须用多维 RelationshipState。 | P08、P11、P12 | RelationshipState | CONFIRMED | 否 | 否 | structural_relation、interaction_state、trust_state、communication_access 独立 EvidenceRef。 |
| Q10 | 苏闻关于姜芮的记忆是 MEMORY Claim，可关联 NarrativeMention；不能直接成为 Canonical Event。 | P09 | Claim、NarrativeMention、Proposal | UNCERTAIN | 否 | 否 | 记忆：verification_status=UNVERIFIED 或 PARTIALLY_SUPPORTED。 |
| Q11 | 系统应同时保留苏闻 MEMORY Claim 与姜芮 DENIAL Claim；因无其他证据，不选择一方为 Canonical。 | P09、P10 | Claim、Proposal、Canonical Data | CONFIRMED | 否 | 否 | 姜芮是否改动机关：UNKNOWN/UNVERIFIED。 |
| Q12 | 陆岚至少需要长发旧海报 Variant、当前短发 Variant、拆线后浅疤 Variant；银色礼服、包扎、绷带、胸针是临时状态/overlay。 | P01、P03、P05、P11、P12 | CharacterVisualVariant、ResolvedCharacterAppearance、InjuryState | CONFIRMED | 否 | 否 | 视觉：基础 Variant + 临时服装/伤势/道具解析。 |
| Q13 | 拆线后伤口愈合表示活动性 injured 状态结束；浅疤作为持续视觉状态开始。 | P05、P12 | InjuryState、StateChange、CharacterState | CONFIRMED | 否 | 否 | 伤势 phase：MEDICALLY_TREATED/RECOVERING -> HEALED_WITH_MARK。 |
| Q14 | P11 画陆岚仍穿银色礼服是 hard failure，因为违反明确服装状态。 | P03、P11 | QAIssue、CharacterState、PanelSpec | CONFIRMED | 否 | 否 | QA：人物状态错误，不是软性审美问题。 |
| Q15 | 明确行为可建 Event/StateChange；愧疚、未原谅、信任缺失、记忆不确定等必须用 ExpressedStance、Claim 或多维 RelationshipState 表达。 | P03-P12 | Event、StateChange、RelationshipState、Claim、ExpressedStance | CONFIRMED/UNCERTAIN | 否 | 否 | 行为不自动推断内心；一项证据只更新直接维度。 |

## 02 主题结论

- RelationshipState 已能同时表达合作、疏远、不信任和通讯限制。
- 完成默契谢幕只支持 `interaction_state=COOPERATING`，不支持 `trust_state=TRUSTS`。
- 胸针临时持有和佩戴不会错误改变 owner。
- 银色礼服在 P11 前结束，不会延续到次日。
- 左手伤势可从 ACUTE、FIRST_AID、MEDICALLY_TREATED 到 HEALED_WITH_MARK。
- 临时礼服、绷带和胸针不会创建大量永久 CharacterVisualVariant。
- 姜芮是否改动机关仍是 UNKNOWN/UNVERIFIED；苏闻记忆不是 Canonical Event。

## 微型回归测试

| 微案例 | 是否解决原定义问题 | 合理 UNKNOWN/UNCERTAIN | 新增概念冲突 | 视觉版本组合爆炸风险 |
|---|---|---|---|---|
| 03_temporary_clothing_expiry.md | 已解决。红色雨衣 P01 生效，P02 归还结束；P03 红雨衣为 hard failure。ObjectState 区分 owner=向导或 UNKNOWN、holder=顾言->向导。 | owner 若仅有“借来”可保持 UNKNOWN 或向导 SUPPORTED。 | 无。 | 无，雨衣是临时服装/道具状态，不建永久 Variant。 |
| 12_persistent_state_change.md | 已解决。周三默认短发；短发到 P03 一个月后“长到肩上”结束，并建立新 StateChange。 | 剪发前发型 UNKNOWN，除非另有证据。 | 无。 | 无，短发/肩长发可作为长期发型 Variant 或状态阶段。 |
| 13_temporary_state_end.md | 已解决。眼镜可见状态 P02 摘下结束；holder 不结束，因为放进口袋仍由方启持有；P03 不应戴眼镜。 | 眼镜 owner 若未说明为 UNKNOWN。 | 无。 | 无，伪装眼镜是临时 overlay。 |
| 14_object_transfer_and_borrow.md | 已解决。owner 始终陈禾；holder 陈禾->许安->陈禾；借出不是永久转移，归还后许安不再持有。 | 无关键 UNKNOWN。 | 无。 | 无。 |
| 16_relationship_surface_internal.md | 已解决。不能只写“已和解”；P01 是 ExpressedStance，P02 确认仍不信任，P03 支持合作。 | StructuralRelation 未给出时 UNKNOWN。 | 无。 | 无。 |
| 23_qa_hard_vs_soft.md | 已解决。长发错误和缺少怀表是 hard failure；光影僵硬是 soft issue；美观不能抵消状态/道具错误。 | 无关键 UNKNOWN。 | 无。 | 无。 |
| 29_dependency_stale_recompute.md | 部分解决。第三、第四章短发 CharacterState、依赖它的 PanelSpec/PromptSpec/ImageCandidate/RenderedPanel 变 STALE；不必整本重生成，只重算依赖受影响区间。 | 若缺少依赖图，具体受影响页面列表 UNKNOWN。 | 无。 | 无，但提示需要依赖边支持局部重算。 |

## 剩余问题

- RelationshipState 的字段落库、兼容迁移和枚举校验尚未进入 Pydantic Schema，本轮只更新领域语义。
- owner_id 在“留下的胸针”这类措辞下可能需要人工审核：可标为苏闻 SUPPORTED，或 UNKNOWN 并记录苏闻强关联。
- ResolvedCharacterAppearance 目前是派生概念，不作为 P0 持久化对象；后续如果生成链路需要缓存，可进入 P1 设计。
- 医学严重程度、伤残等级、复杂所有权和完整社会关系本体明确推迟到 P1/P2。
