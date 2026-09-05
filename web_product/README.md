# 绘卷：GitHub Pages 接入真实生产服务

目前没有公网 API 时，Pages 默认使用演示模式，打开即可体验上传、进度和阅读。
展示的是内置 SVG 示例，不会根据文本调用模型，也不提供真实 PDF/ZIP 下载。
未设置 COMIC_API_BASE_URL 不会再阻止部署。

页面右上角的“连接设置”可在当前浏览器切换服务。只有浏览器能访问 API 时，
才能真实提交生成任务。如果 API 就运行在打开页面的电脑上，可尝试
http://127.0.0.1:8000；若 API 在另一台服务器且仅绑定 localhost，需先通过
已有 SSH 连接将服务器 API 端口转发到本机，再填写本机转发端口。
连接成功只验证 API 与参考素材配置，不代表 GPU 已启动或已完成实际出图。
浏览器可能需要允许本地网络访问，服务器 CORS_ORIGINS 仍需包含 Pages origin。
连接失败时保留当前模式，不自动将失败任务替换为演示。

Pages 托管静态前端，HTTPS FastAPI 服务负责文本导入与分镜编译，Linux GPU
worker 负责 FLUX.2 生图。当前网页入口采用 DETERMINISTIC_EXTRACTIVE 原文提取式
分镜，使用服务器预设的参考素材。它不执行 Narrative/Timeline/StoryBible LLM
审核工作流，也不会将 demo fallback 当作生产审批。

## 服务器配置

在项目根目录的 .env 中配置：

```dotenv
WORKSPACE_ROOT=/srv/longtext-comic-agent
DATABASE_URL=sqlite+pysqlite:////srv/longtext-comic-agent/comic_agent.db
IMAGE_QUEUE_ROOT=queue
IMAGE_RUN_ROOT=runs
PRODUCT_REQUEST_TEMPLATE=configs/longtext-morning-tea.json
CORS_ORIGINS=["https://YOUR-ACCOUNT.github.io"]
```

PRODUCT_REQUEST_TEMPLATE 是服务器维护的 ComicProductionRequestV1 JSON。
示例路径仅示范格式，请改成适合实际故事的配置：selected_assets 必须对应
inputs/references/manifest.json 中存在的素材；若采用 APPROVED_LIBRARY，
素材必须已审核并满足 canonical 要求。服务器保留种子、QA、文字排版、素材策略和
设备参数；网页只覆盖原文、风格、创作要求、单格画幅、最多页数。

API 与 worker 必须使用同一工作区、同一 queue 和 runs 目录；若在不同机器，
必须共享这些目录，并让运行产物绝对路径在 API 端同样可访问。仅把文本分析 API
启动在另一台不共享文件的机器上，不会自动把任务传到 GPU 服务器。

在该 Linux 项目环境中启动：

```bash
uv sync --extra dev
uv run uvicorn comic_agent.main:app --host 0.0.0.0 --port 8000
```

另一个进程持续处理队列：

```bash
uv run flux2-agent --workspace /srv/longtext-comic-agent queue \
  --root /srv/longtext-comic-agent/queue worker \
  --output-root /srv/longtext-comic-agent/runs \
  --model-path /srv/longtext-comic-agent/models/FLUX.2-klein-4B \
  --offline --watch
```

用服务器反向代理提供 HTTPS API 域名。CORS_ORIGINS 填 Pages 的 origin，
例如 https://alice.github.io，不含仓库路径。若只做团队联调，将 API 放在已有的
访问控制范围内；当前项目没有用户账号隔离，浏览器任务历史不代表权限控制。

## Pages 配置与部署

以后有 HTTPS API 时，可在 GitHub 仓库 Settings → Secrets and variables → Actions → Variables 中设置：

- COMIC_API_BASE_URL = https://你的API域名

在 Settings → Pages 中选择 GitHub Actions。推送 main 或手动运行
Deploy Product Web to GitHub Pages；workflow 会生成 js/deploy-config.js，
有 HTTPS 地址时默认真实模式，没有时默认演示模式；填写了非法地址则部署报错。

公开 URL 可进入前端，LLM 密钥不得写到仓库变量或前端。
本地直接访问 API 的 /product/ 页面会使用同源 API。
也可以使用页面“连接设置”保存当前浏览器的 API 地址，或切回演示模式。
本地选择优先于部署默认值，仅存储在当前浏览器中。

## 用户操作与接口

上传 TXT → POST /projects → POST /projects/{id}/documents/import →
POST /projects/{id}/comic-runs/from-product → GPU worker →
GET /comic-runs/{id} 轮询并拼页 → 图片阅读 / PDF / ZIP 下载。

| 能力 | 接口 |
| --- | --- |
| 查看服务器参考素材方案 | GET /product-capabilities |
| 创建生产任务 | POST /projects/{id}/comic-runs/from-product |
| 查询状态与结果 | GET /comic-runs/{id} |
| 取消等待中的任务 | POST /comic-runs/{id}/cancel |
| 重试失败任务 | POST /comic-runs/{id}/retry |
| 浏览页面 | GET /comic-runs/{id}/pages/{number} |
| 下载 | GET /comic-runs/{id}/download?format=pdf 或 zip |

RealComicGenerationAPI 负责把后端 QUEUED/RUNNING/SUCCEEDED 状态与
page_artifacts 转成前端视图数据。轮询间隔两秒，短暂断网自动重连；
已成功生成的页面统一在拼页完成后可见，不模拟百分比进度。
正在 GPU 上执行的任务不可取消。成功或已取消任务需回创作页重新提交。
“我的作品”保存此浏览器、此 API 地址下的任务记录；刷新后可点击恢复查看。
清除浏览器数据后本地作品索引会丢失，服务器任务本身仍保留。

## 验证

```bash
uv run pytest tests/test_product_api.py tests/test_process_lock.py \
  tests/test_web_product_static.py tests/test_comic_production.py
```

接口测试使用替代图片生成器执行真实队列、拼页、图片与 PDF/ZIP 接口。
可选浏览器测试需要 playwright 与 Microsoft Edge；没有 playwright 时跳过。
上线验收还需要实际服务器配置、GPU 模型与一次真实图像生成。

本次 Windows 验证：32 项接口、浏览器、队列与素材目录测试通过；Ruff 与 schema
导出通过。全量测试为 1015 passed、7 failed、1 skipped：6 项失败是现有 Unix
权限位断言不适用于 Windows，另 1 项是独立脚本子进程未安装 flux2_agent 包。
全量 mypy 尚有 visual_qa 的既有类型问题及本机缺失 torch/diffusers 引发的 4 项错误；
本次新增适配代码无 mypy 报错。浏览器测试使用 Edge 与真实 API 实现，图片生成器
在测试中替换为本地假实现，未调用真实模型。
