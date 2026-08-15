# 综合集成小说：钟楼第三次响起：核心词压力测试问题

## 作答要求

1. 只依据当前仓库中的 `docs/domain_glossary.md`、`docs/domain_rules.md` 和本目录 `source.md` 作答。
2. 每个判断必须引用段落编号，例如 `[P03]`。
3. 区分“原文明确事实”“合理推断”“未经证实说法”“UNKNOWN/UNCERTAIN”。
4. 不要为了得到唯一答案而补写原文没有的信息。
5. 对存在歧义的问题，列出所有可成立解释，并指出是词汇定义不足还是证据不足。
6. 本轮只回答问题，不修改领域词汇表。

## 问题

1. 列出全部Character、账号、别名和未知身份，不得把共享账号直接合并到单一人物。
2. 分别给出全文NarrativeOrder与StoryTime，标出FLASHBACK、DREAM、视角切换和未来片段。
3. 沈岑失踪是否是一个已确认Event？哪些更细粒度事件可以确认？
4. 同一“七年前停电夜”有多少NarrativeMention，是否都指向同一组Canonical Events？
5. 沈雾在2023、2030、梦境和2031片段中的CharacterState分别是什么？
6. 黄色安全背心、头灯、急救包、铜钥匙、学生证、复印件的ObjectState如何变化？
7. 周鹿关于钥匙的两次说法冲突时，Proposal和Canonical Data怎样处理？
8. 顾舟回忆沈岑原话能否直接作为Canonical DialogueUnit？
9. 读者在[P19]知道而沈雾不知道的信息，何时进入沈雾KnowledgeState？
10. 沈雾梦见周鹿扔钥匙后产生怀疑，梦境如何影响现实情绪而不修改现实事实？
11. 顾舟与周鹿都可能对应Q-Zhou，系统应怎样保留账号身份不确定性？
12. Scene应如何切分，特别是[P10]梦境、[P19]顾舟视角和[P37]未来片段？
13. 列出至少十二个StoryBeat，并指出哪些应合并或拆分为Panel。
14. 为[P25]-[P27]设计PanelSpec，明确钥匙交付的must_show和must_not_show。
15. 如果漫画在[P30]把周鹿画成正在把钥匙扔入井中，QA应如何判定？
16. 如果[P34]离开时沈雾仍穿黄色安全背心，是hard failure还是soft issue？
17. 关键对白“今天不是原谅你的日子”应如何影响RelationshipState？
18. [P28]学生证和外套能否证明沈岑死亡？
19. [P32]录像能推翻哪些旧认知，不能证明哪些结论？
20. [P36]定时消息出现时，三个在场人物是否都可排除为发送者？
21. [P37]应归类为FLASH_FORWARD、IMAGINATION、作者预示还是UNKNOWN？现有词汇表是否足够？
22. 哪些字段必须保存EvidenceRef，哪些判断应显式标UNCERTAIN？
23. 若修改“周鹿何时获得钥匙”，哪些Scene、Panel、VisualAsset和QA结果应标STALE？
24. 从完整流水线角度，找出至少五处可能造成上游定义错误向下游扩散的节点。
25. 基于当前词汇表给出本章MVP范围内无法稳定处理的复杂点。
