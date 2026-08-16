# 刘文熙分镜生图 Agent

独立的场景级异步生图服务。上游只需要提交一个
`UpstreamSceneEnvelopeV1`，其余的素材解析、视觉规划、Prompt 编译、
GPU 调度、图片生成、状态持久化和结果封装均在服务内部执行。

## 上游边界

- 唯一任务写入接口：`POST /v1/scene-jobs`
- 请求结构：`schemas/upstream-scene-envelope-v1.schema.json`
- 返回结构：`SceneResultV1`
- 相同 `request_id` 和相同 Envelope 幂等返回
- 相同 `request_id` 但内容不同返回 HTTP `409`
- 内部 `SceneJobV1` 不作为上游请求结构

完整请求样例位于 `examples/upstream_scene_envelope.valid.json`。公开 demo
素材位于 `assets/presets/demo-v1`，许可证为 CC0-1.0。

## 本地联调

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
export PYTHONPATH="$PWD/src"
python -m anime_image_agent serve --backend fake --host 127.0.0.1 --port 8000
```

```bash
curl -X POST http://127.0.0.1:8000/v1/scene-jobs \
  -H 'Content-Type: application/json' \
  --data-binary @examples/upstream_scene_envelope.valid.json
```

Fake 后端不会调用真实模型，只用于验证 HTTP、Schema、素材、内部工作流、
幂等和结果接口。生产 GPU 部署方式见 `IMAGE_PROVIDER.md`。

## 验证

```bash
export PYTHONPATH="$PWD/src"
pytest -q
```

需要真实 8×A40 节点的测试默认跳过。
