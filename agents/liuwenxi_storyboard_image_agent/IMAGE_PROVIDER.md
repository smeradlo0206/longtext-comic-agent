# 8×A40 Qwen 漫画生图 Agent V1

场景级异步 HTTP Agent 只保留一个上游任务写入边界。`SceneJobV1` 及后续结构均为内部实现：

```text
UpstreamSceneEnvelopeV1（唯一上游请求结构）
  → 严格校验与确定性映射
  → SceneJobV1（内部）
  → PresetAssetRepository
  → Qwen2.5-VL-7B VisualPlanV1
  → GenerationSpecV1
  → Qwen-Image-Edit-2509
  → SceneResultV1
```

V1 每次提交一个最多 32 格的场景，每格最多两个角色和一张输出图。支持：

- `landscape`：1664×928
- `portrait`：928×1664
- `square`：1328×1328

不包含视觉评估、自动选图、语义重生成和对白渲染。

## 安装与素材

```bash
bash env_install.sh
source activate.sh
```

仓库已在 `assets/presets/demo-v1` 提供可运行的原创 demo 参考图。可运行 `python scripts/build_demo_assets.py` 重新生成图片并更新 SHA256。接入正式素材时按该目录 README 替换文件即可。

首次生产执行会下载并锁定以下 checkpoint：

- `Qwen/Qwen2.5-VL-7B-Instruct`
- `Qwen/Qwen-Image-Edit-2509`

锁文件分别写入 `${MODEL_ROOT}/qwen2.5-vl-7b` 和 `${MODEL_ROOT}/qwen-image-edit-2509`。

## 本地 Fake 验证

Fake 模式不加载模型和 GPU，但需要一份 checksum 正确的 preset 素材：

```bash
export PYTHONPATH="${PROJECT_ROOT}/src"
python -m anime_image_agent serve --backend fake --host 127.0.0.1 --port 8000
curl -X POST http://127.0.0.1:8000/v1/scene-jobs \
  -H 'Content-Type: application/json' \
  --data-binary @examples/upstream_scene_envelope.valid.json
```

也可以不启动监听端口，直接执行完整 ASGI/SQLite 工作流：

```bash
python scripts/run_demo_workflow.py
```

Fake 模式输出条纹测试图，仅证明 HTTP、素材解析、规划、编译、任务状态和 artifact 下载链路可用；真实漫画画面必须在 8×A40 节点使用 `--backend qwen` 生成。

运维人员也可使用内部 CLI 提交同一份 Envelope 并排空；这不是上游集成接口：

```bash
python -m anime_image_agent scene-submit examples/upstream_scene_envelope.valid.json
python -m anime_image_agent scene-drain --backend fake
```

## 8 卡生产运行

```bash
bash run_scene_agent_8gpu.sh
```

默认仅监听 `127.0.0.1:8000`。上游唯一写入接口：

- `POST /v1/scene-jobs`

请求体固定为 `schemas/upstream-scene-envelope-v1.schema.json` 定义的
`UpstreamSceneEnvelopeV1`。内部 `SceneJobV1` 不被该端点接受。

任务提交后使用以下只读接口查询和取回结果：

- `GET /v1/scene-jobs/{request_id}`
- `GET /v1/scene-jobs/{request_id}/result`
- `GET /v1/artifacts/{image_id}`
- `GET /health/live`
- `GET /health/ready`

GPU 调度分三阶段：最多 8 个单卡视觉规划进程、最多 8 个单卡条件编码进程、4 个双卡扩散 worker，映射为 `0,1`、`2,3`、`4,5`、`6,7`。阶段间卸载模型并释放显存。

## 持久化

- SQLite：`${RUN_ROOT}/image-provider/scene-jobs.sqlite3`
- 图片：`${OUTPUT_ROOT}/image-provider/scene-jobs/...`
- 参考图缓存：`${SCRATCH_ROOT}/image-provider/asset-cache`
- 模型条件中间产物：`${SCRATCH_ROOT}/image-provider/scene-conditioning`

同一 `request_id` 和完全相同的上游 Envelope 幂等返回；Envelope 任意字段内容不一致均返回 HTTP `409`，包括当前内部映射不会消费的事件状态字段。技术错误以相同 `GenerationSpec` 和 seed 最多尝试三次。

## 测试与 Schema

```bash
pytest -q
python -m anime_image_agent schema --output schemas
RUN_SCENE_GPU_ACCEPTANCE=1 pytest tests/test_scene_gpu_acceptance.py -q
```

真实 GPU 验收要求独占的 8×A40 节点和完整 `demo-v1` 素材。
