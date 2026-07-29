# 给Codex的领域词汇压力测试提示词

你正在当前GitHub仓库中执行“领域词汇和业务规则压力测试”。

## 本次目标

依据当前版本的：

- `docs/domain_glossary.md`
- `docs/domain_rules.md`

回答指定黄金测试目录中的问题，暴露定义缺口、概念歧义和证据不足。

## 严格限制

1. 本轮只分析，不修改任何仓库文件。
2. 不得把自己的回答写入`expected.json`。
3. 不得修改`domain_glossary.md`或`domain_rules.md`。
4. 不得把合理猜测写成Canonical事实。
5. 所有判断必须引用`source.md`中的段落编号。
6. 区分：原文明确事实、合理但未确认的推断、人物说法或Claim、UNKNOWN、UNCERTAIN。
7. 对当前定义无法唯一回答的问题，必须明确指出是原文证据不足、领域定义存在歧义，还是超出MVP范围。
8. 不要为了显得完整而补写原文没有的信息。

## 本轮测试目录

将下面路径替换为需要测试的目录，例如：

`tests/golden_corpus/03_complex_timeline`

## 执行步骤

1. 阅读`docs/domain_glossary.md`。
2. 阅读`docs/domain_rules.md`。
3. 阅读指定目录的`source.md`。
4. 阅读指定目录的`questions.md`。
5. 按问题顺序逐题作答。
6. 最后生成“定义压力测试摘要”。

## 每题输出格式

### Q{编号}

**结论：**

**依据：**
- `[Pxx]`：
- 领域词汇或规则：

**确定性：**
- `CONFIRMED` / `UNCERTAIN` / `UNKNOWN`

**对象分类：**
例如Event、NarrativeMention、StateChange、CharacterState、Claim、Proposal等。

**当前定义是否足够：**
- `YES`
- `NO_DEFINITION_GAP`
- `NO_AMBIGUOUS_DEFINITION`
- `NO_INSUFFICIENT_EVIDENCE`
- `OUT_OF_SCOPE`

**潜在下游风险：**
说明错误结论会怎样影响时间线、状态、分镜、视觉资产或QA。

## 最终摘要

1. 当前定义足以回答的问题；
2. 存在Definition Gap的问题；
3. 存在Ambiguous Definition的问题；
4. 正确答案应为UNKNOWN/UNCERTAIN的问题；
5. 疑似模型没有遵守定义的问题；
6. 建议团队重点评审的概念；
7. 不提出直接修改方案，只说明问题位置。

现在开始执行指定测试。
