# 身份、账号和主张抽象示例

本文示例抽象自 Golden Corpus V1 的身份共指压力场景，只展示结构化方式，不复刻完整原文。

## 场景摘要

校园调查者收到一张匿名线索照片，照片背面写有警告语。随后，一个署名账号发来邮件，声称照片并非某论坛账号本人所发。调查中出现两位姓名读音相近的人，其中一人经营论坛账号，另一人曾知道该账号密码。原文还出现“他们”这样的未解析群体指代。

## 核心对象

| 类型 | 示例记录 | 说明 |
|---|---|---|
| Character | 调查者、林姓助教、近音姓名学生、老师、离校学生 | 人物实体，姓名近似不能自动合并。 |
| Account | 论坛账号 A、邮件账号 B | 数字身份，不等同于 Character。 |
| Message | 匿名照片警告、邮件、论坛新帖 | 信息载体，记录可见来源和内容。 |
| EntityAlias | 林姓助教 = 常用昵称 = 职务称呼 | 只有原文明确支持时才建立。 |
| EntityMention | “她”“小林”“Q”“账号 A”“他们” | 单次文本提及，可能未解析。 |
| UnresolvedGroupReference | “他们” | 未知成员和组织身份的群体指代。 |

## 关系与主张

```yaml
account_access_relations:
  - subject: 近音姓名学生
    account: 论坛账号A
    relation_type: PRIMARY_OPERATOR
    verification_status: CONFIRMED
  - subject: 林姓助教
    account: 论坛账号A
    relation_type: KNOWN_PASSWORD
    verification_status: SUPPORTED
    note: 知道密码不等于写下每条消息

authorship_claims:
  - message: 匿名照片警告
    candidate_author: UNKNOWN
    claim_type: HYPOTHESIS
    verification_status: UNRESOLVED
  - message: 论坛新帖
    visible_account: 论坛账号A
    candidate_author: UNRESOLVED
    claim_type: FACTUAL_ASSERTION
    temporal_scope: PRESENT
    verification_status: UNVERIFIED
  - message: 匿名照片警告
    speaker: 近音姓名学生
    claim_type: DENIAL
    content: 我没有发送这张照片
    verification_status: UNVERIFIED
```

## Claim 与 Event 的拆分

- Event：调查者收到邮件。
- Message：邮件账号 B 发来的邮件文本。
- Claim：邮件声称“照片不是论坛账号 A 的经营者发的”。
- AuthorshipClaim：邮件真实发送者是谁仍为 UNKNOWN。

这四层不能合并。系统可以确认“收到邮件”发生了，但不能因此确认邮件内容为事实，也不能确认署名账号背后的人。

## KnowledgeState 示例

| 角色 | 时间点 | knowledge_target | EpistemicStatus | 说明 |
|---|---|---|---|---|
| 调查者 | 收到照片后 | 照片作者 | UNAWARE | 照片存在，但作者未知。 |
| 调查者 | 收到邮件后 | “照片不是论坛账号经营者所发” | HEARD | 只是听闻邮件 Claim。 |
| 调查者 | 看见登录后 | 近音姓名学生经营论坛账号 A | KNOWS | 有直接登录证据和承认。 |
| 调查者 | 结尾 | 第一张照片作者 | UNAWARE | 证据仍不足。 |

## NarrativePerspective 示例

- 调查者受限视角：她听见身后有人说话，但无法确认说话者。
- 匿名消息视角：邮件内容只能作为 Message 和 Claim，不是全知旁白。
- 草稿改写视角：调查者把“账号 A 警告我”改为“尚未确认身份的人留下警告”，体现角色对 Claim 与 Canonical Fact 边界的修正。

## 处理结论

1. 近音姓名不是身份合并证据。
2. 账号经营者不是每条消息的默认作者。
3. 知道密码不是发送消息的充分证据。
4. “他们”保持 UnresolvedGroupReference，直到有证据说明成员或组织身份。
5. 角色听闻、怀疑和知道必须分别进入 KnowledgeState。
