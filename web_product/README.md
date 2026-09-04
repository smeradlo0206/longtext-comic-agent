# 绘卷 · 长文本漫画产品前端

把长文本故事变成完整漫画的客户产品前端。**当前是纯静态站点 + Frontend Mock 模式**，
可直接部署到 GitHub Pages，不依赖 Python / FastAPI / 服务器。

## 本地静态开发

```bash
python -m http.server 8080 --directory web_product
```

打开 http://127.0.0.1:8080/

> 这个 Python server 只用于本地静态开发；正式部署不依赖 Python。

## GitHub Pages 部署

```text
Push to main
→ GitHub Actions（deploy-pages.yml）
→ 上传 web_product/ 静态产物
→ GitHub Pages 发布
```

或命令行流程：

```bash
git add web_product .github/workflows/deploy-pages.yml
git commit -m "feat(product): static GitHub Pages deploy for comic product frontend"
git push
```

仓库 Pages 设置：Settings → Pages → Source 选 **GitHub Actions**（workflow 已包含部署步骤）。

## 目录结构

```
web_product/
├── index.html                       # 单页壳（顶栏 / app / modal / toast / demo-switch）
├── 404.html                         # 静态 404 页（返回首页）
├── css/app.css                      # 全部视觉与响应式
└── js/
    ├── config.js                    # APP_CONFIG（apiMode / apiBaseUrl / storageKey）
    ├── app.js                       # 事件绑定 / 视图路由 / 全屏与键盘
    ├── api/
    │   ├── comic-generation-api.js      # 稳定前端契约 ComicGenerationAPI（DTO 定义）
    │   ├── mock-comic-generation-api.js # Mock 实现（timer 与 localStorage 完全隔离于此）
    │   └── real-comic-generation-api.js # 未来真实后端网络实现（本轮仅接口占位）
    ├── state/generation-store.js    # 状态机 + 轮询 + 草稿持久化
    └── components/ui.js             # 纯视图模板（无 timer、无 API 调用）
```

## 分层原则

```
ui.js（视图）+ app.js（事件）
   ↓ 仅读写 GenerationStore.state
generation-store.js（状态）
   ↓ 仅调用 API 接口
ComicGenerationAPI（契约） ← MockComicGenerationAPI / RealComicGenerationAPI
```

页面只消费前端 ViewModel（`GenerationViewModel` / `ComicResultViewModel` /
`ComicPageViewModel`），**禁止**直接引用后端 schema 字段；未来真实后端 schema 变化时只改 Adapter。

## API 契约（前端 DTO）

| 方法 | 说明 |
| --- | --- |
| `createGeneration({file,prompt,preferences})` | 创建生成任务，返回 run |
| `getGeneration(runId)` | 轮询状态（status / stage / progress / current / total / availablePages） |
| `getGenerationResult(runId)` | 返回最终结果（title / pageCount / panelCount / pages[]） |
| `listGenerations()` | 作品列表 |
| `cancelGeneration(runId)` | 取消 → `CANCELLED` |
| `retryGeneration(runId)` | 重新生成 |
| `downloadComic(runId, format)` | 下载（`pdf` / `zip`，Mock 返回提示） |

## Mock 模式（默认）

- 文件在浏览器本地读取（`FileReader` 语义），**不会上传到任何服务器**。
- 漫画页面来自 `assets/mock-comic/page-01.svg` 至 `page-12.svg`，无外部图片依赖。
- 作品列表与创作草稿持久化到 `localStorage`，刷新后仍在。
- 右下角 `Demo Mode` 切换器可选择下一次生成演示 **成功** 或 **失败** 流程。
- 首页 `示例作品 · 雨夜来客` 是内置 Demo 项目（12 页 / 28 画面）。

## 切换 / 未来接入真实后端

修改 [js/config.js](js/config.js)：

```javascript
export const APP_CONFIG = {
  apiMode: "real",
  apiBaseUrl: "https://api.example.com",
};
```

页面、状态管理、组件**无需重写**。真实网络请求集中在
[real-comic-generation-api.js](js/api/real-comic-generation-api.js)：

```text
POST   {apiBaseUrl}/api/comic-generation/runs
GET    {apiBaseUrl}/api/comic-generation/runs
GET    {apiBaseUrl}/api/comic-generation/runs/{runId}
GET    {apiBaseUrl}/api/comic-generation/runs/{runId}/result
POST   {apiBaseUrl}/api/comic-generation/runs/{runId}/cancel
POST   {apiBaseUrl}/api/comic-generation/runs/{runId}/retry
GET    {apiBaseUrl}/api/comic-generation/runs/{runId}/download?format=
```

**未来后端需注意**：

- CORS：后端须只允许正式前端 origin（GitHub Pages 与后端跨域）。
- secret：LLM / 生图 / 下载密钥必须留在后端，绝不能进入前端代码。

## Mock 进度模拟（timer）

| 时间 | 阶段 |
| --- | --- |
| ~0s | 创建任务（STORY_ANALYSIS） |
| ~3.9s | CHARACTER_WORLD → COMIC_PLANNING |
| ~2.7s | STORYBOARD |
| ~0.9s | IMAGE_GENERATION（页面逐页产出） |
| ~0.9s | PAGE_ASSEMBLY |
| ~0.9s | FINALIZING → COMPLETED |

所有 `setTimeout` 仅存在于 `mock-comic-generation-api.js`。
