import { ComicGenerationAPI } from './comic-generation-api.js';

export class RealComicGenerationAPI extends ComicGenerationAPI {
  constructor(base = window.__COMIC_API_BASE_URL__ || '') {
    super(); this.base = base.replace(/\/+$/, '');
    this.key = 'huijuan.real.runs:' + this.base;
  }
  async _request(path, options = {}, binary = false) {
    if (!this.base) throw new Error('生成服务尚未配置，请联系站点管理员');
    let response;
    try { response = await fetch(this.base + path, { ...options, signal: AbortSignal.timeout(120000) }); }
    catch { throw new Error('无法连接生成服务，请检查网络后重试'); }
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(typeof error.detail === 'string' ? error.detail : '生成服务请求失败 (' + response.status + ')');
    }
    return binary ? response.blob() : response.json();
  }
  _json(path, value) {
    return this._request(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(value) });
  }
  _history() {
    try { return JSON.parse(localStorage.getItem(this.key) || '{}'); } catch { return {}; }
  }
  _remember(id, metadata) {
    const saved = this._history(); saved[id] = metadata;
    localStorage.setItem(this.key, JSON.stringify(saved));
  }
  _pages(run) {
    return [...run.page_artifacts].sort((a, b) => a.order - b.order).map((page, i) => ({
      id: page.page_id, number: i + 1, width: page.width, height: page.height,
      imageUrl: this.base + '/comic-runs/' + encodeURIComponent(run.run_id) + '/pages/' + (i + 1),
      thumbnailUrl: this.base + '/comic-runs/' + encodeURIComponent(run.run_id) + '/pages/' + (i + 1),
      sceneTitle: '第 ' + (i + 1) + ' 页',
    }));
  }
  _view(run) {
    const metadata = this._history()[run.run_id] || {};
    const status = { COMPILED: 'RUNNING', QUEUED: 'RUNNING', RUNNING: 'RUNNING', SUCCEEDED: 'COMPLETED', FAILED: 'FAILED', CANCELLED: 'CANCELLED' }[run.status];
    const pages = this._pages(run);
    return {
      runId: run.run_id, status, stage: status === 'COMPLETED' ? 'COMPLETED' : 'IMAGE_GENERATION',
      progress: status === 'COMPLETED' ? 100 : 0, indeterminate: status === 'RUNNING',
      current: pages.length, total: run.manifest.proposal.pages.length, availablePages: pages.length,
      previewPages: pages, createdAt: run.created_at, title: metadata.title || '漫画作品',
      fileName: metadata.fileName || '', preferences: metadata.preferences || {},
      message: { COMPILED: '分镜已准备，正在提交队列', QUEUED: '已进入服务器队列，等待绘制', RUNNING: '服务器正在绘制，完成后将显示漫画页面', SUCCEEDED: '漫画已完成', FAILED: '服务器生成失败，可重试或联系管理员', CANCELLED: '任务已取消' }[run.status],
      canCancel: ['COMPILED', 'QUEUED'].includes(run.status),
    };
  }
  async createGeneration(input) {
    await this._request('/product-capabilities');
    const digest = await crypto.subtle.digest('SHA-256', await input.file.arrayBuffer());
    const contentHash = Array.from(new Uint8Array(digest), x => x.toString(16).padStart(2, '0')).join('');
    const fingerprint = JSON.stringify([input.file.name, contentHash, input.prompt, input.preferences]);
    const pendingKey = this.key + ':pending';
    let pending = JSON.parse(sessionStorage.getItem(pendingKey) || 'null');
    if (!pending || pending.fingerprint !== fingerprint) {
      pending = { fingerprint, projectId: 'pages-' + crypto.randomUUID() };
      sessionStorage.setItem(pendingKey, JSON.stringify(pending));
    }
    const title = input.file.name.replace(/\.txt$/i, '');
    await this._json('/projects', { project_id: pending.projectId, name: title });
    const body = new FormData(); body.append('file', input.file);
    const imported = await this._request('/projects/' + pending.projectId + '/documents/import', { method: 'POST', body });
    const preferences = input.preferences || {};
    const run = await this._json('/projects/' + pending.projectId + '/comic-runs/from-product', {
      document_id: imported.document.document_id, prompt: input.prompt,
      style: preferences.style || '电影写实', aspect_ratio: preferences.aspectRatio || 'portrait',
      max_pages: parseInt(preferences.length || '12', 10),
    });
    this._remember(run.run_id, { title, fileName: input.file.name, prompt: input.prompt, preferences });
    sessionStorage.removeItem(pendingKey);
    return this._view(run);
  }
  async getGeneration(id) { return this._view(await this._request('/comic-runs/' + encodeURIComponent(id))); }
  async getGenerationResult(id) {
    const run = await this._request('/comic-runs/' + encodeURIComponent(id));
    if (run.status !== 'SUCCEEDED') throw new Error('漫画尚未完成');
    const view = this._view(run);
    return { runId: id, title: view.title, pageCount: run.page_artifacts.length,
      panelCount: run.manifest.proposal.panels.length, pages: this._pages(run),
      sourceFile: view.fileName, prompt: this._history()[id]?.prompt || '',
      preferences: view.preferences, createdAt: run.created_at };
  }
  async listGenerations() { return Promise.all(Object.keys(this._history()).reverse().map(id => this.getGeneration(id))); }
  async cancelGeneration(id) { return this._view(await this._json('/comic-runs/' + encodeURIComponent(id) + '/cancel', {})); }
  async retryGeneration(id) {
    const current = await this.getGeneration(id);
    if (current.status !== 'FAILED') throw new Error('只有失败任务可重试；请回到创作页提交新任务');
    return this._view(await this._json('/comic-runs/' + encodeURIComponent(id) + '/retry', {}));
  }
  async downloadComic(id, format) {
    const blob = await this._request('/comic-runs/' + encodeURIComponent(id) + '/download?format=' + encodeURIComponent(format), {}, true);
    const url = URL.createObjectURL(blob), link = document.createElement('a');
    link.href = url; link.download = 'comic.' + format;
    document.body.append(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 60000);
    return { message: '漫画已开始下载' };
  }
}
