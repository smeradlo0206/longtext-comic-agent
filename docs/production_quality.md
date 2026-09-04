# Production Quality Pipeline

## 单格 60 秒口径

`result.json.performance` 同时报告：

- `single_image_seconds`：队列等待、参考图处理、冷加载、身份锚点、最慢单格生成、该格 QA、
  字层和拼页摊销。`within_budget` 使用这个值与默认 `60s` SLA 比较。
- `end_to_end_seconds`：整批 panel 的真实总耗时。`workflow_within_budget` 仅用于观察整批是否
  也在预算内，不拿 6 格或 12 格总耗时冒充单格性能。
- `stages`：`model_load`、`identity_anchor_generation`、`panel_generation`、`visual_qa`、
  `selective_repair_generation`、`lettering`、`page_composition` 等分阶段耗时。

2026-08-23 的改造前冷启动基线为：1024x768、4 steps、1 张参考图，端到端 `15.77s`，其中
FLUX 推理 `5.61s`。加入最终 QA 后的同配置实测为 `16.856s`：模型加载 `10.252s`、生成
`5.979s`、QA `0.102s`，通过 60 秒预算。保持 worker 常驻会省去后续任务的模型加载；QA 和
气泡是 CPU 后处理，只有 QA 失败才增加一次扩散采样。查看报告：

```bash
jq '.performance' runs/<run-id>/result.json
```

## 参考素材库模式

推荐使用 `APPROVED_LIBRARY`，而不是把上传目录中的任意图片直接交给模型：

1. `candidate`：刚上传或文件内容发生变化，禁止进入严格生产。
2. `approved`：人工确认主体、授权、裁剪、清晰度、颜色和角色/场景归属。
3. `is_canonical=true`：某个 `entity_id + intended_role` 的冻结基准；同一组合只能有一个。
4. 服装、姿势、表情等变体使用明确 `variant`，审核后保持非 canonical；需要选变体时将
   `require_canonical` 设为 `false`，但仍要求 approved、实体和用途匹配。

```bash
flux2-agent --workspace . catalog
flux2-agent --workspace . references
flux2-agent --workspace . reference-set wechat-004 \
  --status approved \
  --entity-id character.male-lead \
  --role character_identity \
  --variant base \
  --canonical
```

manifest 使用文件锁和原子替换，多进程审核不会互相覆盖。生产配置示例见
`configs/longtext-morning-tea.json`。

## 自动 QA 与选择性修复

当前 `local-objective-visual-qa-v1` 自动检查：

- 输出尺寸；
- 5%-95% 灰度动态范围，拦截空白或低对比图；
- 邻接像素边缘能量，拦截严重缺失细节的图；
- 生成图与参考图的量化色彩直方图相似度。

失败会生成结构化 `QAResultV1` 和 `RepairPlanV1`。worker 只归档并重绘失败的 panel，正常 panel
不重新生成；`max_auto_repairs` 默认最多 1 次。当前相似度是低成本客观信号，不等价于人脸 ID、
手指数量、准确人数或剧情语义判断。严格角色项目应在同一 `PanelVisualQA` 接口后增加本地
CLIP/VLM/FaceID 评分器，并继续保留人工终审。

## 对白与气泡

规划器只抽取原文引号内的逐字对白，保存 chunk 字符跨度和 speaker entity；不允许新增对白。
FLUX 继续生成无字底图，`ComicLetterer` 另存 `lettered-<panel-id>.png` 并排版气泡，拼页只读取
带字副本。修改字体、字号或气泡位置无需重新生图。

要保证中文排版质量，请在本地配置 CJK 字体：

```text
./fonts/NotoSansCJK-Regular.ttc
```

也可通过 `dialogue_layout.font_path` 指定其他 CJK 字体。

## 人工工作

自动化之后仍需要人工完成以下关口：

1. 上传原文与参考素材，并确认使用权、隐私和内容合规。
2. 审核每个 candidate，绑定正确实体/用途/变体，只冻结一个 canonical 基准。
3. 审核自动身份锚点；脸型、服装或颜色错误时先换锚点，不要继续批量生成。
4. 审核分镜的原文证据、出场人数、动作、场景和对白 speaker。
5. 查看 QA 淘汰图与修复图；客观 QA 通过但人物身份、手部或剧情错误时人工指定该格重绘。
6. 在无字底图确认后调整气泡位置、字体和断行，最后审核 `page-*.png`。
