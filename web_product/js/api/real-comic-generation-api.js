import { ComicGenerationAPI } from './comic-generation-api.js';

/**
 * RealComicGenerationAPI —— 未来真实后端的网络实现。
 *
 * 本轮后端不存在，此文件仅定义接口边界与请求形状，供未来接入：
 *
 *   POST   {apiBaseUrl}/api/comic-generation/runs                 → createGeneration
 *   GET    {apiBaseUrl}/api/comic-generation/runs                 → listGenerations
 *   GET    {apiBaseUrl}/api/comic-generation/runs/{runId}         → getGeneration
 *   GET    {apiBaseUrl}/api/comic-generation/runs/{runId}/result  → getGenerationResult
 *   POST   {apiBaseUrl}/api/comic-generation/runs/{runId}/cancel  → cancelGeneration
 *   POST   {apiBaseUrl}/api/comic-generation/runs/{runId}/retry   → retryGeneration
 *   GET    {apiBaseUrl}/api/comic-generation/runs/{runId}/download?format= → downloadComic
 *
 * 注意（未来后端需要处理）：
 *   - GitHub Pages 与后端跨域，后端须允许正式前端 origin 的 CORS；
 *   - LLM / 生图 / 下载等 secret 必须留在后端，绝不能进入前端代码。
 */
export class RealComicGenerationAPI extends ComicGenerationAPI {
  constructor() {
    super();
    if (!window.__COMIC_API_BASE_URL__) {
      // 产品级错误：避免向用户抛出一堆 JS traceback。
      console.error('[comic-api] apiMode=real 但未配置 apiBaseUrl');
    }
    this.base = (window.__COMIC_API_BASE_URL__ || '').replace(/\/+$/, '');
  }

  _configured() {
    return !!this.base;
  }

  _ensureConfigured() {
    if (!this._configured()) {
      throw new Error('真实生成服务尚未配置');
    }
  }

  async _request(path, options = {}) {
    this._ensureConfigured();
    let response;
    try {
      response = await fetch(this.base + path, {
        headers: { 'Content-Type': 'application/json' },
        ...options,
      });
    } catch (cause) {
      // 网络层错误同样转换为产品级消息。
      throw new Error('无法连接生成服务，请稍后重试');
    }
    if (!response.ok) {
      throw new Error('生成服务暂时不可用');
    }
    return response.json();
  }

  async createGeneration(input) {
    this._ensureConfigured();
    const body = new FormData();
    body.append('file', input.file);
    body.append('prompt', input.prompt || '');
    body.append('preferences', JSON.stringify(input.preferences || {}));
    let response;
    try {
      response = await fetch(`${this.base}/api/comic-generation/runs`, {
        method: 'POST',
        body,
      });
    } catch {
      throw new Error('无法连接生成服务，请稍后重试');
    }
    if (!response.ok) throw new Error('创建生成任务失败');
    return response.json();
  }

  async getGeneration(runId) { return this._request(`/api/comic-generation/runs/${runId}`); }
  async getGenerationResult(runId) { return this._request(`/api/comic-generation/runs/${runId}/result`); }
  async listGenerations() { return this._request('/api/comic-generation/runs'); }
  async cancelGeneration(runId) { return this._request(`/api/comic-generation/runs/${runId}/cancel`, { method: 'POST' }); }
  async retryGeneration(runId) { return this._request(`/api/comic-generation/runs/${runId}/retry`, { method: 'POST' }); }
  async downloadComic(runId, format) { return this._request(`/api/comic-generation/runs/${runId}/download?format=${encodeURIComponent(format)}`); }
}
