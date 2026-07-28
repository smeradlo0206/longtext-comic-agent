# Golden Corpus V1：领域词汇与业务规则压力测试语料

本目录用于验证：

- `docs/domain_glossary.md`
- `docs/domain_rules.md`
- 后续核心Schema V1
- Agent结构化输出
- StoryBible、PanelSpec和QA规则

## 目录

- `01_identity_coreference/`：人物身份、别名、账号和共指
- `02_relationship_state/`：人物状态、服装、伤势和关系变化
- `03_complex_timeline/`：复杂时间与叙述顺序
- `04_reality_layers/`：梦境、想象、不可靠记忆和模拟未来
- `05_claims_knowledge/`：未经证实说法、秘密和KnowledgeState
- `06_storyboard_qa/`：Scene、StoryBeat、PanelSpec和QA
- `07_integrated_novel/`：完整综合集成小说
- `08_campus_factlock/`：校园通知、多版本更正与FactLock
- `micro_cases/`：30个单点边界案例
- `coverage_matrix.md`：核心概念覆盖情况

## 每个主题目录

- `source.md`：带段落编号的原始测试文本
- `questions.md`：要求Codex基于当前定义回答的问题
- `expected.json`：团队评审后填写的标准答案；首次不得由Codex自动填充
- `review_notes.md`：记录模型错误、定义缺口和修改意见

## 推荐测试流程

1. 固定当前领域词汇表Commit。
2. 让Codex只读取词汇表、规则、`source.md`和`questions.md`。
3. Codex输出回答，不修改文档。
4. 团队将每题分类为：`PASS`、`MODEL_ERROR`、`DEFINITION_GAP`、`AMBIGUOUS_DEFINITION`、`INSUFFICIENT_EVIDENCE` 或 `OUT_OF_SCOPE`。
5. 修改领域定义后进行回归测试。
6. 团队确认后再填写`expected.json`。

## 重要原则

Codex的第一次答案不是标准答案。标准答案必须由团队根据原文证据和已确认规则评审后形成。
