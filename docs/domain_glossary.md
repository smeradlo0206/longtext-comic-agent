# 领域词汇表 V1

## 文档用途

本文是“长文本多 Agent 连续漫画生成系统”的领域概念唯一正式定义来源。它用于统一产品、Schema、Agent、数据库、QA 和视觉生产模块对同一名称的理解。其他文档引用本文词汇，不再重复定义。

当前版本：V1.9-draft
维护负责人：待团队指定
最后更新时间：2026-07-21

## 使用规则

- Schema、Agent、StoryBible 等代码名保持英文，第一次出现时附中文。
- 每个词汇只在本文有一个正式定义位置。
- Agent 只能输出 Proposal（候选结果），不能直接写 Canonical Data（正式事实）。
- 关键故事事实必须能通过 EvidenceRef（原文证据引用）追溯到 SourceChunk（原文片段）。
- 无原文支持、证据不足或叙述不可靠的内容必须标记为 UNKNOWN 或 UNCERTAIN。
- PanelSpec（单格分镜规范）必须与模型供应商解耦；供应商字段进入 PromptSpec（模型提示词规范）。

## V1.9-draft 变更摘要

- 基于 `tests/golden_corpus/micro_cases` 回归结果，确认 Q01-Q17、Q19-Q29 的 V1.8 语义基本足够。
- 补清连续跨地点动作的 Scene 粒度：地点变化仍是强切分信号，但追逐、搬运、移动、交接等连续动作可通过相邻 Scene、StoryBeat 序列和 PanelSpec 连续动作说明保持连贯。
- 明确每个 PanelSpec 必须保留自己的 location_id，不得为了保持一个 Scene 而混淆不同地点的 LocationState。
- 补清 story-within-story 语义：角色讲述的童话、寓言、剧本或小说片段不进入 PRIMARY 主线 Canonical Event，嵌入故事中的 Entity/Event/ObjectState 与主线隔离。
- 本轮不新增正式 `FICTIONAL_STORY` RealityLayer，不实现 ActionSequenceV1、EmbeddedNarrativeScopeV1、故事内故事实体库或自动 Scene 切分器。

## V1.8-draft 变更摘要

- 新增 FactLock 文档层概念，用于标记通知、公告、海报和分镜文字中必须保持精确的关键事实字段。
- 强化通知类时间字段、地点字段、日期/星期、数字单位和联系人身份的精确性边界。
- 明确最终有效事实来自最新有效 Revision，字段级覆盖、继承、确认不变和旧版本 STALE 必须保留 EvidenceRef。
- 补清信息省略与 hard failure 的边界：完整通知目标下漏关键字段可硬失败，背景板省略可作为 completeness issue。
- 本轮只修订领域文档，不实现 FactLockV1、字段级 Revision 数据库、通知解析 Agent、真实 QA 或日历校验器。

## V1.7-draft 变更摘要

- 强化综合小说链路一致性，覆盖共享账号、复杂时间、RealityLayer、KnowledgeState、ObjectState、PanelSpec、QA 与 STALE 传播。
- 明确共享账号、账号名、账号密码知情者不等于单一 Character，账号操作者不等于具体 Message 作者。
- 强化多个 NarrativeMention、Claim、记录、录像、录音或回忆回指同一历史事件组，不重复制造 Canonical Event。
- 补清读者可见与角色所知、DREAM/未来片段与 PRIMARY、后续证据与历史 KnowledgeState 的隔离。
- 补充 DependencyEdge / STALE 传播语义与 MVP out-of-scope 边界。

## V1.6-draft 变更摘要

- 强化 Storyboard QA、PanelSpec、RepairPlan 和 QAIssue 的文档语义。
- 补清 Scene 粒度规则，明确 RealityLayer 改变、StoryTime 跳跃、地点明显改变时通常必须切 Scene。
- 补充 StoryBeat-to-Panel 拆分规则，连续动作的关键时刻、信息揭示和物体转移不得随意压成一格。
- 强化 PanelSpec 的 must_show / must_not_show、关键 DialogueUnit、回忆状态绑定和 ObjectState 结束态。
- 明确 QA hard failure 优先级、RepairPlan 策略选择阈值，以及关键道具颜色/材质错误严重性。

## V1.5-draft 变更摘要

- 强化 Claim、KnowledgeState、NarrativePerspective 与 Canonical Data 的边界。
- 明确读者可见事实不等于人物 KnowledgeState。
- 明确后续证据不能反向修改角色历史认知。
- 明确 CommitService 对冲突 Proposal 只提交中性已证事实。
- 补充 ObjectState 只记录证据支持的位置或持有状态，不自动补偷窃、栽赃或完整移动路径。

## V1.4-draft 变更摘要

- 澄清 RealityLayer 判定矩阵，统一 `PRIMARY` 作为现实主线命名，`MAIN_REALITY` 仅作为旧称或说明性同义词。
- 明确设备重放、污染记忆、预测模拟和未来片段的边界。
- 强化跨 RealityLayer 状态隔离，非 PRIMARY 层状态不默认写入 PRIMARY。
- 明确角色 Claim、系统标签、画面内容和 Canonical Data 不能混用。
- 补充相似道具不能仅凭颜色、外观或角色确信自动合并为同一 StoryObject。

## V1.3-draft 变更摘要

- 细化 StoryTime 的时间精度、相对时间锚点和解析状态说明。
- 明确 TemporalRelation 中 SIMULTANEOUS 与 OVERLAPS 的边界。
- 补充同一历史事件多次叙述、事件簇和 NarrativeMention 的处理规则。
- 补充 ObjectState 未知区间与 actor UNKNOWN 状态变化事件的表达方式。
- 强化 BEFORE 不自动支持 CausalRelation，避免把时间先后误判为因果。

## V1.2-draft 变更摘要

- RelationshipState 多维化，区分结构关系、互动状态、信任状态和通讯权限。
- ObjectState 明确 owner、holder、authorized_user、in_use_by、location 和 condition，避免临时持有误改所有权。
- 新增 InjuryState 最小语义，覆盖急性受伤、包扎、医疗处理、恢复、愈合和疤痕阶段。
- 澄清 CharacterVisualVariant 与临时服装、绷带、血迹、单场道具等临时视觉状态的边界。
- 增加行为、对白和内心状态推断限制：可观察合作不等于信任恢复，角色说法不等于真实内心。

## V1.1-draft 变更摘要

- 补充身份层级：区分 Character、EntityAlias、EntityMention、UnresolvedReference 和 UnresolvedGroupReference。
- 补充账号和消息语义：新增 Account、Message、AccountAccessRelation 和 AuthorshipClaim。
- 引入 Claim 体系，明确 claim_type 和 verification_status，防止角色说法直接升级为 Canonical Event。
- 强化 KnowledgeState，新增 EpistemicStatus，区分角色所知、读者所知和事实层。
- 强化 NarrativePerspective，要求记录叙事来源、可见性边界和可靠性。
- 明确 Organization 与临时群体指代的边界，避免把“他们”等未解析群体强制归入组织。

## 目录

