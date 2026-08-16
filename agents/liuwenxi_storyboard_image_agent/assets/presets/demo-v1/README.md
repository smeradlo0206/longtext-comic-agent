# demo-v1 素材集

该目录已包含可直接运行工作流的三张原创 demo 参考图：

- `characters/char-a-ref-01.png`
- `scenes/scene-library-ref-01.png`
- `styles/style-comic-ref-01.png`

素材由 `scripts/build_demo_assets.py` 确定性生成，按 CC0-1.0 用于项目测试。脚本会同时更新 `manifest.json` 中的 SHA256：

```bash
python scripts/build_demo_assets.py
```

这些图片用于验证人物、场景、风格素材绑定与 Qwen Image Edit 多图输入。它们不是最终美术资产，接入正式素材库后可保持相同 manifest/Repository 接口直接替换。

项目根目录中的三张微信截图是架构说明，不属于视觉参考素材。
