# 微型边界案例库

这些案例用于单独测试一条概念边界，避免长文本中多个变量相互干扰。

## 使用规则

1. 每次运行只选择一个或少量案例。
2. Codex必须读取当前 `docs/domain_glossary.md` 和 `docs/domain_rules.md`。
3. 回答后由团队分类为：`PASS`、`MODEL_ERROR`、`DEFINITION_GAP`、`AMBIGUOUS_DEFINITION`、`INSUFFICIENT_EVIDENCE` 或 `OUT_OF_SCOPE`。
4. 不允许Codex把自己的首次回答直接写成标准答案。
5. 修改定义后，重跑本案例和所有相邻概念案例。

## 案例索引

| 文件 | 主题 |
|---|---|
| `01_same_event_multiple_mentions.md` | 同一事故的三次叙述 |
| `02_dream_state_leak.md` | 梦里白发 |
| `03_temporary_clothing_expiry.md` | 借来的雨衣 |
| `04_false_claim_not_fact.md` | 未经证实的指控 |
| `05_ambiguous_pronoun.md` | 两个她 |
| `06_alias_confirmed.md` | 网名被确认 |
| `07_similar_names_not_merge.md` | 周舟与周洲 |
| `08_flashback_historical_state.md` | 回忆中的长发 |
| `09_prediction_not_future_event.md` | 预言并未发生 |
| `10_simultaneous_different_locations.md` | 同一时刻 |
| `11_relative_time_anchor.md` | 前一天是谁的前一天 |
| `12_persistent_state_change.md` | 剪发 |
| `13_temporary_state_end.md` | 摘下眼镜 |
| `14_object_transfer_and_borrow.md` | 借书与归还 |
| `15_knowledge_leak.md` | 读者知道，人物不知道 |
| `16_relationship_surface_internal.md` | 表面和解 |
| `17_same_location_reality_switch.md` | 同一车站的回忆 |
| `18_location_change_continuous_action.md` | 跨门追逐 |
| `19_beat_vs_trivial_action.md` | 喝水是不是剧情节拍 |
| `20_one_beat_multi_panel.md` | 摔杯 |
| `21_panel_must_show.md` | 必须出现的钥匙 |
| `22_panel_must_not_show.md` | 追兵尚未出现 |
| `23_qa_hard_vs_soft.md` | 漂亮但画错 |
| `24_proposal_conflict.md` | 两个Agent相反结论 |
| `25_unknown_vs_uncertain.md` | 不知道还是不确定 |
| `26_causality_vs_precedence.md` | 先后不等于因果 |
| `27_unreliable_memory_partial.md` | 部分错误的记忆 |
| `28_exact_dialogue.md` | 不可改写的证词 |
| `29_dependency_stale_recompute.md` | 剪发时间被修正 |
| `30_story_within_story.md` | 角色讲述的虚构故事 |