- [核心词汇速查表](#核心词汇速查表)
- [第一组：项目、原文和证据](#第一组项目原文和证据)
- [第二组：故事世界](#第二组故事世界)
- [第三组：时间、叙事层和状态](#第三组时间叙事层和状态)
- [第四组：场景和剧情组织](#第四组场景和剧情组织)
- [第五组：视觉与漫画生产](#第五组视觉与漫画生产)
- [第六组：质检、修复和工作流](#第六组质检修复和工作流)
- [概念对比](#概念对比)
- [团队评审清单](#团队评审清单)

## 核心词汇速查表

| 英文代码名 | 中文名称 | 所属阶段 | 优先级 | 是否需要证据 |
|---|---|---|---|---|
| Project | 项目 | 项目、原文和证据 | P0 | 否 |
| ProjectSpec | 项目配置规范 | 项目、原文和证据 | P0 | 否 |
| SourceDocument | 原始文档 | 项目、原文和证据 | P0 | 否 |
| SourceChapter | 原文章节 | 项目、原文和证据 | P0 | 否 |
| SourceChunk | 原文片段 | 项目、原文和证据 | P0 | 否 |
| EvidenceRef | 原文证据引用 | 项目、原文和证据 | P0 | 是 |
| NarrativeOrder | 叙述顺序 | 项目、原文和证据 | P0 | 视情况而定 |
| Revision | 版本修订 | 项目、原文和证据 | P0 | 否 |
| Proposal | 候选结果 / 候选建议 | 项目、原文和证据 | P0 | 视情况而定 |
| Canonical Data | 正式事实 / 标准数据 | 项目、原文和证据 | P0 | 是 |
| Confidence | 置信度 | 项目、原文和证据 | P0 | 否 |
| Entity | 实体 | 故事世界 | P0 | 是 |
| Character | 人物 | 故事世界 | P0 | 是 |
| Location | 地点 | 故事世界 | P0 | 是 |
| StoryObject | 剧情道具 | 故事世界 | P0 | 是 |
| Organization | 组织 | 故事世界 | P0 | 是 |
| UnresolvedGroupReference | 未解析群体指代 | 故事世界 | P0 | 是 |
| EntityAlias | 实体别名 | 故事世界 | P0 | 是 |
| EntityMention | 实体文本提及 | 故事世界 | P0 | 是 |
| UnresolvedReference | 未解析指代 | 故事世界 | P0 | 是 |
| EntityRelation | 实体关系 | 故事世界 | P0 | 是 |
| Account | 账号 | 故事世界 | P0 | 是 |
| Message | 消息 | 故事世界 | P0 | 是 |
| AccountAccessRelation | 账号访问关系 | 故事世界 | P0 | 是 |
| AuthorshipClaim | 作者身份主张 | 故事世界 | P0 | 是 |
| Claim | 主张 | 故事世界 | P0 | 是 |
| ExpressedStance | 表达态度 | 故事世界 | P0 | 是 |
| Event | 标准事件 | 故事世界 | P0 | 是 |
| NarrativeMention | 事件的一次叙述 | 故事世界 | P0 | 是 |
| CausalRelation | 因果关系 | 故事世界 | P0 | 是 |
| NarrativePerspective | 叙事视角 | 故事世界 | P0 | 是 |
| StoryTime | 故事时间 | 时间、叙事层和状态 | P0 | 视情况而定 |
| TemporalRelation | 时间关系 | 时间、叙事层和状态 | P0 | 是 |
| RealityLayer | 叙事现实层 | 时间、叙事层和状态 | P0 | 是 |
| StateChange | 状态变化 | 时间、叙事层和状态 | P0 | 是 |
| CharacterState | 人物状态 | 时间、叙事层和状态 | P0 | 是 |
| InjuryState | 伤势状态 | 时间、叙事层和状态 | P0 | 是 |
| KnowledgeState | 人物知识状态 | 时间、叙事层和状态 | P0 | 是 |
| RelationshipState | 人物关系状态 | 时间、叙事层和状态 | P0 | 是 |
| ObjectState | 道具状态 | 时间、叙事层和状态 | P0 | 是 |
| LocationState | 地点状态 | 时间、叙事层和状态 | P0 | 是 |
| Scene | 场景 | 场景和剧情组织 | P0 | 是 |
| StoryBeat | 剧情节拍 | 场景和剧情组织 | P0 | 是 |
| DialogueUnit | 对白单元 | 场景和剧情组织 | P0 | 是 |
| NarrationUnit | 旁白单元 | 场景和剧情组织 | P0 | 是 |
| TranslationDecision | 漫画转译决策 | 场景和剧情组织 | P0 | 是 |
| StoryBible | 故事设定总库 | 场景和剧情组织 | P0 | 是 |
| VisualBible | 视觉设定总库 | 视觉与漫画生产 | P0 | 视情况而定 |
| StyleBible | 画风规范 | 视觉与漫画生产 | P0 | 否 |
| CharacterVisualProfile | 人物基础视觉档案 | 视觉与漫画生产 | P0 | 视情况而定 |
| CharacterVisualVariant | 人物视觉版本 | 视觉与漫画生产 | P0 | 视情况而定 |
| VisualAsset | 视觉资产 | 视觉与漫画生产 | P0 | 视情况而定 |
| PageSpec | 页面规划规范 | 视觉与漫画生产 | P0 | 是 |
| PanelSpec | 单格分镜规范 | 视觉与漫画生产 | P0 | 是 |
| PromptSpec | 模型提示词规范 | 视觉与漫画生产 | P0 | 继承 PanelSpec |
| GenerationJob | 图片生成任务 | 视觉与漫画生产 | P0 | 继承 PanelSpec |
| ImageCandidate | 图片候选 | 视觉与漫画生产 | P0 | 继承生成任务 |
| RenderedPanel | 已渲染漫画格 | 视觉与漫画生产 | P0 | 继承 PanelSpec |
| RenderedPage | 已渲染漫画页 | 视觉与漫画生产 | P0 | 继承 PageSpec |
| QAResult | 质检结果 | 质检、修复和工作流 | P0 | 视情况而定 |
| FactLock | 事实锁定项 | 质检、修复和工作流 | P0 | 是 |
| QAIssue | 具体质检问题 | 质检、修复和工作流 | P0 | 视情况而定 |
| RepairPlan | 修复方案 | 质检、修复和工作流 | P0 | 视情况而定 |
| DependencyEdge | 依赖关系 | 质检、修复和工作流 | P0 | 否 |
| Approval | 审核记录 | 质检、修复和工作流 | P0 | 视情况而定 |
| WorkflowRun | 工作流运行记录 | 质检、修复和工作流 | P0 | 否 |
| AgentRun | Agent 运行记录 | 质检、修复和工作流 | P0 | 否 |
| Checkpoint | 工作流检查点 | 质检、修复和工作流 | P0 | 否 |
| CommitService | 正式数据提交服务 | 质检、修复和工作流 | P0 | 否 |
| ContextBuilder | Agent 上下文组装器 | 质检、修复和工作流 | P0 | 否 |
| Provider | 外部模型服务适配器 | 质检、修复和工作流 | P0 | 否 |
| Idempotency | 幂等性 | 质检、修复和工作流 | P0 | 否 |

## 第一组：项目、原文和证据

## Project

中文名称：项目  
所属阶段：项目、原文和证据  
优先级：P0  
精确定义：Project 表示一次独立漫画生成工作的业务容器，包含输入文本、配置、版本、运行记录、StoryBible、VisualBible 和最终产物。不同 Project 之间的源文档、实体和状态默认隔离。  
识别规则：当用户开始处理一部长篇小说、一篇校园新闻、宣传稿或通知时建立。  
正例：为《雨后的操场》小说创建一个 `project-linxia`。  
反例：单个 SourceChunk 或一次 AgentRun 不是 Project。  
容易混淆：ProjectSpec 是配置，Project 是容器；WorkflowRun 是一次运行，不是项目本身。  
产生者：API、项目创建服务。  
读取者：所有服务、Agent、工作流。  
是否必须包含 EvidenceRef：否。  
候选Schema：ProjectSpecV1、ProjectV1。  
备注或待确认问题：无。  

## ProjectSpec

中文名称：项目配置规范  
所属阶段：项目、原文和证据  
优先级：P0  
精确定义：ProjectSpec 表示约束整个 Project 的配置，包括项目类型、忠实度模式、阅读方向、预算、是否允许新增事件或对白等。它是后续 Agent 判断允许行为的上游规则。  
识别规则：创建 Project 时必须建立，配置变更必须产生新 Revision。  
正例：`fidelity_mode=CANON_STRICT`、`allow_new_events=false`。  
反例：某一格的镜头角度不是 ProjectSpec。  
容易混淆：StyleBible 管画风，ProjectSpec 管业务约束。  
产生者：用户、API。  
读取者：CommitService、ContextBuilder、所有 Agent。  
是否必须包含 EvidenceRef：否。  
候选Schema：ProjectSpecV1。  
备注或待确认问题：预算字段的最终单位需团队确认。  

## SourceDocument

中文名称：原始文档  
所属阶段：项目、原文和证据  
优先级：P0  
精确定义：SourceDocument 表示一次导入的原始文件元数据，包括文件名、格式、checksum、存储位置和导入时间。它不直接表示文本中的故事事实。  
识别规则：每次上传 TXT、DOCX、PDF 等源文件时建立；相同 Project 下相同 checksum 重复导入应复用。  
正例：`source.txt` 对应一个 SourceDocument。  
反例：从原文中提取出的“旧车站”不是 SourceDocument。  
容易混淆：SourceChapter 和 SourceChunk 是 SourceDocument 的结构化子单元。  
产生者：DocumentParser、导入服务。  
读取者：文档查询 API、SourceRepository、ContextBuilder。  
是否必须包含 EvidenceRef：否。  
候选Schema：SourceDocumentV1。  
备注或待确认问题：EPUB 支持需团队确认。  

## SourceChapter

中文名称：原文章节  
所属阶段：项目、原文和证据  
优先级：P0  
精确定义：SourceChapter 表示 SourceDocument 中按标题、规则或默认策略识别出来的章节边界。它服务于检索和并行处理，不代表故事世界中的章节事件。  
识别规则：遇到“第 X 章”“Chapter X”等标题时建立；无标题文本建立默认章节。  
正例：`第一章 雨后的操场`。  
反例：漫画第 3 页不是 SourceChapter。  
容易混淆：Scene 是故事结构，SourceChapter 是原文结构。  
产生者：DocumentParser。  
读取者：API、ContextBuilder、抽取 Agent。  
是否必须包含 EvidenceRef：否。  
候选Schema：SourceChapterV1。  
备注或待确认问题：复杂标题规则后续扩展。  

## SourceChunk

中文名称：原文片段  
所属阶段：项目、原文和证据  
优先级：P0  
精确定义：SourceChunk 表示可追溯、可排序、带 checksum 的最小原文证据单元。它保留原文内容和位置，用于支撑 Entity、Event、StateChange、PanelSpec 等关键事实。  
识别规则：文档导入后按段落或稳定切分策略建立，不允许因为空行丢失正文顺序。  
正例：`林晓剪去了长发，带着父亲留下的怀表回到旧车站。`  
反例：Agent 对该段的摘要不是 SourceChunk。  
容易混淆：EvidenceRef 指向 SourceChunk；SourceChunk 本身不是引用。  
产生者：DocumentParser。  
读取者：所有抽取 Agent、ContextBuilder、QA、CommitService。  
是否必须包含 EvidenceRef：否。  
候选Schema：SourceChunkV1。  
备注或待确认问题：十万字长文的 chunk 粒度需压力测试校准。  

## EvidenceRef

中文名称：原文证据引用  
所属阶段：项目、原文和证据  
优先级：P0  
精确定义：EvidenceRef 表示一个候选或正式事实回指 SourceChunk 的证据，必要时包含 quote_start、quote_end 和 quote_text。它证明事实来自原文，而不是模型自由发挥。
识别规则：任何关键故事事实、状态变化、关系、PanelSpec 约束、FactLock 字段或字段级 Revision 覆盖/确认都应绑定至少一个 EvidenceRef。
正例：Event“林晓回到旧车站”引用包含该句的 chunk；通知最终决赛日期引用更正说明；“报名截止时间不变”引用初版具体值和更正说明。
反例：`confidence=0.9` 不是 EvidenceRef。  
容易混淆：EvidenceRef 是证据指针，不是事实本身。  
产生者：抽取 Agent、确定性服务。  
读取者：CommitService、QA、审核界面。  
是否必须包含 EvidenceRef：是。  
候选Schema：EvidenceRefV1。  
备注或待确认问题：quote_text 是否必须逐字匹配 SourceChunk 可后续加强。通知、公告、海报类 FactLock 字段建议保留原文格式，便于 text_accuracy=1.00 校验。

## NarrativeOrder

中文名称：叙述顺序  
所属阶段：项目、原文和证据  
优先级：P0  
精确定义：NarrativeOrder 表示内容在原文中出现的顺序。它不等同于故事世界中事件真实发生的先后。  
识别规则：根据 SourceChapter、SourceChunk 和 NarrativeMention 的 order 字段确定。  
正例：小说先写“十年后”，再回忆“大学时期第一次见面”，叙述顺序是现实段在前、回忆段在后。  
反例：大学见面发生在十年前，这属于 StoryTime，不是 NarrativeOrder。  
容易混淆：StoryTime 描述故事世界发生位置，NarrativeOrder 描述文本出现位置。  
产生者：DocumentParser、叙事结构服务。  
读取者：TemporalRelation Agent、Scene 切分、QA。  
是否必须包含 EvidenceRef：视情况而定。  
候选Schema：NarrativeMentionV1、SourceChunkV1.order。  
备注或待确认问题：无。  

## Revision

中文名称：版本修订  
所属阶段：项目、原文和证据  
优先级：P0  
精确定义：Revision 表示同一记录或字段的可追踪修订版本，用于支持审核、回滚、幂等写入、字段级覆盖、确认不变、作废和依赖重算。Revision 不表示故事时间变化。
识别规则：Schema、ProjectSpec、Canonical Data 或审核后的关键记录发生内容变化时递增。通知、公告或海报存在初版、更正、补充通知时，应按字段记录 created、overridden、confirmed_unchanged、added 或 stale 状态。
正例：VisualBible 审核后从 revision 1 变为 revision 2；初版创建决赛日期，第一份更正覆盖决赛日期并确认报名截止不变，第二份补充覆盖现场名额并新增材料截止。
反例：人物从长发变短发不是 Revision，而是 StateChange；第二份补充通知没有提到会场时，不代表会场字段被整份覆盖为空。
容易混淆：Revision 是工程版本；StoryTime 是故事时间。  
产生者：CommitService、版本服务。  
读取者：WorkflowRun、DependencyEdge、审核界面。  
是否必须包含 EvidenceRef：否。  
候选Schema：BaseRecordV1.revision。  
备注或待确认问题：字段级 Revision 数据库、覆盖策略枚举和迁移设计暂不进入 V1.8。

## Proposal

中文名称：候选结果 / 候选建议  
所属阶段：项目、原文和证据  
优先级：P0  
精确定义：Proposal 表示 Agent 或程序提交的候选结构化结果，尚未成为正式事实。Proposal 可以重复、冲突、置信度不足或被拒绝。  
识别规则：任何 Agent 输出的实体、事件、关系、状态变化、修复方案等都先以 Proposal 存在。  
正例：EventProposalV1 认为“林晓剪去长发”是一个事件。  
反例：已被 CommitService 写入的 Canonical Event 不是 Proposal。  
容易混淆：Canonical Data 是审核/合并后的正式事实；Proposal 是候选。  
产生者：Agent、Mock Provider、辅助程序。  
读取者：SchemaValidator、CommitService、合并服务、QA。  
是否必须包含 EvidenceRef：视情况而定；故事事实类 Proposal 必须包含。  
候选Schema：EntityProposalV1、EventProposalV1、StateChangeProposalV1。  
备注或待确认问题：无。  

## Canonical Data

中文名称：正式事实 / 标准数据  
所属阶段：项目、原文和证据  
优先级：P0  
精确定义：Canonical Data 表示通过 Schema 验证、证据检查、合并、冲突处理和提交后被系统承认的正式数据。它是后续状态编译、分镜和 QA 的可信来源。通知类最终有效事实必须来自最新有效 Revision，并保留覆盖或确认该字段的 EvidenceRef。嵌入故事、童话、寓言、剧本或角色讲述中的内容，除非原文明示进入主线现实，否则不得提交为 PRIMARY 主线 Canonical Data。
识别规则：只有 CommitService 可以把合格结果提交为 Canonical Data。旧通知、旧海报或旧视觉资产中的过期字段不得覆盖最终 Canonical Data，只能作为历史 Revision、STALE 证据或对比材料。story-within-story 的 Event、Entity 或 ObjectState 应绑定非 PRIMARY RealityLayer 或候选层，不得与主线实体库静默合并。
正例：正式确认“林晓在十年后为短发并持有怀表”；校园通知最终决赛日期为更正后的日期，现场名额为补充通知后的队伍数。
反例：某 Agent 单次输出的高置信度 EventProposal 仍不是 Canonical Data。  
容易混淆：Proposal 是候选；Canonical Data 是正式事实。  
产生者：CommitService。  
读取者：StoryBible、VisualBible、PanelSpec 生成、QA、导出服务。  
是否必须包含 EvidenceRef：是，关键故事事实必须包含。  
候选Schema：EventV1、EntityV1、CharacterStateV1。  
备注或待确认问题：正式 Canonical Schema 后续单独设计。FactLock 不是新的故事事实类型，而是 Canonical Data、PanelSpec 和 QA 上的精确性约束。EmbeddedNarrativeScope 可作为后续候选说明，本轮不新增顶层 Schema。

## Confidence

中文名称：置信度  
所属阶段：项目、原文和证据  
优先级：P0  
精确定义：Confidence 表示生成者对 Proposal 正确性的数值估计，通常在 0 到 1 之间。它不能替代 EvidenceRef，也不能单独决定是否提交。  
识别规则：Agent 对实体、事件、关系、状态变化等不确定判断输出时必须提供。  
正例：`confidence=0.82` 表示共指判断较可信但仍需校验。  
反例：`confidence=1.0` 不代表无需证据。  
容易混淆：Confidence 是概率/质量信号；Approval 是人工或系统审核记录。  
产生者：Agent、QA 模型、规则评分器。  
读取者：合并服务、CommitService、QA、审核界面。  
是否必须包含 EvidenceRef：否。  
候选Schema：Proposal confidence 字段。  
备注或待确认问题：不同 Agent 的置信度校准方式需黄金集验证。  

## 第二组：故事世界

## Entity

中文名称：实体  
所属阶段：故事世界  
优先级：P0  
精确定义：Entity 表示故事世界或事实文本中可被引用、可跨片段追踪的对象总称，包括人物、地点、道具和组织。Entity 是上位概念，不能替代更具体类型。嵌入故事中的国王、巨龙、虚构地点或虚构道具可作为非 PRIMARY 层或候选层 Entity 表达，但不自动进入主线实体空间。
识别规则：原文中出现可被多次提及、参与事件或具有状态的对象时建立。若对象只存在于角色讲述的童话、寓言、剧本、小说片段或虚构故事中，应记录其叙述来源和 RealityLayer，不得与主线 Character、Location 或 StoryObject 静默合并。
正例：林晓、旧车站、怀表、学生会；童话里的国王和巨龙可作为嵌入故事 Entity 候选，但不等于主线人物。
反例：“她”这个单次代词本身不是 Canonical Entity。  
容易混淆：EntityAlias 是别名；NarrativeMention 是文本提及。  
产生者：实体抽取 Agent、实体合并服务。  
读取者：事件抽取、状态编译、PanelSpec、QA。  
是否必须包含 EvidenceRef：是。  
候选Schema：EntityProposalV1、EntityV1。  
备注或待确认问题：故事内故事实体库暂不进入 V1.9。

## Character

中文名称：人物  
所属阶段：故事世界  
优先级：P0  
精确定义：Character 是具有身份、行为、状态、知识或关系变化的人物型 Entity。人物可以是真人、虚构角色或文本中的人类群体成员。
识别规则：实体参与行为、对白、心理、关系、职务责任或视觉呈现时建立为 Character。近似姓名、同音姓名、相近职务、同姓或同单位不能单独合并为同一 Character 或 Contact。
正例：林晓、顾远；“周舟老师”和“周洲副院长”在原文明确区分时必须保持不同 Character / Contact 候选。
反例：旧车站不是 Character。  
容易混淆：Organization 是组织；CharacterVisualVariant 是人物的视觉表现版本。通知类联系人、致辞人、负责人等角色职责不同，即使姓名相近也不能自动合并。
产生者：实体抽取 Agent、实体合并服务。  
读取者：状态编译、StoryBible、VisualBible、PanelSpec、人物连续性 QA。  
是否必须包含 EvidenceRef：是。  
候选Schema：EntityProposalV1、CharacterV1。  
备注或待确认问题：群体人物是否拆分需后续规则。  

## Location

中文名称：地点  
所属阶段：故事世界  
优先级：P0  
精确定义：Location 是事件发生、人物出现或视觉场景需要呈现的空间型 Entity。Location 可以有状态，如是否破旧、是否下雨、是否拥挤。通知类文本中报到地点、开幕地点、主会场、材料提交渠道等不同业务地点/渠道必须分开。
识别规则：原文出现明确空间、场所、建筑、房间或地理位置时建立。建筑、楼层、房间和功能厅可能需要层级 Location 或 LocationState 表达，不能因同属一个校区而混为同一地点。
正例：旧车站、大学操场、图书馆；科创中心一楼大厅是报到地点，科创中心二楼多功能厅是开幕/主会场。
反例：“十年后”是时间，不是 Location。  
容易混淆：LocationState 描述地点在某个 StoryTime 的状态。报到地点与主会场不是同一位置时，PanelSpec 不得把两个业务事件画成同一地点。
产生者：实体抽取 Agent、场景切分服务。  
读取者：Scene、PanelSpec、VisualAsset 检索、QA。  
是否必须包含 EvidenceRef：是。  
候选Schema：EntityProposalV1、LocationV1。  
备注或待确认问题：真实校园地点隐私策略需团队确认。  

## StoryObject

中文名称：剧情道具  
所属阶段：故事世界  
优先级：P0  
精确定义：StoryObject 是对剧情、状态或视觉连续性有意义的物件型 Entity。普通背景杂物只有影响剧情或被视觉约束引用时才升级为 StoryObject。相似外观、相同颜色、角色确信或同类名称不能单独证明两个物件是同一 StoryObject。
识别规则：物件被持有、转移、损坏、寻找、作为线索或必须出现在画面中时建立。跨 RealityLayer 或跨时间的相似物体只能建立 candidate_link、Claim 或 UNCERTAIN object_identity，直到有证据确认合并。
正例：父亲留下的怀表、蓝色雨伞、折过的地图；梦中的红钥匙、童年红色塑料钥匙挂件和现实红色金属钥匙默认是三个候选对象或候选关联，不自动合并。
反例：背景里未被原文提及的一把椅子不是 StoryObject。  
容易混淆：ObjectState 描述道具状态；VisualAsset 是道具图像资产。  
产生者：实体抽取 Agent、状态变化 Agent。  
读取者：事件抽取、状态编译、PanelSpec、道具连续性 QA。  
是否必须包含 EvidenceRef：是。  
候选Schema：EntityProposalV1、StoryObjectV1。  
备注或待确认问题：无。  

## Organization

中文名称：组织
所属阶段：故事世界
优先级：P0
精确定义：Organization 是具有相对稳定身份、边界、名称或职能的组织型 Entity，包括学校、社团、公司、部门、家庭、论坛管理组等。它可参与事件、发布通知、拥有账号或与人物存在成员关系。
识别规则：原文出现明确组织名称、机构身份、发布主体、成员关系或可复用集体身份时建立。临时的“他们”“那些人”“几个人”只有在证据支持其稳定组织身份时才能升级为 Organization。
正例：学生会、教务处、顾远所在社团。
反例：一群临时路人，或身份未解析的“他们”，如果没有组织身份证据，不是 Organization。
容易混淆：Character 是个体人物；UnresolvedGroupReference 是未解析群体指代；EntityRelation 可表达人物属于组织。
产生者：实体抽取 Agent、校园新闻解析器。
读取者：事件抽取、校园模式、StoryBible、QA。
是否必须包含 EvidenceRef：是。
候选Schema：EntityProposalV1、OrganizationV1。
备注或待确认问题：校园新闻机构名称审核策略需确认。

## UnresolvedGroupReference

中文名称：未解析群体指代
所属阶段：故事世界
优先级：P0
精确定义：UnresolvedGroupReference 表示原文中出现的群体性称呼尚不能确定具体成员、组织身份或稳定边界，例如“他们”“那些人”“有人不希望”。它保留群体指代本身和候选解释，但不强制合并为 Organization 或多个 Character。
识别规则：当文本使用复数代词、模糊群体称呼或匿名集体行动主体，且证据不足以确定成员列表或组织身份时建立。
正例：角色说“他们不希望你知道真相”，但未说明“他们”是谁。
反例：原文明确写“学生会成员三人共同决定”，应建立 Organization 或多个 Character 及关系，而不是 UnresolvedGroupReference。
容易混淆：Organization 需要稳定组织身份；UnresolvedReference 可以是单人或单物指代，UnresolvedGroupReference 专指群体。
产生者：共指消解 Agent、关系抽取 Agent、知识状态 Agent。
读取者：StoryBible、Claim 合并、QA、审核界面。
是否必须包含 EvidenceRef：是。
候选Schema：UnresolvedGroupReferenceV1、EntityProposalV1。
备注或待确认问题：后续可增加 candidate_member_ids 和 group_resolution_status 字段。

## EntityAlias

中文名称：实体别名
所属阶段：故事世界
优先级：P0
精确定义：EntityAlias 表示同一 Entity 的稳定可复用名称映射，包括本名、昵称、职务称呼、常用简称、笔名或被证据确认的账号名。EntityAlias 不包括一次性代词提及，且别名本身不等于新实体。
识别规则：多个称呼被证据支持为同一对象时建立，必须记录 alias_status，建议值为 CONFIRMED、PROPOSED、REJECTED。相似读音、相同首字母、同名或同款物品不能单独构成 EntityAlias。
正例：“林乔”“乔姐”“林助教”被原文明确指向同一人时，可作为林乔的 EntityAlias。
反例：“她”是 EntityMention，不是稳定 EntityAlias；“林乔”和“乔临”不能因读音相近合并为别名。
容易混淆：EntityMention 是原文中的一次出现；EntityAlias 是可复用的名称映射。
产生者：实体抽取 Agent、共指消解 Agent、实体合并服务。
读取者：事件抽取、搜索、审核界面。
是否必须包含 EvidenceRef：是。
候选Schema：EntityAliasV1、EntityProposalV1.aliases。
备注或待确认问题：别名置信度阈值需通过黄金集校准。

## EntityMention

中文名称：实体文本提及
所属阶段：故事世界
优先级：P0
精确定义：EntityMention 表示 SourceChunk 中对某个 Entity、Account、Organization、StoryObject 或未知对象的一次文本出现，包括专名、昵称、代词、职务称呼、账号名、签名、缩写、联系方式标签和模糊称呼。它是文本层对象，不自动表示稳定别名或正式实体。
识别规则：只要原文出现可被指向某个对象的词语、短语或代词，就可建立 EntityMention，并记录 mention_text、source_chunk_id、candidate_entity_ids、resolution_status。近似姓名或职务相近时，应先保留独立 EntityMention，再由证据决定是否可合并。
正例：“她”“小林”“灰桥”“Q”“北岸”都可以是 EntityMention；“周舟老师”和“周洲副院长”是两个不同 EntityMention。
反例：已经审核确认的人物“林乔”是 Character；它在某段中的一次出现才是 EntityMention。
容易混淆：EntityAlias 跨片段复用；EntityMention 只代表一次文本位置。NarrativeMention 更偏事件或叙述内容，EntityMention 专注实体指代。
产生者：文档解析器、共指消解 Agent、实体抽取 Agent。
读取者：实体合并服务、Claim 抽取、KnowledgeState、QA。
是否必须包含 EvidenceRef：是。
候选Schema：EntityMentionV1。
备注或待确认问题：mention 类型枚举可后续细化为 NAME、PRONOUN、TITLE、ACCOUNT_HANDLE、SIGNATURE、GROUP_PRONOUN。

## UnresolvedReference

中文名称：未解析指代
所属阶段：故事世界
优先级：P0
精确定义：UnresolvedReference 表示一个 EntityMention 暂时无法被唯一绑定到 Character、Account、Organization、StoryObject 或 Location。它保留候选对象、排除对象和证据边界，防止系统为了完成结构化而强行合并。
识别规则：当候选超过一个、证据不足、叙述视角受限、角色说法互相冲突、共享账号、账号名线索或同名/近音/同首字母导致歧义时建立。
正例：“小林”在两名姓林或近音人物同时回应时，应保持 UnresolvedReference；共享账号“白栖”的第二条消息作者未知时，作者可保持 UnresolvedReference；“他答应过会把阿岑带回来”中的“他”候选不唯一时不得强行绑定；账号名 “Q-Zhou” 不能单独解析为某个姓 Zhou 的 Character。
反例：原文明确写“林助教，你跟我来”且上下文唯一指向林乔时，不需要保持未解析。
容易混淆：UNKNOWN 表示无法得知结果；UNCERTAIN 表示有候选但证据不足；UnresolvedReference 是记录这种状态的结构。
产生者：共指消解 Agent、实体合并服务。
读取者：事件抽取、Claim 合并、QA、审核界面。
是否必须包含 EvidenceRef：是。
候选Schema：UnresolvedReferenceV1、EntityMentionV1.resolution。
备注或待确认问题：后续需定义人工解除 unresolved 的审核流程。

## EntityRelation

中文名称：实体关系  
所属阶段：故事世界  
优先级：P0  
精确定义：EntityRelation 表示两个 Entity 之间在某个 StoryTime 或区间内成立的关系，如亲属、同学、持有、隶属、敌对。关系可随时间变化。  
识别规则：原文明确描述关系、称谓、归属或互动关系时建立。  
正例：怀表属于林晓；林晓和顾远是大学同学。  
反例：同一段出现两个人名不自动构成关系。  
容易混淆：RelationshipState 是人物关系在时间区间内的有效状态。  
产生者：关系抽取 Agent、状态编译器。  
读取者：StoryBible、PanelSpec、QA。  
是否必须包含 EvidenceRef：是。  
候选Schema：EntityRelationProposalV1、EntityRelationV1。  
备注或待确认问题：关系类型枚举需后续收敛。  

## Account

中文名称：账号
所属阶段：故事世界
优先级：P0
精确定义：Account 表示在论坛、邮件、社交平台、系统或设备中可登录、发帖、发送消息或署名的数字身份。Account 是故事世界 Entity，但不等同于 Character；共享账号、账号操作者、账号知情者和具体消息作者必须分开记录。
识别规则：原文出现用户名、邮箱账号、论坛账号、设备登录名、署名身份或账号操作证据时建立。
正例：校园论坛账号“灰桥”、邮件账号“北岸”；校园账号“白栖”；被铭文说明为一组共享账号的 “Q”。
反例：人物乔临不是 Account；“灰桥”作为照片背面署名若无账号证据，只是 EntityMention 或 AuthorshipClaim 的署名线索。
容易混淆：Character 是人物；Account 是数字身份；EntityAlias 只有在证据确认账号名稳定指向某实体时才建立。账号名、共享密码知情者或主要使用者都不能单独证明具体 Message 作者。
产生者：实体抽取 Agent、账号解析 Agent。
读取者：AuthorshipClaim、AccountAccessRelation、Message、StoryBible、QA。
是否必须包含 EvidenceRef：是。
候选Schema：AccountV1、EntityProposalV1。
备注或待确认问题：Account 与真实平台隐私策略需后续确认。

## Message

中文名称：消息
所属阶段：故事世界
优先级：P0
精确定义：Message 表示由某个可见来源发布、发送、张贴或留下的一段信息载体，包括邮件、论坛帖、短信、便签、照片背面文字、公告、定时消息等。Message 记录内容、渠道、发布时间、可见发送方和 EvidenceRef，但不自动确认真实作者。
识别规则：原文出现可被引用的信息文本、发布行为或载体时建立。
正例：论坛账号“灰桥”发布的新消息；账号“北岸”发来的邮件；照片背面的“不要相信Q”；“白栖”在 23:06 以后发送的定时消息。
反例：角色口头说出一句话通常是 DialogueUnit，不是 Message，除非它以可保存的信息载体存在。
容易混淆：Message 是信息载体；Claim 是消息中表达的主张；AuthorshipClaim 判断谁发了这条 Message。Message 的 visible_sender 只说明显示来源，不排除预设、共享账号或冒用。
产生者：消息抽取 Agent、事件抽取 Agent。
读取者：Claim 抽取、AuthorshipClaim、KnowledgeState、QA。
是否必须包含 EvidenceRef：是。
候选Schema：MessageV1、MessageProposalV1。
备注或待确认问题：消息渠道枚举需后续补充。

## AccountAccessRelation

中文名称：账号访问关系
所属阶段：故事世界
优先级：P0
精确定义：AccountAccessRelation 表示 Character、Organization 或其他主体与 Account 之间的访问、运营、知晓密码、共享登录、被盗用或被冒用关系。它只说明访问能力或管理关系，不说明某条 Message 的真实作者。
识别规则：原文出现登录、经营账号、知道密码、交出密码、借用账号、否认登录或账号被他人使用等证据时建立。
正例：乔临被确认经营论坛账号“灰桥”；林乔曾知道该账号密码；周璐是“白栖”的主要使用者；社团成员共享过同一账号密码。
反例：某条消息署名“灰桥”不能单独证明乔临写了这条消息。
容易混淆：AccountAccessRelation 是账号访问能力；AuthorshipClaim 是具体消息作者判断。
产生者：账号解析 Agent、关系抽取 Agent。
读取者：AuthorshipClaim、StoryBible、QA、审核界面。
是否必须包含 EvidenceRef：是。
候选Schema：AccountAccessRelationV1。
备注或待确认问题：关系类型建议包括 PRIMARY_OPERATOR、KNOWN_PASSWORD、SHARED_ACCESS、SUSPECTED_ACCESS、DENIED_ACCESS、COMPROMISED。

## AuthorshipClaim

中文名称：作者身份主张
所属阶段：故事世界
优先级：P0
精确定义：AuthorshipClaim 表示关于某条 Message、照片、帖子、邮件或署名文本真实作者/发送者/发布者的结构化主张。它可引用 Account、Character、Organization 或 UnresolvedReference，并必须保留验证状态、候选作者范围和冲突来源。
识别规则：原文直接陈述、否认、暗示、质疑或留下署名线索时建立。账号可见发送方、实际登录者和真实作者不一致时，必须用 AuthorshipClaim 表达，而不能改写 Account 或 Character 身份。
正例：“乔临否认发送第一张照片”是一条 DENIAL 类型 AuthorshipClaim；“论坛账号灰桥发新消息”只确认可见发布账号，不确认键盘前是谁；“周璐否认发送第二条白栖消息”是 Authorship DENIAL，不能反向证明其他人发送。
反例：账号经营关系本身不是 AuthorshipClaim。
容易混淆：Claim 是通用主张；AuthorshipClaim 是作者身份领域的专门 Claim；AccountAccessRelation 只描述账号访问关系。
产生者：Claim 抽取 Agent、账号解析 Agent、共指消解 Agent。
读取者：StoryBible、QA、审核界面、KnowledgeState。
是否必须包含 EvidenceRef：是。
候选Schema：AuthorshipClaimV1、ClaimV1。
备注或待确认问题：后续可抽象为 Claim 的 subtype。shared_account、candidate_author_ids、excluded_author_ids、scheduled_or_presumed_send 等字段可作为 Schema 候选。

## Claim

中文名称：主张
所属阶段：故事世界
优先级：P0
精确定义：Claim 表示文本、角色、消息、设备日志标签或叙述者提出的一条可被验证或暂时保留的陈述。Claim 不等于 Event，也不等于 Canonical Data；它记录“谁在何处声称了什么”，并通过 verification_status 表示证据状态。
识别规则：原文出现断言、否认、指控、猜测、暗示、调查推论、记忆、解释、预测、消息内容、系统标签、实验记录、Agent 推理或角色草稿改写时建立。任何未被独立证实的角色说法、匿名消息、署名线索、系统日志标签和推理结论都应先作为 Claim、Proposal 或 Evidence 线索。
正例：“灰桥不是发照片的人”是一条 Claim；“我没有贴那张照片”是一条 DENIAL Claim；“林祁说程放拿卡”是 ACCUSATION Claim，不是“程放拿卡”这个 Canonical Event；角色说“我在未来见过它”是 Claim/KnowledgeState，不是对象身份 Canonical 证明；研究员说“也许读取到未来记忆”是 HYPOTHESIS Claim，不是 FLASH_FORWARD Event；周璐说“我看见顾舟捡起钥匙”是 MEMORY/ASSERTION Claim，若后续自述冲突则保持 Claim 冲突；顾舟记得沈岑说过某句话，先作为 Gu POV 的 MEMORY Claim，不能直接升级为 Canonical DialogueUnit。
反例：“唐宁收到邮件”是 Event；邮件中说“你问错了人”是 Claim。
容易混淆：Event 是故事世界中发生的事；Claim 是关于事实的说法。Character Belief 可由 Claim 影响，但 Claim 本身不是 KnowledgeState。没有可验证内容的暗示不能生成 Canonical 因果链。
产生者：Claim 抽取 Agent、消息抽取 Agent、叙事结构 Agent。
读取者：CommitService、KnowledgeState、QA、审核界面。
是否必须包含 EvidenceRef：是。
候选Schema：ClaimV1、AuthorshipClaimV1。
枚举约束：claim_type 必须使用 ASSERTION、DENIAL、ACCUSATION、HYPOTHESIS、MEMORY、INTERPRETATION、PREDICTION。verification_status 必须使用 UNVERIFIED、SUPPORTED、CONFIRMED、CONTRADICTED、PARTIALLY_SUPPORTED、UNRESOLVED。
备注或待确认问题：Claim 合并和互斥判断策略需后续设计。

## ExpressedStance

中文名称：表达态度
所属阶段：故事世界
优先级：P0
精确定义：ExpressedStance 表示 Character 通过对白、动作或书面文本表达出的态度、立场、承诺、拒绝、道歉或原谅声明。它可作为 Claim 的子类或关联对象，记录“角色表达了什么”，但不自动证明真实内心、长期信任或 Canonical RelationshipState 全维度变化。
识别规则：原文出现“我原谅你”“我不原谅你”“不是你的错”“以后别再联系了”等态度性表达时建立，并绑定 DialogueUnit、speaker_id、target_id、stance_type、EvidenceRef 和 verification_status。
正例：“我可以和你把这场演完，但这不等于我原谅你”表达了愿意临时合作和拒绝原谅两项态度。
反例：角色完成默契动作不是 ExpressedStance，而是可观察 Event；它只能作为 InteractionState 证据。
容易混淆：DialogueUnit 是原文对白单元；Claim 是可验证主张；ExpressedStance 是角色表达出的关系态度，不能直接等同 Internal State。
产生者：对话抽取 Agent、关系抽取 Agent。
读取者：RelationshipState、KnowledgeState、PanelSpec、QA。
是否必须包含 EvidenceRef：是。
候选Schema：ClaimV1、DialogueUnitV1、RelationshipStateV1.expressed_stances。
备注或待确认问题：stance_type 枚举暂不扩展为完整情感本体。

## Event

中文名称：标准事件  
所属阶段：故事世界  
优先级：P0  
精确定义：Event 表示故事世界中实际发生的一次标准事件，与它在原文中被叙述、回忆或转述多少次无关。Event 必须带 RealityLayer，梦境内部 Event 不能默认成为现实主线 Event。参与者未知但结果由原文确认时，可以建立 actor=UNKNOWN 或 actor_ref=UnresolvedReference 的 Event 候选。嵌入故事中的事件可作为非 PRIMARY 可视化或叙述对象，但不自动成为主线 Canonical Event。
识别规则：当文本表达一次行动、变化、信息揭示、决定或关系变化，并可定位到证据时建立候选 Event。同一历史夜晚可根据粒度建立事件簇，事件簇内包含受伤、交付、离开、失踪等多个 Event；多个记录、录像、录音、回忆或角色说法回指同一历史事件时，不得重复制造多个 Canonical Event。角色讲述的童话、寓言、剧本或小说片段，应优先作为 DialogueUnit、NarrationUnit、Claim、NarrativeMention 或非 PRIMARY Scene 的来源处理。
正例：林晓剪去长发；林晓回到旧车站；大学时期第一次见到顾远；某物被未知人物放回原处；门禁记录确认沈岑 22:13 刷卡进入地下档案室，录像确认他 23:06 独自离开泵房，但二者都不确认最终去向。
反例：“她想起那天下午”是 NarrativeMention 或触发回忆的 Event，不能直接等同于被回忆事件本身；童话里“国王被巨龙带走”不是 PRIMARY 主线 Event。
容易混淆：NarrativeMention 是对 Event 的一次叙述；StateChange 是 Event 导致的属性变化。  
产生者：事件抽取 Agent、事件去重服务。  
读取者：TemporalRelation Agent、状态编译器、Scene、StoryBible、QA。  
是否必须包含 EvidenceRef：是。  
候选Schema：EventProposalV1、EventV1。  
备注或待确认问题：事件粒度和事件簇边界需通过黄金样例校准。本轮不新增 EventCluster 顶层 Schema。

## NarrativeMention

中文名称：事件的一次叙述  
所属阶段：故事世界  
优先级：P0  
精确定义：NarrativeMention 表示原文对某个 Event、EventCluster、Entity 或状态的一次描述、回忆、转述、暗示或提及。它属于文本表达层，不自动成为故事世界事实。
识别规则：当一个 SourceChunk 中出现事件描述、回忆句、传闻、梦境描述、记录、录像、录音、设备材料或代词提及时建立。同一历史夜晚被病历、回忆、客观叙述、角色讲述、档案记录、监控片段或自动播放录音多次提及时，应建立多个 NarrativeMention、Claim 或相关 Event，并回指同一 Event 或事件簇。
正例：`她想起大学时期第一次见到顾远的下午` 是对过去事件的一次 NarrativeMention；病历提到某夜受伤、角色讲述同一夜晚、客观叙述同一夜晚行动，都是不同 NarrativeMention 或 Claim；巡逻表、旧录像、录音和角色记忆共同提到失踪夜时，优先回指同一历史夜晚而非复制事件。
反例：正式去重后的“第一次见到顾远” Event 不是 NarrativeMention。  
容易混淆：Event 是故事世界事实；NarrativeMention 是文本叙述。  
产生者：叙事结构 Agent、事件抽取 Agent。  
读取者：TemporalRelation Agent、RealityLayer Agent、QA。  
是否必须包含 EvidenceRef：是。  
候选Schema：NarrativeMentionV1。  
备注或待确认问题：EventCluster 可作为事件组织粒度使用，本轮不新增顶层持久 Schema。

## CausalRelation

中文名称：因果关系  
所属阶段：故事世界  
优先级：P0  
精确定义：CausalRelation 表示一个 Event、StateChange 或信息揭示对另一个事件产生原因、动机、结果或触发作用。它不能仅凭文本相邻、时间先后、视觉暗示或相隔很短时间强行建立。
识别规则：原文出现“因为、导致、于是、为了、使得”等因果线索，或上下文明确支持时建立。TemporalRelation BEFORE 只能证明先后，不能单独支持 CausalRelation。
正例：钟声响起触发林晓想起顾远。  
反例：两件事连续出现、相隔八分钟或在画面上被并置，但没有因果证据，不是 CausalRelation。
容易混淆：TemporalRelation 表示时间先后，不等于因果。  
产生者：因果关系 Agent、故事编译服务。  
读取者：StoryBible、QA、修复规划。  
是否必须包含 EvidenceRef：是。  
候选Schema：CausalRelationProposalV1、CausalRelationV1。  
备注或待确认问题：无。  

## NarrativePerspective

中文名称：叙事视角
所属阶段：故事世界
优先级：P0
精确定义：NarrativePerspective 表示某段文本从谁的感知、回忆、想象、转述、讲述或叙述位置呈现。它决定信息可见性、可靠性和角色是否可据此更新 KnowledgeState，但不自动改变 Canonical Data。
识别规则：文本出现第一人称、角色心理、回忆触发、观察限制、传闻来源、草稿改写、匿名消息、读者可见但角色不可见的信息、角色讲故事或视角切换时建立，并记录 perspective_type、focal_entity_id、visible_to_character_ids、visible_to_reader、reliability_status。
正例：唐宁听见身后有人说话时，该信息首先进入唐宁受限视角；林晓“想起”大学下午，视角来源是林晓记忆；客观叙述让读者看见黑手套拿走门禁卡时，可记录 visible_to_reader=true 且 visible_to_character_ids 为空；顾舟视角让读者知道他保存巡逻表副本，但沈雾和周璐的 KnowledgeState 不因此更新；作家给孩子讲“月亮王国”童话时，讲述者视角应作为嵌入叙事来源。
反例：全知旁白直接陈述事实不一定绑定具体人物视角。
容易混淆：RealityLayer 是现实层级；NarrativePerspective 是叙述来源；KnowledgeState 是某个角色在某个 StoryTime 的认知内容。
产生者：叙事层识别 Agent。
读取者：事件抽取、TemporalRelation、QA、StoryBible。
是否必须包含 EvidenceRef：是。
候选Schema：NarrativePerspectiveV1。
字段建议：visible_to_reader、visible_to_character_ids、source_perspective_id、reliability_reason。读者可见信息可进入 StoryBible 或 Canonical Data，但 visible_to_character_ids 为空时，不进入人物 KnowledgeState；本轮不新增 ReaderKnowledge 或 ReaderVisibleFact 顶层概念。
枚举约束：perspective_type 建议使用 OMNISCIENT、EXTERNAL_OBSERVER、CHARACTER_LIMITED、FIRST_PERSON、UNKNOWN。reliability_status 建议使用 RELIABLE、LIMITED、UNRELIABLE、UNKNOWN。
备注或待确认问题：多视角同段落和 story-within-story 的切分策略需后续黄金集校准；EmbeddedNarrativeScope 只作为候选说明，不进入 V1.9 Schema。

## 第三组：时间、叙事层和状态

## StoryTime

中文名称：故事时间  
所属阶段：时间、叙事层和状态  
优先级：P0  
精确定义：StoryTime 表示事件在故事世界中真实发生的时间位置，可以是 absolute_datetime、date_only、time_point、time_interval、relative_time、fuzzy_time 或 UNKNOWN。它不强制推断精确日期。
识别规则：当 Event、Scene、CharacterState、ObjectState 或 PanelSpec 需要按故事时间排序或查询状态时建立。相对时间必须记录 precision、anchor_event、anchor_story_time、candidate_anchors 和 resolution_status；锚点不足时保留多个候选或 UNKNOWN。
正例：“大学时期第一次见面”早于“十年后回到旧车站”；“三天前”可解析到某个叙述锚点前 3 天；“前一天”在锚点不明时保留候选。
反例：文本中先写“十年后”不代表它在 StoryTime 中最早发生。  
容易混淆：NarrativeOrder 是文本出现顺序；StoryTime 是故事发生顺序。  
产生者：TemporalRelation Agent、时间求解器。  
读取者：状态编译器、PanelSpec、QA。  
是否必须包含 EvidenceRef：视情况而定；由原文直接给出的时间需要证据。  
候选Schema：StoryTimeRefV1、TemporalRelationProposalV1。  
字段建议：time_kind、absolute_datetime、date_only、time_point、time_interval、relative_time、fuzzy_time、precision、anchor_event、anchor_story_time、candidate_anchors、resolution_status、evidence_refs。
备注或待确认问题：时间表达字段本轮只作领域语义说明，暂不实现 Schema。

## TemporalRelation

中文名称：时间关系  
所属阶段：时间、叙事层和状态  
优先级：P0  
精确定义：TemporalRelation 表示两个 Event、Scene 或状态区间之间的时间关系，如 BEFORE、AFTER、DURING、OVERLAPS、SIMULTANEOUS、UNKNOWN。SIMULTANEOUS 表示两个事件或状态在同一明确时间点、同一叙述锚点或同一同步声明下发生；OVERLAPS 表示两个时间区间存在交集，但起止不完全相同，或只能确认区间重叠。
识别规则：原文或推理规则能支持两个对象的先后、包含、同时或重叠关系时建立。时间区间覆盖某个时间点时，不要强行改成完全同时；可用 AT_TIME 或 SAME_ANCHOR 作为派生说明，不必新增正式枚举。
正例：大学见顾远 BEFORE 十年后回旧车站；“同一时刻”支持 SIMULTANEOUS；20:58-21:12 的监控区间与 21:00 事件支持 OVERLAPS 或 AT_TIME 覆盖。
反例：因果关系不自动等于 TemporalRelation，虽然常有关联。  
容易混淆：CausalRelation 表示原因结果；TemporalRelation 表示时间位置。  
产生者：时间关系 Agent、时间求解器。  
读取者：状态编译器、Scene、QA。  
是否必须包含 EvidenceRef：是；UNKNOWN 可无明确证据但需记录原因。  
候选Schema：TemporalRelationProposalV1。  
备注或待确认问题：无。  

## RealityLayer

中文名称：叙事现实层  
所属阶段：时间、叙事层和状态  
优先级：P0  
精确定义：RealityLayer 表示事实或画面属于现实主线、回忆、梦境、想象、假设、未来片段、不可靠记忆或嵌入叙事等哪一层。不同 RealityLayer 的状态不能默认互相继承。`PRIMARY` 是现实主线的标准命名；`MAIN_REALITY` 仅作为旧称或解释性同义词，不作为新增层级。
识别规则：文本出现回忆、梦、想象、假设、预言、插叙、设备重放、系统预测模拟、角色讲述的童话/寓言/剧本/小说片段或现实主线切换时标记。画面内容、角色说法、系统日志标签和 Canonical Data 必须分层处理，不能互相替代。
判定矩阵：
- `PRIMARY`：现实主线中实际发生或被可靠证据确认的事件/状态。
- `DREAM`：角色睡眠、惊醒、梦境语境明确，且无独立证据确认其为现实。
- `IMAGINATION`：角色主动构造或想象的场景。
- `HYPOTHETICAL`：假设、推演、预测模拟、可能性画面；不进入已发生 StoryTime。
- `FLASHBACK`：可靠回忆或明确过去事件的叙述。
- `UNRELIABLE_MEMORY`：来源是记忆或设备重放，但存在污染、冲突、否认证据或可靠性不足。
- `FLASH_FORWARD`：只有当文本明确给出未来真实片段，且不是预测、想象、梦或模拟时才使用。
- `UNKNOWN`：多个层级候选都合理，且证据不足以选择。
正例：大学时期第一次见面在 FLASHBACK；十年后旧车站在 PRIMARY；梦中兄长把铜钥匙交给周璐是 DREAM 内事件，不改变 PRIMARY ObjectState；设备日志标为“预测模拟”的未来画面可用 `reality_layer=HYPOTHETICAL`、`source_medium=DEVICE_LOG`、`source_label=预测模拟`、`verification_status=UNVERIFIED` 表达；2031 春的短未来片段若文本未确认是真实未来、想象或章节预告，应使用 `UNKNOWN` 并保留 `candidate_layers=[FLASH_FORWARD, HYPOTHETICAL, IMAGINATION]`；角色讲童话时，童话画面可用 IMAGINATION、HYPOTHETICAL 或 UNKNOWN/candidate_layers 表达，不进入 PRIMARY。
反例：把梦里的受伤直接写入 PRIMARY CharacterState。  
容易混淆：NarrativePerspective 是叙述来源；RealityLayer 是事实所在层级。  
产生者：叙事层识别 Agent、Scene 切分服务。  
读取者：状态编译器、PanelSpec、QA。  
是否必须包含 EvidenceRef：是。  
候选Schema：RealityLayer enum、SceneSpecV1.reality_layer。  
字段建议：reality_layer、candidate_layers、source_medium、source_label、verification_status、reliability_reason、evidence_refs。
备注或待确认问题：`UNRELIABLE_MEMORY` 与 `FLASH_FORWARD` 在 V1 文档语义中可作为合法 RealityLayer 标签使用；若当前 Schema 尚未支持，后续由 Schema 映射或兼容层处理。本轮不新增正式 `SIMULATION`、`AUTHOR_FORESHADOW` 或 `FICTIONAL_STORY` 层级。

## StateChange

中文名称：状态变化  
所属阶段：时间、叙事层和状态  
优先级：P0  
精确定义：StateChange 表示某个 Entity 的某个属性因 Event 在某个 StoryTime 发生一次变化。它是变化记录，不是完整状态快照。  
识别规则：原文明确或强支持发型、年龄阶段、伤势、持有物、知识、关系、地点状态变化时建立。  
正例：林晓剪去长发导致 `appearance.hair` 从长发变短发。  
反例：林晓在十年后完整外观不是 StateChange，而是 CharacterState。  
容易混淆：CharacterState 是状态编译结果；StateChange 是输入变化。  
产生者：状态变化 Agent。  
读取者：状态编译器、StoryBible、QA。  
是否必须包含 EvidenceRef：是。  
候选Schema：StateChangeProposalV1。  
备注或待确认问题：属性路径命名需统一。  

## CharacterState

中文名称：人物状态  
所属阶段：时间、叙事层和状态  
优先级：P0  
精确定义：CharacterState 表示某个 Character 在指定 StoryTime 区间和 RealityLayer 下完整有效的故事事实状态，包括外貌、身体、伤势引用、临时服装、持有物、知识和关系引用。
识别规则：状态编译器根据 Event、TemporalRelation 和 StateChange 计算状态查询结果时建立。  
正例：十年后林晓为成年、短发、持有怀表；2030 的沈雾为短发、有眉疤、穿临时安全背心，2023 回忆中的沈雾为长发、校服、无 2030 安全背心，DREAM 中的无眉疤状态不得污染 PRIMARY。
反例：某张图里的短发造型资产不是 CharacterState。  
容易混淆：CharacterVisualVariant 是稳定可复用视觉版本；CharacterState 是故事事实；临时礼服、绷带和当场佩戴道具通常属于 CharacterState 或 PanelSpec 的临时视觉状态。
产生者：状态编译器。  
读取者：VisualBible、PanelSpec、人物连续性 QA。  
是否必须包含 EvidenceRef：是，来源来自其 StateChange。  
候选Schema：CharacterStateV1。  
备注或待确认问题：完整状态快照字段需迭代。临时装备、伤势和外貌状态必须绑定 StoryTime 与 RealityLayer，并在证据支持的结束点停止延续。

## InjuryState

中文名称：伤势状态
所属阶段：时间、叙事层和状态
优先级：P0
精确定义：InjuryState 表示某个 Character 身体某一部位在指定 StoryTime 区间内的受伤、处理、恢复和后遗视觉状态。它是 CharacterState 的伤势子结构或关联状态，不是复杂医学诊断本体。
识别规则：原文出现受伤、流血、包扎、缝针、医嘱、恢复、拆线、伤口愈合、疤痕或功能限制时建立或更新。必须记录 body_part、injury_type、phase、visible_markers、functional_limitations、treatment、effective_from、effective_until 和 evidence_refs。
正例：左手被木板划伤为 ACUTE；手帕简单包扎为 FIRST_AID；医务室缝三针为 MEDICALLY_TREATED；拆线时伤口愈合但留浅疤为 HEALED_WITH_MARK。
反例：角色戴手套不是 InjuryState，除非手套是治疗或遮盖伤势的证据。
容易混淆：Event 记录“被划伤”“缝针”“拆线”等发生事项；InjuryState 记录这些事项之后伤势在时间区间内的有效阶段和视觉表现。
产生者：状态变化 Agent、状态编译器。
读取者：CharacterState、CharacterVisualVariant、PanelSpec、人物连续性 QA。
是否必须包含 EvidenceRef：是。
候选Schema：CharacterStateV1.injuries、InjuryStateV1。
枚举约束：phase 第一版建议使用 ACUTE、FIRST_AID、MEDICALLY_TREATED、RECOVERING、HEALED、HEALED_WITH_MARK、UNKNOWN。
备注或待确认问题：医学严重程度、诊断分类和康复概率暂不进入 MVP。

## KnowledgeState

中文名称：人物知识状态
所属阶段：时间、叙事层和状态
优先级：P0
精确定义：KnowledgeState 表示某个 Character 在某个 StoryTime、RealityLayer 和 NarrativePerspective 下对某个 Claim、Event、EntityRelation 或身份问题的认知状态。它防止角色提前知道未来信息，也防止把读者、叙述者或其他角色知道的内容泄漏给该角色。
识别规则：原文表达人物得知、听闻、怀疑、相信、否认、误解、隐瞒、发现、回忆、忘记或修改判断时建立，并记录 epistemic_status、knowledge_target_id、source_claim_id、evidence_refs 和 valid_story_time。读者通过全知、客观叙述或画面知道的信息，不自动进入任何 Character 的 KnowledgeState。
正例：唐宁在收到邮件后 HEARD“灰桥不是发照片的人”；唐宁在看到乔临登录后 KNOWS“乔临经营论坛账号灰桥”；她仍然 UNKNOWN 第一张照片作者；后续监控确认积水，只能确认积水事实，不能反向把周芮在监控恢复前的猜测改成 KNOWS；读者通过顾舟视角知道巡逻表副本存在时，沈雾和周璐仍为 UNAWARE；沈雾在 2030 看到录像后才 KNOWS 沈岑 23:06 仍活着离开泵房。
反例：读者知道的信息不等于角色知道；角色猜中真实事实时，历史状态仍可保持 SUSPECTS 或 BELIEVES，直到角色获得证据。
容易混淆：NarrativePerspective 是叙述角度；KnowledgeState 是角色知识内容；Canonical Data 是系统确认的事实。角色 BELIEVES 的内容可以与 Canonical Data 冲突。
产生者：知识状态 Agent、状态编译器。
读取者：剧情转译、DialogueUnit 生成、QA。
是否必须包含 EvidenceRef：是。
候选Schema：KnowledgeStateV1、CharacterStateV1.knowledge_fact_ids。
字段建议：visible_to_character_ids、source_perspective_id、valid_story_time、epistemic_status、knowledge_target_id、source_claim_id。
枚举约束：EpistemicStatus 必须使用 UNAWARE、HEARD、SUSPECTS、BELIEVES、DISBELIEVES、KNOWS。
备注或待确认问题：从 BELIEVES 升级为 KNOWS 的证据阈值需后续通过黄金集校准。

## RelationshipState

中文名称：人物关系状态  
所属阶段：时间、叙事层和状态  
优先级：P0  
精确定义：RelationshipState 表示两个 Character 在某个 StoryTime 区间内多个相互独立关系维度的有效状态集合，而不是“朋友、敌人、和解”等单一标签。第一版至少区分 StructuralRelation、InteractionState、TrustState 和 CommunicationAccess。
识别规则：原文中出现结构关系、合作/回避/冲突行为、信任或不信任证据、通讯权限变化、关系破裂、误会、道歉、拒绝原谅或共同调查时建立或更新。每个维度必须有独立 EvidenceRef；证据不足的维度保持 UNKNOWN。
正例：陆岚与陈默可同时是 structural_relation=FORMER_PARTNERS、interaction_state=COOPERATING、trust_state=DISTRUSTS 或 UNKNOWN、communication_access=REMOVED。
反例：两人同框出现不自动产生关系状态。  
容易混淆：EntityRelation 可包含组织和道具关系；RelationshipState 专注人物关系随时间变化。COOPERATING 不等于 TRUSTS，通讯录好友权限不等于真实情感关系，动作默契不等于恢复信任。
产生者：关系抽取 Agent、状态编译器。  
读取者：StoryBible、PanelSpec、QA。  
是否必须包含 EvidenceRef：是。  
候选Schema：RelationshipStateV1。  
枚举约束：StructuralRelation 推荐 STRANGERS、ACQUAINTANCES、FRIENDS、FORMER_FRIENDS、COLLEAGUES、FORMER_PARTNERS、FAMILY、UNKNOWN。InteractionState 推荐 NONE、COOPERATING、TEMPORARY_ALLIANCE、AVOIDING、CONFLICTING、NEGOTIATING、UNKNOWN。TrustState 推荐 UNKNOWN、DISTRUSTS、PARTIAL_TRUST、TRUSTS。CommunicationAccess 推荐 OPEN、RESTRICTED、BLOCKED、REMOVED、UNKNOWN。
备注或待确认问题：多人物群体关系和关系强度分值暂不进入 MVP。

## ObjectState

中文名称：道具状态  
所属阶段：时间、叙事层和状态  
优先级：P0  
精确定义：ObjectState 表示 StoryObject 在某个 StoryTime 和 RealityLayer 的权利关系、物理持有、使用、位置、完整性、可见性或功能状态。它至少区分 owner_id、holder_id、authorized_user_ids、in_use_by_id、location_id、condition、effective_from、effective_until 和 evidence_refs。已知离散状态点之间可以存在 UNKNOWN interval，不得为了连续性自动填补 holder、location 或 owner。
识别规则：物件被获得、丢失、损坏、隐藏、转交、借用、佩戴、归还、保管、授权使用、观察到位于某地或改变位置/状态时建立或更新。owner、holder 和 in_use_by 必须独立更新；最新 EvidenceRef 支持的结束态必须覆盖旧 holder、location 或 in_use_by 的延续。观察到某物在某地，可确认 observation/state，不一定确认是谁移动它，也不能自动推出偷窃、栽赃、动机或完整移动路径。
正例：陈默把胸针交给陆岚后，holder 可变为陆岚；陆岚第二幕佩戴时，in_use_by 可变为陆岚；归还苏闻后 holder 变为苏闻，但不能仅凭临时持有把 owner 改为陆岚；门禁卡从桌面消失后出现在林祁外套里，只能确认两个离散状态点，中间移动链保持 UNKNOWN；钥匙留在门锁上后，不能继续把 holder 静默延续为刚才开门的人；周璐从某时起持有铜钥匙并在 2030 交给沈雾，但 2023 停电后到取出钥匙前的完整保管链可保持 UNKNOWN；沈雾归还黄色安全背心后 holder 回到顾舟，不得继续画在沈雾身上；外套与学生证一起出现只能确认该时间点位置，不能确认死亡、持续持有或完整移动路径。
反例：画面中装饰性的未提及杯子没有 ObjectState。  
容易混淆：StoryObject 是道具实体；ObjectState 是该道具的时间状态。交给、借用、佩戴和保管都不等于拥有。
产生者：状态变化 Agent、状态编译器。  
读取者：PanelSpec、视觉资产检索、QA。  
是否必须包含 EvidenceRef：是。  
候选Schema：ObjectStateV1。  
备注或待确认问题：复杂法律所有权、多人共有权和完整物流轨迹推断暂不进入 MVP。梦境或不确定未来片段中的 ObjectState 不得覆盖 PRIMARY ObjectState。

## LocationState

中文名称：地点状态  
所属阶段：时间、叙事层和状态  
优先级：P0  
精确定义：LocationState 表示 Location 在某个 StoryTime 的环境状态，如天气、损坏程度、人群、光照、是否营业。它属于故事事实或明确视觉约束。  
识别规则：原文描述地点环境变化、时间氛围或场所状态时建立。  
正例：雨后的操场、旧车站钟声响起时。  
反例：模型为了好看添加的夕阳不是 Canonical LocationState。  
容易混淆：VisualAsset 是可复用图像资产；LocationState 是故事状态。  
产生者：地点状态 Agent、场景分析服务。  
读取者：Scene、PanelSpec、视觉 QA。  
是否必须包含 EvidenceRef：是。  
候选Schema：LocationStateV1。  
备注或待确认问题：无。  

## 第四组：场景和剧情组织

## Scene

中文名称：场景  
所属阶段：场景和剧情组织  
优先级：P0  
精确定义：Scene 表示一段在 StoryTime、Location、RealityLayer、叙事视角和主要行动目标上相对连续的剧情单元。Scene 可以包含多个 StoryBeat。RealityLayer 改变、StoryTime 跳跃或地点明显改变时通常必须切 Scene；过渡段可根据页面节奏保留一定粒度弹性。连续追逐、移动、搬运、交接等跨地点动作可拆成多个相邻 Scene，并通过 StoryBeat 序列、PanelSpec 连续动作说明或候选 continuous_action_group 保持动作连贯。
识别规则：地点明显改变、故事时间跳跃、RealityLayer 改变、视角改变或行动目标改变时切分。回忆、梦境、想象或假设插入前后必须与现实主线分 Scene；单纯换段或同地连续动作不必机械切分。跨办公室、走廊、楼梯口等不同 Location 的连续追逐，不得为了保持一个 Scene 而混淆不同地点的 LocationState。
正例：十年后的旧车站现实主线是一个 Scene；插入大学时期回忆时切为 FLASHBACK Scene，回到现实后再回到 PRIMARY Scene；林岚从办公室冲进走廊再到楼梯口追人，可拆为相邻 Scene，并用同一 continuous_action_group 或 StoryBeat 序列表示追逐连续。
反例：漫画单格不是 Scene。  
容易混淆：StoryBeat 是 Scene 内更小的叙事变化；Panel 是漫画画面单元。  
产生者：Scene 切分服务、叙事结构 Agent。  
读取者：剧情转译 Agent、PageSpec、PanelSpec、QA。  
是否必须包含 EvidenceRef：是。  
候选Schema：SceneSpecV1、SceneV1。  
备注或待确认问题：Scene 粒度与漫画页节奏需要黄金样例继续校准。continuous_action_group 只作为候选说明，不进入 V1.9 顶层 Schema。

## StoryBeat

中文名称：剧情节拍  
所属阶段：场景和剧情组织  
优先级：P0  
精确定义：StoryBeat 表示 Scene 中最小的有叙事意义的动作、信息、情绪、决策或关系变化。它是漫画转译单位，不等同于漫画格；一个 StoryBeat 可以拆成多个 Panel，多个简单 StoryBeat 也可以在不丢失事实的前提下合入一格。跨地点连续动作可由多个相邻 Scene 内的 StoryBeat 序列共同表达。
识别规则：当文本表达剧情推进、信息揭示、情绪变化、决策变化、物体转移或行动变化时建立。连续动作若包含多个关键时刻、信息揭示或状态变化，不得为了压缩页面随意合并；若动作跨地点，应保持每个 Beat 的 location_id 或所属 Scene 清楚。
正例：钟声响起触发林晓回忆大学下午；开柜、看到照片、犹豫和取走地图可作为连续 Beat 或相邻 Beat，但应拆成多个 Panel 表达关键信息；追逐从办公室到走廊再到楼梯口可用相邻 StoryBeat 串联。
反例：人物眨眼但无叙事意义时不一定建立 StoryBeat。  
容易混淆：Panel 是画面容器；StoryBeat 是叙事变化。一个连续动作若用单 Panel 表达，必须通过明确运动线、构图或因果连续性表现关键状态变化，不能让道具无因出现在新 holder 手中。
产生者：剧情转译 Agent。  
读取者：PageSpec、PanelSpec、QA。  
是否必须包含 EvidenceRef：是。  
候选Schema：StoryBeatV1。  
备注或待确认问题：Beat 粒度需在样例中继续校准。ActionSequenceV1 暂不进入 V1.9。

## DialogueUnit

中文名称：对白单元  
所属阶段：场景和剧情组织  
优先级：P0  
精确定义：DialogueUnit 表示可被漫画气泡承载的一段原文对白或经允许拆分后的对白片段。原文明示必须逐字保留、后续作为证据或剧情钩子的关键对白不得缩写、改写或移到旁白。
识别规则：原文出现直接引语、明确发言人和可定位文本时建立。相同文本若说话者、StoryTime、RealityLayer 或叙事功能不同，应建立不同 DialogueUnit，可额外记录重复、呼应或引用关系。
正例：陈野说：“先回教室。”；父亲在回忆中说“门打开以后，不要回头”和安遥在现实中说同一句话，应是两个 DialogueUnit。
反例：模型为画面新增的一句台词不是 DialogueUnit；把关键对白改写成旁白摘要不是合格 DialogueUnit。
容易混淆：NarrationUnit 是旁白；DialogueUnit 是角色发言。  
产生者：对白抽取 Agent、文本排版服务。  
读取者：PanelSpec、页面排版、文本准确性 QA。  
是否必须包含 EvidenceRef：是。  
候选Schema：DialogueUnitV1。  
备注或待确认问题：对白拆分规则需黄金集校准。  

## NarrationUnit

中文名称：旁白单元  
所属阶段：场景和剧情组织  
优先级：P0  
精确定义：NarrationUnit 表示可进入漫画旁白框或标题框的叙述性文本单元。它来自原文叙述或经过忠实压缩的媒介转译。  
识别规则：原文中非对白但需要保留为文字信息、时间提示或心理描述时建立。  
正例：“十年后”作为页面旁白。  
反例：画师临时添加的营销文案不是 NarrationUnit。  
容易混淆：DialogueUnit 是角色说话；NarrationUnit 是叙述文本。  
产生者：叙事转译 Agent、文本压缩服务。  
读取者：PanelSpec、页面排版、QA。  
是否必须包含 EvidenceRef：是。  
候选Schema：NarrationUnitV1。  
备注或待确认问题：忠实压缩尺度需评审。  

## TranslationDecision

中文名称：漫画转译决策  
所属阶段：场景和剧情组织  
优先级：P0  
精确定义：TranslationDecision 表示把原文转换为漫画表达时做出的可审计选择，如压缩心理描写、拆分对白、合并 StoryBeat 或省略非关键信息。  
识别规则：当转译结果不是逐字逐句映射，而是进行了媒介转换时记录。  
正例：把“她心里一紧”转为近景表情和旁白。  
反例：新增原文不存在的争吵不是合法 TranslationDecision。  
容易混淆：StoryBeat 是叙事单元；TranslationDecision 是如何表现它的决策记录。  
产生者：剧情转译 Agent、页面规划 Agent。  
读取者：QA、审核界面、修复规划。  
是否必须包含 EvidenceRef：是。  
候选Schema：TranslationDecisionV1。  
备注或待确认问题：无。  

## StoryBible

中文名称：故事设定总库  
所属阶段：场景和剧情组织  
优先级：P0  
精确定义：StoryBible 是 Project 中经审核的故事事实总库，包含正式实体、事件、时间关系、状态规则、人物关系和关键限制。它是视觉生产前的人工冻结点之一。  
识别规则：完成实体合并、事件去重、时间求解和状态编译后生成，并由审核记录冻结。  
正例：StoryBible 记录林晓十年后短发、持有怀表。  
反例：单次 Agent 输出的 EventProposal 集合不是 StoryBible。  
容易混淆：VisualBible 管视觉呈现；StoryBible 管故事事实。  
产生者：故事编译服务、CommitService、人工审核。  
读取者：VisualBible、PanelSpec、QA、导出服务。  
是否必须包含 EvidenceRef：是。  
候选Schema：StoryBibleV1。  
备注或待确认问题：冻结后的变更流程需团队确认。  

## 第五组：视觉与漫画生产

## VisualBible

中文名称：视觉设定总库  
所属阶段：视觉与漫画生产  
优先级：P0  
精确定义：VisualBible 是 Project 中经审核的视觉事实和资产总库，包含 StyleBible、人物视觉档案、视觉版本、地点和道具资产。它不能反向修改 StoryBible。  
识别规则：StoryBible 冻结后，根据故事事实和风格策略生成并审核冻结。  
正例：为学生时期长发林晓和成年短发林晓分别建立视觉版本。  
反例：单个模型 prompt 不是 VisualBible。  
容易混淆：StoryBible 是故事事实；VisualBible 是视觉表达。  
产生者：视觉规划 Agent、人工审核。  
读取者：PanelSpec、PromptSpec、图片生成、视觉 QA。  
是否必须包含 EvidenceRef：视情况而定；视觉事实来自故事事实时继承证据。  
候选Schema：VisualBibleV1。  
备注或待确认问题：视觉资产审核粒度需确认。  

## StyleBible

中文名称：画风规范  
所属阶段：视觉与漫画生产  
优先级：P0  
精确定义：StyleBible 表示项目级画风、线条、色彩、页面密度、气氛和排版审美约束。它是风格规则，不是故事事实。  
识别规则：项目开始或 VisualBible 生成阶段建立。  
正例：黑白校园漫画风、细线条、低饱和色彩。  
反例：林晓短发不是 StyleBible，而是 CharacterState/CharacterVisualVariant。  
容易混淆：ProjectSpec 管业务限制；StyleBible 管视觉风格。  
产生者：风格规划 Agent、人工审核。  
读取者：CharacterVisualProfile、PanelSpec、PromptSpec、视觉 QA。  
是否必须包含 EvidenceRef：否。  
候选Schema：StyleBibleV1。  
备注或待确认问题：首版黑白或彩色需团队确认。  

## CharacterVisualProfile

中文名称：人物基础视觉档案  
所属阶段：视觉与漫画生产  
优先级：P0  
精确定义：CharacterVisualProfile 表示一个 Character 的稳定视觉身份基础，如脸型、身高体态、识别特征和不可随意改变的设计原则。它不表示某个时间点的具体服装或发型状态。  
识别规则：Character 被纳入 VisualBible 时建立。  
正例：林晓的脸型、眼睛特征、整体气质。  
反例：大学时期长发校服版本不是 Profile，而是 CharacterVisualVariant。  
容易混淆：CharacterVisualVariant 是状态相关视觉版本；Profile 是稳定身份基准。  
产生者：角色视觉规划 Agent、人工审核。  
读取者：CharacterVisualVariant、PanelSpec、人物连续性 QA。  
是否必须包含 EvidenceRef：视情况而定；原文支持的特征需证据，风格补全需标记。  
候选Schema：CharacterVisualProfileV1。  
备注或待确认问题：无原文外貌时默认补全策略需确认。  

## CharacterVisualVariant

中文名称：人物视觉版本  
所属阶段：视觉与漫画生产  
优先级：P0  
精确定义：CharacterVisualVariant 表示 Character 稳定、可复用、经过审核的人物视觉身份版本，例如年龄阶段、基础脸部、体型、长期发型、持久疤痕和主要人生时期。它是视觉表现，不能反向修改故事事实。
识别规则：人物长期年龄阶段、基础脸部、体型、长期发型、持久疤痕或主要人生时期发生可复用视觉差异时建立。单场临时服装、绷带、血迹、污渍、暂时持有的道具、单场首饰和临时雨衣默认不创建新的永久 CharacterVisualVariant。回忆画面必须绑定过去 StoryTime 与对应 RealityLayer 的 CharacterState/CharacterVisualVariant，当前状态不得污染回忆。
正例：学生时期长发林晓；十年后成年短发林晓；拆线后长期保留浅疤的陆岚；五年前穿校服的年轻安遥应使用历史 CharacterVisualVariant，而不是当前防水外套状态。
反例：某一晚的银色礼服、手帕包扎、医用绷带、单场佩戴胸针不应单独创建永久 CharacterVisualVariant。
容易混淆：CharacterState 是故事事实；CharacterVisualVariant 是稳定画法和资产选择；临时视觉状态应由 CharacterState、PanelSpec 人物绑定、临时视觉 overlay 或 ResolvedCharacterAppearance 表达。原文未说明的发型、配饰或材质细节保持 UNKNOWN 或由风格补全标记，不能写回 Canonical。
产生者：角色视觉规划 Agent、VisualBible 审核。  
读取者：PanelSpec、PromptSpec、人物连续性 QA。  
是否必须包含 EvidenceRef：视情况而定；继承对应 CharacterState 证据。  
候选Schema：CharacterVisualVariantV1。  
派生概念：ResolvedCharacterAppearance 是某一 Panel 生成前，由 CharacterVisualVariant 加当前 CharacterState、ObjectState、InjuryState 和 PanelSpec 临时视觉约束动态解析得到的完整视觉状态。它是派生结果，不作为 V1.2 的 P0 持久化对象。
备注或待确认问题：反复使用且经过审核的经典服装可在后续作为 CostumeProfile 管理，本轮不新增正式顶层 Schema。

## VisualAsset

中文名称：视觉资产  
所属阶段：视觉与漫画生产  
优先级：P0  
精确定义：VisualAsset 表示可复用的图像、参考、草图、角色设定图、地点设定图或道具图。它是资产文件或引用，不等于故事事实。关键道具的颜色、材质和形状若被原文明确强调，应作为视觉资产和 PanelSpec QA 的重要约束。
识别规则：当视觉规划、生成或审核产生可复用图像资源时建立；当关键道具需要跨 Panel 保持识别时，应保留材质、颜色、轮廓或标志性特征来源。
正例：林晓学生时期设定图、旧车站背景参考图、黄铜钥匙的道具参考图。
反例：`must_show=怀表` 不是 VisualAsset。  
容易混淆：CharacterVisualVariant 选择视觉版本；VisualAsset 是实际资源。VisualAsset 错误不能反向修改 StoryObject 或 ObjectState，只能生成 QAIssue 或 RepairPlan。
产生者：视觉资产检索器、图片生成 Provider、人工上传。  
读取者：PromptSpec、PanelSpec、视觉 QA。  
是否必须包含 EvidenceRef：视情况而定。  
候选Schema：VisualAssetV1。  
备注或待确认问题：校园真人参考图政策需团队确认。  

## PageSpec

中文名称：页面规划规范  
所属阶段：视觉与漫画生产  
优先级：P0  
精确定义：PageSpec 表示一页漫画的结构规划，包括页码、阅读方向、Panel 列表、节奏、页面目标和文本空间策略。它不包含模型供应商参数。  
识别规则：页面规划 Agent 将 StoryBeat 分配到漫画页面时建立。  
正例：第 1 页包含旧车站现实 Scene 的 3 个 Panel。  
反例：模型生成的一张成品页面图片是 RenderedPage，不是 PageSpec。  
容易混淆：PanelSpec 规划单格；PageSpec 规划整页。  
产生者：页面规划 Agent。  
读取者：分镜导演 Agent、页面排版器、QA。  
是否必须包含 EvidenceRef：是，通过 StoryBeat 和 PanelSpec 继承。  
候选Schema：PageSpecV1。  
备注或待确认问题：页面阅读方向需团队确认。  

## PanelSpec

中文名称：单格分镜规范  
所属阶段：视觉与漫画生产  
优先级：P0  
精确定义：PanelSpec 表示一格漫画必须表达的故事事实、人物绑定、状态、视觉硬约束、镜头和文字排版要求。它必须与具体模型供应商和 API 参数解耦。must_show 与 must_not_show 是故事忠实度硬约束，不是审美建议；text_must_be_exact 和 FactLock 字段要求文字事实逐字或等值准确。
识别规则：分镜导演 Agent 将 StoryBeat 映射为一个或多个漫画格时建立。连续动作压缩到单格时，PanelSpec 必须明确运动线、构图因果或多时刻表达方式；原文明示“没有进入画面”“尚未出现”的人物或物体应进入 must_not_show。通知、公告、海报或报名信息出现在画面中时，应绑定最新有效 Canonical Data 和 FactLock 候选字段。跨地点连续动作的每个 PanelSpec 必须保留自己的 location_id，可额外记录 continuous_action_note 或候选 continuous_action_group。
正例：Panel 要求展示十年后短发林晓在旧车站握着怀表；钥匙交接 Panel 必须显示交接双方的手和黄铜钥匙；闯入者尚未出现时必须 must_not_show 完整闯入者；通知画面必须准确显示“11月17日 星期日”“科创中心二楼多功能厅”“最多36支队伍”等 FactLock 字段；追逐格可分别标注办公室、走廊、楼梯口并用运动方向保持连续。
反例：包含 `provider=openai`、`model_name` 或 `positive_prompt` 的对象不是合法 PanelSpec；把原文禁止出现的人物放进画面不是可接受构图。
容易混淆：PromptSpec 是给具体模型的请求；PanelSpec 是模型无关分镜合同。  
产生者：分镜导演 Agent。  
读取者：Prompt 编译器、图片生成工作流、QA。  
是否必须包含 EvidenceRef：是。  
候选Schema：PanelSpecV1。  
备注或待确认问题：PanelSpec V1 字段需与代码 Schema 后续对齐；多时刻单格表达、运动线字段和 FactLock 字段绑定暂作候选说明，不在本轮实现。

## PromptSpec

中文名称：模型提示词规范  
所属阶段：视觉与漫画生产  
优先级：P0  
精确定义：PromptSpec 表示从 PanelSpec、VisualBible 和 Provider 能力编译出的具体模型请求规范，可以包含 provider、model_name、positive_prompt、negative_prompt 和采样参数。  
识别规则：准备调用特定图片模型或编辑模型前建立。  
正例：为某图片模型生成包含镜头、角色视觉版本和负面约束的 prompt。  
反例：把 provider 参数直接写入 PanelSpec。  
容易混淆：PanelSpec 是通用故事/视觉约束；PromptSpec 是供应商请求。  
产生者：Prompt 编译器、模型路由器。  
读取者：Provider、GenerationJob、成本统计。  
是否必须包含 EvidenceRef：继承 PanelSpec。  
候选Schema：PromptSpecV1。  
备注或待确认问题：不同 Provider 的参数映射需后续实现。  

## GenerationJob

中文名称：图片生成任务  
所属阶段：视觉与漫画生产  
优先级：P0  
精确定义：GenerationJob 表示一次可追踪、可重试、可计费的图片生成或编辑任务。它记录输入 PromptSpec、目标 Panel、Provider、状态和成本。  
识别规则：工作流准备调用 Provider 生成或编辑图片时建立。  
正例：为 `panel-001` 创建一次生成任务。  
反例：PanelSpec 本身不是 GenerationJob。  
容易混淆：Provider 是适配器；GenerationJob 是一次任务记录。  
产生者：模型路由器、工作流服务。  
读取者：Provider、WorkflowRun、成本统计、QA。  
是否必须包含 EvidenceRef：继承 PanelSpec。  
候选Schema：GenerationJobV1。  
备注或待确认问题：成本字段单位需确认。  

## ImageCandidate

中文名称：图片候选  
所属阶段：视觉与漫画生产  
优先级：P0  
精确定义：ImageCandidate 表示一次 GenerationJob 返回的候选图片及其元数据、评分和来源。它尚未必然成为最终漫画格。  
识别规则：Provider 返回图片结果后建立。  
正例：同一 Panel 生成的 4 张候选图之一。  
反例：最终排版后的页面不是 ImageCandidate。  
容易混淆：RenderedPanel 是选定并排版后的漫画格；ImageCandidate 是候选。  
产生者：Provider、图片生成服务。  
读取者：视觉 QA、人工审核、页面排版器。  
是否必须包含 EvidenceRef：继承生成任务。  
候选Schema：ImageCandidateV1。  
备注或待确认问题：无。  

## RenderedPanel

中文名称：已渲染漫画格  
所属阶段：视觉与漫画生产  
优先级：P0  
精确定义：RenderedPanel 表示经过候选选择、裁切、文字预留或局部修复后准备用于页面合成的一格漫画图像。  
识别规则：ImageCandidate 通过 QA 或人工选择并绑定到 PanelSpec 后建立。  
正例：修复后正确显示学生时期长发林晓的回忆格。  
反例：未审核的候选图不是 RenderedPanel。  
容易混淆：PanelSpec 是计划；RenderedPanel 是图像结果。  
产生者：页面排版器、图片选择服务。  
读取者：RenderedPage、QA、导出服务。  
是否必须包含 EvidenceRef：继承 PanelSpec。  
候选Schema：RenderedPanelV1。  
备注或待确认问题：无。  

## RenderedPage

中文名称：已渲染漫画页  
所属阶段：视觉与漫画生产  
优先级：P0  
精确定义：RenderedPage 表示由多个 RenderedPanel、文字和页面布局合成后的最终或候选漫画页。它用于章节 QA 和导出。  
识别规则：页面排版器按照 PageSpec 合成完整页面后建立。  
正例：第 1 页现实旧车站场景成品页。  
反例：单张候选图不是 RenderedPage。  
容易混淆：PageSpec 是规划；RenderedPage 是渲染结果。  
产生者：页面排版器。  
读取者：章节 QA、全书 QA、导出服务。  
是否必须包含 EvidenceRef：继承 PageSpec。  
候选Schema：RenderedPageV1。  
备注或待确认问题：无。  

## 第六组：质检、修复和工作流

## QAResult

中文名称：质检结果  
所属阶段：质检、修复和工作流  
优先级：P0  
精确定义：QAResult 表示对某个目标对象的一次结构化质量检查结果，包括分数、硬性错误、具体问题、是否通过和评估者。  
识别规则：任一 QA Agent 或规则检查器完成检查后建立。  
正例：人物状态 QA 判定回忆格把林晓画成年短发，`passed=false`。  
反例：一句“画面不太好”不是结构化 QAResult。  
容易混淆：QAIssue 是具体问题；QAResult 是一次检查总结果。  
产生者：QA Agent、规则检查服务。  
读取者：RepairPlan Agent、审核界面、WorkflowRun。  
是否必须包含 EvidenceRef：视情况而定；故事事实类问题应引用证据。  
候选Schema：QAResultV1。  
备注或待确认问题：分数阈值需黄金集校准。  

## FactLock

中文名称：事实锁定项
所属阶段：质检、修复和工作流
优先级：P0
精确定义：FactLock 表示通知、公告、海报、分镜文字、字幕或 UI 文案中必须保持精确的关键事实字段。它不是新的故事事实类型，而是附加在 Canonical Data、PanelSpec、RenderedPanel 或 QA 上的精确性约束。
识别规则：当字段涉及日期、星期、时间、地点、联系人、电话、邮箱、人数/队伍数、金额、编号、报名规则、流程规则、奖项数量或其他不可改写事实时建立 FactLock 候选。每个 FactLock 必须指向最新有效 Canonical Data、EvidenceRef 和适用范围。
正例：报名截止 `10月25日18:00`；材料截止 `11月10日22:00`；决赛 `11月17日 星期日`；报到地点 `科创中心一楼大厅`；主会场 `科创中心二楼多功能厅`；最多 `36支队伍`；每队 `2至4名学生`；咨询电话 `0551-6360-2186`。
反例：背景板上为了画面氛围添加的无原文装饰标语不是 FactLock；FactLock 本身也不是 Event 或 Location。
容易混淆：Canonical Data 是正式事实；FactLock 是对该事实在下游文字或画面中不得改写的约束。QAIssue 描述违反 FactLock 的具体问题。
产生者：通知解析 Agent、分镜导演 Agent、人工审核或 QA 规则检查器。
读取者：PanelSpec、PromptSpec、RenderedPanel、QA、RepairPlan、审核界面。
是否必须包含 EvidenceRef：是。
候选Schema：PanelSpecV1。
备注或待确认问题：PanelSpec V1 字段需与代码 Schema 后续对齐；FactLockV1 Schema、PanelSpecV1.fact_locks、QAResultV1.fact_lock_checks、continuous_action_group 暂作候选说明，不在 V1.9 实现。

## QAIssue

中文名称：具体质检问题  
所属阶段：质检、修复和工作流  
优先级：P0  
精确定义：QAIssue 表示 QAResult 中发现的一个可定位问题，包括 issue_type、expected、observed、severity、hard_failure 和目标区域。hard_failure 表示故事事实、状态、文字或硬约束错误，不能被构图漂亮、画风统一或视觉质量高抵消。
识别规则：QA 检查发现状态、身份、文字、构图、道具属性或供应商约束问题时建立。人物状态错误、回忆和现实状态混用、关键道具缺失、关键对白错误、违反 must_not_show 通常是 hard_failure。关键道具颜色/材质被原文明确、多次强调且影响剧情功能时，通常 high severity 且 hard_failure；轻微色偏且不影响识别时可降为 medium 或 soft issue，并要求复检。上游定义错误导致 Scene、StoryBeat、PanelSpec、PromptSpec、VisualAsset、QAResult 或 RepairPlan 继续使用旧事实时，应产生 STALE 或 dependency_mismatch 类问题。FactLock 字段的日期、星期、数字单位、地点、联系人或电话错误通常属于 text_accuracy hard_failure；若只是未要求完整展示的背景信息省略，可记录 completeness issue 或 soft/medium issue。嵌入故事实体进入 PRIMARY、跨地点 Panel 混淆 location_id 或为了连续动作抹掉 LocationState，均应产生 QAIssue。
正例：`STATE_MISMATCH`，expected 学生时期长发，observed 成年短发；`MUST_NOT_SHOW_VIOLATION`，expected 闯入者不入画，observed 完整闯入者出现；`OBJECT_ATTRIBUTE_MISMATCH`，expected 黄铜钥匙，observed 银色钥匙；梦境铜钥匙转移污染现实持有链是 hard_failure；沈雾归还安全背心后后续格仍穿背心是临时装备状态延续错误；通知海报写成“11月17日 星期六”是日期/星期 FactLock 错误；把童话巨龙画入主线现实是 RealityLayer 泄漏错误。
反例：整个页面的综合分数不是 QAIssue。  
容易混淆：RepairPlan 是修复指令；QAIssue 是问题描述。  
产生者：QA Agent、规则检查器。  
读取者：RepairPlan Agent、审核界面。  
是否必须包含 EvidenceRef：视情况而定。  
候选Schema：QAIssueV1、QAResultV1.issues。  
备注或待确认问题：issue_type 完整枚举、严重性评分阈值、FactLock 检查项和自动追踪策略需后续固定，本轮只给文档语义边界。

## RepairPlan

中文名称：修复方案  
所属阶段：质检、修复和工作流  
优先级：P0  
精确定义：RepairPlan 表示对一个 QA 失败目标的有界修复指令，包括修复类型、目标区域、使用的正确状态或视觉版本、最大尝试次数和复检要求。它选择修复策略，但不实现真实图像编辑能力。
识别规则：QAResult 存在硬性错误、可修复软性问题或上游依赖变更导致下游产物过期时建立。缺少或错误的 PanelSpec 约束应先修 PanelSpec；小范围局部事实错误优先局部重绘；主体构图依赖错误对象、错误人物或多处事实错误时整格重生成；阅读顺序、气泡区域或文字区域被破坏时才重新排版。修复后必须复检对应 QAIssue。
正例：使用大学时期 CharacterVisualVariant 对人物区域局部重生成；展柜格漏掉黄铜钥匙时先补 PanelSpec must_show，再对钥匙区域局部重绘；P06 若以完整闯入者为主体构图，则整格重生成。
反例：“重新画好看点”不是合格 RepairPlan；为修复一个局部道具颜色轻微偏差直接重排整页通常不是最小修复。
容易混淆：QAIssue 描述问题；RepairPlan 描述怎么修。  
产生者：修复规划 Agent。  
读取者：图片编辑 Provider、工作流、QA。  
是否必须包含 EvidenceRef：视情况而定。  
候选Schema：RepairPlanV1。  
备注或待确认问题：自动选择最优修复策略暂不进入 MVP；本轮只要求记录重算或复检建议。

## DependencyEdge

中文名称：依赖关系  
所属阶段：质检、修复和工作流  
优先级：P0  
精确定义：DependencyEdge 表示一个数据或产物依赖另一个数据或产物，用于局部重算、缓存失效、STALE 标记和断点恢复。
识别规则：当 Scene 依赖 StoryTime/RealityLayer、StoryBeat 依赖 Event、PanelSpec 依赖 CharacterState/ObjectState/FactLock、PromptSpec 依赖 PanelSpec、VisualAsset 依赖 StoryObject/CharacterVisualVariant/FactLock、QAResult 依赖 RenderedPanel/PanelSpec、RepairPlan 依赖 QAIssue 时建立。上游事实、状态、FactLock 或分镜约束变化后，下游 Scene、StoryBeat、PanelSpec、PromptSpec、VisualAsset、QAResult 或 RepairPlan 应标记为 STALE 或进入重算队列。
正例：`panel-1 -> character-state-linxia-student`；铜钥匙 holder 从 Zhou 更新为 Shen 后，依赖旧 holder 的 PanelSpec、PromptSpec、RenderedPanel、QAResult 和 RepairPlan 应标记 STALE；旧海报中“11月16日、创新楼、30强现场赛”作废后，引用这些字段的海报资产和 QAResult 应标记 STALE。
反例：团队任务分配不是 DependencyEdge。  
容易混淆：TemporalRelation 是故事时间关系；DependencyEdge 是工程依赖。  
产生者：工作流服务、依赖追踪服务。  
读取者：重算服务、Checkpoint、WorkflowRun。  
是否必须包含 EvidenceRef：否。  
候选Schema：DependencyEdgeV1。  
备注或待确认问题：完整 DependencyGraph、自动重算调度和缓存策略暂不进入 MVP；本轮只定义文档语义和 QA 注意事项。

## Approval

中文名称：审核记录  
所属阶段：质检、修复和工作流  
优先级：P0  
精确定义：Approval 表示人工或系统对 StoryBible、VisualBible、QAResult、候选图或修复结果的审核决定。Approval 是审计记录，不直接改变故事事实，改变必须通过 CommitService。  
识别规则：团队成员或自动门禁批准、拒绝、冻结或退回对象时建立。  
正例：人工冻结 VisualBible revision 2。  
反例：Agent 高置信度输出不是 Approval。  
容易混淆：Confidence 是模型估计；Approval 是审核决策。  
产生者：人工审核界面、自动门禁。  
读取者：CommitService、WorkflowRun、导出服务。  
是否必须包含 EvidenceRef：视情况而定。  
候选Schema：ApprovalV1。  
备注或待确认问题：审批角色权限需后续定义。  

## WorkflowRun

中文名称：工作流运行记录  
所属阶段：质检、修复和工作流  
优先级：P0  
精确定义：WorkflowRun 表示一次端到端或局部流程执行记录，包含状态、输入、输出、失败点、成本和 Checkpoint。  
识别规则：导入、故事编译、页面生成、QA 修复或导出流程启动时建立。  
正例：运行“导入黄金小说并生成 chunks”的一次记录。  
反例：单个 Agent 调用不是 WorkflowRun，而是 AgentRun。  
容易混淆：AgentRun 是单个 Agent 执行；WorkflowRun 是流程级执行。  
产生者：工作流引擎。  
读取者：监控、断点恢复、成本统计。  
是否必须包含 EvidenceRef：否。  
候选Schema：WorkflowRunV1。  
备注或待确认问题：后续可接 LangGraph。  

## AgentRun

中文名称：Agent 运行记录  
所属阶段：质检、修复和工作流  
优先级：P0  
精确定义：AgentRun 表示一次 Agent 在限定 Context 上执行的记录，包括输入引用、输出 Proposal、耗时、错误和模型配置引用。它不应包含真实 API Key。  
识别规则：任一 Agent 被工作流调用时建立。  
正例：事件抽取 Agent 处理第 1 章 20 个 chunks。  
反例：Provider 的一次图片请求是 GenerationJob，不是 AgentRun。  
容易混淆：WorkflowRun 是流程；AgentRun 是流程中的一次 Agent 调用。  
产生者：Agent Wrapper、工作流引擎。  
读取者：调试、审计、成本统计、QA。  
是否必须包含 EvidenceRef：否；输出 Proposal 自身按需含证据。  
候选Schema：AgentRunV1。  
备注或待确认问题：无。  

## Checkpoint

中文名称：工作流检查点  
所属阶段：质检、修复和工作流  
优先级：P0  
精确定义：Checkpoint 表示工作流可恢复位置及必要状态快照，用于失败后从最近安全点继续，而不是全量重跑。  
识别规则：完成导入、实体合并、StoryBible 冻结、页面生成、QA 等关键节点时建立。  
正例：StoryBible 冻结后建立 Checkpoint。  
反例：一次普通日志行不是 Checkpoint。  
容易混淆：Revision 是数据版本；Checkpoint 是运行恢复点。  
产生者：工作流引擎。  
读取者：断点恢复、依赖重算服务。  
是否必须包含 EvidenceRef：否。  
候选Schema：CheckpointV1。  
备注或待确认问题：无。  

## CommitService

中文名称：正式数据提交服务  
所属阶段：质检、修复和工作流  
优先级：P0  
精确定义：CommitService 是唯一允许把经过验证的 Proposal 或程序结果写入 Canonical Data 的服务。它负责 Schema 校验、证据检查、状态检查、冲突处理和 Revision 管理。  
识别规则：任何正式故事事实、状态或审核冻结写入前必须经过它。两个或多个 Agent 输出互斥 Proposal 时，CommitService 不得任选其一；应保留冲突 Proposal/Claim，只提交证据支持的中性事实，并在需要人工判断时生成审核项。
正例：把合并后的 Event 写入 Canonical Event；在“程放拿卡”和“林祁拿卡”互斥 Proposal 冲突时，只提交“有人在停电前拿走门禁卡”和“门禁卡后来出现在林祁外套里”等已证中性事实。
反例：Agent 直接写数据库不是 CommitService。  
容易混淆：SourceRepository 可保存原文结构；CommitService 控制正式故事数据提交。  
产生者：普通程序服务。  
读取者：工作流、审核界面、数据库层。  
是否必须包含 EvidenceRef：否；它负责验证别人是否包含。  
候选Schema：CommitResultV1、CommitService。  
备注或待确认问题：完整自动真相裁决和复杂冲突评分策略需后续设计。

## ContextBuilder

中文名称：Agent 上下文组装器  
所属阶段：质检、修复和工作流  
优先级：P0  
精确定义：ContextBuilder 是为 Agent 组装有限、可审计输入上下文的普通程序组件，避免 Agent 直接读取整个数据库或拿到无关事实。  
识别规则：每次调用 Agent 前，根据 ProjectSpec、SourceChunk、StoryBible、VisualBible 和依赖关系构造上下文。  
正例：为事件抽取 Agent 提供第 2 章相关 chunks 和已知实体。  
反例：把全库 dump 给 Agent 不是 ContextBuilder 的合格输出。  
容易混淆：Provider 调外部模型；ContextBuilder 只组装输入。  
产生者：普通程序服务。  
读取者：Agent Wrapper、所有 Agent。  
是否必须包含 EvidenceRef：否；上下文中事实应保留证据引用。  
候选Schema：AgentContextV1。  
备注或待确认问题：上下文窗口策略需后续优化。  

## Provider

中文名称：外部模型服务适配器  
所属阶段：质检、修复和工作流  
优先级：P0  
精确定义：Provider 是对外部 LLM、图片生成、图片编辑或检索服务的统一适配接口。业务模块不得直接调用供应商 API。  
识别规则：任何外部模型调用都必须通过对应 Provider。  
正例：MockImageProvider、LLMProvider、ImageProvider。  
反例：在 Agent 中直接写 HTTP 请求到图片模型 API。  
容易混淆：PromptSpec 是请求数据；Provider 是执行请求的适配器。  
产生者：平台工程。  
读取者：Agent Wrapper、模型路由器、工作流。  
是否必须包含 EvidenceRef：否。  
候选Schema：ProviderRequestV1、ProviderResultV1。  
备注或待确认问题：供应商选择需团队确认。  

## Idempotency

中文名称：幂等性  
所属阶段：质检、修复和工作流  
优先级：P0  
精确定义：Idempotency 表示同一输入、同一语义操作重复执行时不会产生重复正式数据或不可控副作用。它是导入、提交、生成任务和修复循环的基础工程规则。  
识别规则：任何写操作、外部任务创建或可重试流程都必须定义幂等键或重复检测策略。  
正例：相同文件 checksum 重复导入只产生一个 SourceDocument。  
反例：重复上传同一 TXT 产生两套 chunks。  
容易混淆：Revision 记录合法变更；Idempotency 防止重复副作用。  
产生者：普通程序服务、数据库约束、工作流。  
读取者：导入服务、CommitService、GenerationJob、Checkpoint。  
是否必须包含 EvidenceRef：否。  
候选Schema：IdempotencyKeyV1、operation_id 字段。  
备注或待确认问题：无。  

## 概念对比

### Event 与 NarrativeMention

- [Event](#event) 是故事世界中实际发生的一次事情。
- [NarrativeMention](#narrativemention) 是原文对某个 Event 的一次描述、回忆、转述或暗示。
- 同一个 Event 可以对应多个 NarrativeMention。
- 一个未经证实的回忆、传闻或角色说法不能直接升级成 Canonical Event。
- DREAM 内部发生的事情不能默认成为 PRIMARY 现实主线 Event。

### NarrativeOrder 与 StoryTime

- [NarrativeOrder](#narrativeorder) 表示内容在小说文本中的出现顺序。
- [StoryTime](#storytime) 表示事情在故事世界中真正发生的时间位置。
- 倒叙时两者顺序不一致。
- StoryTime 允许只有相对时间或 UNKNOWN，不强制推断准确日期。

### StateChange 与 CharacterState

- [StateChange](#statechange) 描述某个属性发生的一次变化。
- [CharacterState](#characterstate) 表示某个时间点或区间内完整有效的人物状态。
- StateChange 通常由 Agent 从原文提取。
- CharacterState 通常由确定性程序根据时间图和 StateChange 编译得到。

### CharacterState 与 CharacterVisualVariant

- [CharacterState](#characterstate) 描述故事事实。
- [CharacterVisualVariant](#charactervisualvariant) 描述该状态应该如何被画出来。
- 同一个 CharacterState 可以有多个经过审核的视觉资产。
- 视觉版本不能反向修改故事事实。

### Scene、StoryBeat 与 Panel

- [Scene](#scene) 是一段时间、地点和 RealityLayer 相对连续的剧情。
- [StoryBeat](#storybeat) 是 Scene 中最小的有叙事意义的动作或信息变化。
- Panel 是漫画中的一格，当前词汇体系用 [PanelSpec](#panelspec) 描述其规划合同，用 [RenderedPanel](#renderedpanel) 描述渲染结果。
- 一个 StoryBeat 可能对应多个 Panel。
- 多个简单 StoryBeat 也可能合并为一个 Panel。

### PanelSpec 与 PromptSpec

- [PanelSpec](#panelspec) 描述漫画格必须表达的故事事实和视觉约束。
- PanelSpec 与模型供应商无关。
- [PromptSpec](#promptspec) 是为某个具体模型编译出来的请求。
- provider、model_name、positive_prompt、API Key 和模型专属采样参数不能写入 PanelSpec。

### Proposal 与 Canonical Data

- [Proposal](#proposal) 是候选结果，Agent 只能输出 Proposal。
- Proposal 可能重复、冲突、证据不足或错误。
- Proposal 必须经过 Schema 验证、证据检查、实体合并和冲突处理。
- 只有 [CommitService](#commitservice) 能够将结果提交为 [Canonical Data](#canonical-data)。

### FactLock 与 Canonical Data

- [Canonical Data](#canonical-data) 是被提交的正式事实。
- [FactLock](#factlock) 是下游文字、海报、分镜或 QA 对正式事实的精确性约束。
- FactLock 不新增事实，只要求日期、星期、时间、地点、数字单位、联系人、电话、邮箱和流程规则不得被改写。
- 旧通知或旧海报中的过期 FactLock 字段应标记 STALE，不能覆盖最新有效 Canonical Data。
- 信息省略是否 hard failure 取决于 PanelSpec 的展示目标和 completeness 要求。

### EntityAlias 与 EntityMention

- [EntityAlias](#entityalias) 是同一 Entity 的稳定可复用名称映射。
- [EntityMention](#entitymention) 是 SourceChunk 中的一次文本出现。
- 代词、一次性称呼、签名和缩写默认先作为 EntityMention。
- 只有证据支持跨片段稳定指向同一对象时，EntityMention 才能支持建立 EntityAlias。
- 相似读音、同名、同首字母或同款物品不能单独形成 EntityAlias。

### Account 与 Character

- [Account](#account) 是可登录、发布或署名的数字身份。
- [Character](#character) 是故事世界中的人物。
- 一个 Character 可以运营多个 Account，一个 Account 也可能被多人知道密码或共同使用。
- 账号名不能默认成为人物别名，除非有证据确认账号稳定代表该人物。
- 账号的可见发布行为不能自动证明具体 Character 亲自发布。

### Account Operator 与 Message Author

- Account Operator 表示通过 [AccountAccessRelation](#accountaccessrelation) 记录的账号经营者、知晓密码者或访问者。
- Message Author 表示通过 [AuthorshipClaim](#authorshipclaim) 记录的具体 Message 作者、发送者或发布者。
- 经营账号可以作为作者候选证据，但不能单独确认每一条 Message 的作者。
- 定时发布、共享密码、冒用和代发都会让 operator 与 author 分离。

### Claim 与 Event

- [Event](#event) 是故事世界中发生的行动、变化或信息接收。
- [Claim](#claim) 是某个来源对事实提出的说法、否认、猜测、记忆或解释。
- “收到邮件”是 Event；邮件里写的内容是 Claim。
- Claim 只有在证据检查和冲突处理后，才能支持建立或修正 Canonical Event。
- 被角色否认的事不自动变成未发生事件；它首先是一条 DENIAL Claim。
- 角色确信、研究员推测和系统日志标签都不能单独升级为 Canonical Data；系统日志标签是证据线索，若其生成或修改过程被质疑，应同时保存冲突 Claim。

### RealityLayer、Claim 与 Canonical Data

- 画面内容说明“角色或系统呈现了什么”，不等于现实主线事实。
- 角色说法说明“角色相信或声称什么”，进入 Claim 或 KnowledgeState。
- 系统日志标签说明“系统如何标记画面来源”，可作为 Evidence 线索或 Claim，但不是不可质疑的事实。
- Canonical Data 只能来自证据检查、冲突处理和 CommitService；设备画面、角色确信、系统标签和研究员推测都不能绕过这一层。
- 预测模拟优先归入 `HYPOTHETICAL`，不作为已发生 StoryTime，也不自动成为 `FLASH_FORWARD`。

### Character Belief 与 Canonical Fact

- Character Belief 是 [KnowledgeState](#knowledgestate) 中 BELIEVES、SUSPECTS 或 DISBELIEVES 等认知状态。
- Canonical Fact 是通过 [Canonical Data](#canonical-data) 提交的正式事实。
- 角色可以相信错误内容，也可以不知道读者已经知道的事实。
- PanelSpec 和 DialogueUnit 生成必须查询该角色当时的 KnowledgeState，不能直接使用读者视角事实。
- 当角色草稿、内心独白或对话与 Canonical Data 冲突时，应保留 Claim 和 KnowledgeState，而不是覆盖事实。

### Organization 与 UnresolvedGroupReference

- [Organization](#organization) 需要稳定名称、边界、职能或成员关系证据。
- [UnresolvedGroupReference](#unresolvedgroupreference) 只表示尚未解析的群体指代。
- “他们”“那些人”不能默认解释为某个组织。
- 后续证据明确成员或组织身份后，UnresolvedGroupReference 可以被解析为 Organization、多个 Character 或二者组合。

### RelationshipState 多维状态

- [RelationshipState](#relationshipstate) 不是单一“朋友/敌人/和解”标签。
- StructuralRelation、InteractionState、TrustState 和 CommunicationAccess 必须独立记录。
- COOPERATING 只说明当前协作行为，不说明 TRUSTS。
- 通讯权限变化可以作为 CommunicationAccess 证据，但不能单独证明真实情感关系。
- 默契动作只能支持互动状态，不能反向证明信任或原谅。

### ObjectState 的 Owner、Holder 与 In Use

- [ObjectState](#objectstate) 的 owner_id 表示长期归属或明确所有者。
- holder_id 表示当前物理持有者。
- in_use_by_id 表示当前实际使用者或佩戴者。
- authorized_user_ids 表示被允许使用的人。
- 交给、借用、佩戴和保管都不能静默修改 owner。

### InjuryState 与 CharacterVisualVariant

- [InjuryState](#injurystate) 记录伤势生命周期和可见标记。
- [CharacterVisualVariant](#charactervisualvariant) 记录稳定可复用的人物视觉身份版本。
- 包扎、血迹和短期绷带通常属于临时视觉状态，不应创建永久 CharacterVisualVariant。
- 持久疤痕可以参与新 CharacterVisualVariant 或 ResolvedCharacterAppearance。
- 视觉状态不能反向修改伤势事实。

### Observable Behavior 与 Internal State

- 可观察行为可以成为 [Event](#event)。
- 人物对白可以成为 [DialogueUnit](#dialogueunit)、[Claim](#claim) 或 [ExpressedStance](#expressedstance)。
- 内心状态只有在可靠 [NarrativePerspective](#narrativeperspective) 明确呈现时，才能进入 Canonical CharacterState。
- 哭泣、沉默、配合、默契动作都不能自动证明责任、信任或原谅。

## 团队评审清单

- [ ] Event 和 NarrativeMention 边界是否清楚
- [ ] NarrativeOrder 和 StoryTime 是否区分
- [ ] Scene 和 StoryBeat 是否区分
- [ ] StoryBeat 和 Panel 是否区分
- [ ] StateChange 和 CharacterState 是否区分
- [ ] 梦境是否会污染现实主线
- [ ] 回忆是否查询历史状态
- [ ] 不可靠记忆是否被当作正式事实
- [ ] CharacterState 和视觉版本是否解耦
- [ ] PanelSpec 是否与模型供应商解耦
- [ ] Proposal 是否不能直接写正式数据库
- [ ] 所有关键事实是否要求 EvidenceRef
- [ ] EntityAlias 和 EntityMention 是否区分
- [ ] Account、AccountAccessRelation 和 AuthorshipClaim 是否区分
- [ ] Claim、KnowledgeState 和 Canonical Data 是否区分
- [ ] Organization 和 UnresolvedGroupReference 是否区分
- [ ] RelationshipState 是否按多维关系独立记录
- [ ] ObjectState 是否区分 owner、holder、authorized_user 和 in_use_by
- [ ] InjuryState 是否覆盖受伤、处理、恢复和疤痕阶段
- [ ] CharacterVisualVariant 是否避免临时状态组合爆炸
- [ ] 可观察行为、表达态度和真实内心是否区分
- [ ] QA 是否区分硬性错误和软性质量
- [ ] FactLock 是否锁定通知类关键字段并保留 EvidenceRef
- [ ] 每个词是否有正例和反例
- [ ] P0 词汇是否足以支撑 MVP 流水线
