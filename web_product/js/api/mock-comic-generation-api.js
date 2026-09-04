import { ComicGenerationAPI } from './comic-generation-api.js';
import { APP_CONFIG } from '../config.js';

export const GENERATION_STAGES = ['STORY_ANALYSIS', 'CHARACTER_WORLD', 'COMIC_PLANNING', 'STORYBOARD', 'IMAGE_GENERATION', 'PAGE_ASSEMBLY', 'FINALIZING', 'COMPLETED'];
export const GENERATION_STATUSES = ['IDLE', 'UPLOADING', 'RUNNING', 'COMPLETED', 'FAILED', 'CANCELLED'];

const scenes = ['雨幕中的车站', '陌生人的来信', '旧城区追踪', '钟楼下的秘密', '真相浮现', '黎明之前'];
const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/** Return repository-local SVG assets; no server or external image host is needed. */
function comicPageAsset(number) {
  return `./assets/mock-comic/page-${String(number).padStart(2, '0')}.svg`;
}

function resultFor(run) {
  const pages = Array.from({ length: 12 }, (_, i) => ({
    id: `page-${i + 1}`,
    number: i + 1,
    imageUrl: comicPageAsset(i + 1),
    thumbnailUrl: comicPageAsset(i + 1),
    width: 900,
    height: 1280,
    sceneTitle: scenes[i % scenes.length],
  }));
  return {
    runId: run.runId,
    title: run.title,
    pageCount: 12,
    panelCount: 28,
    pages,
    sourceFile: run.fileName,
    prompt: run.prompt,
    preferences: run.preferences,
    createdAt: run.createdAt,
  };
}

/** 安全读写 localStorage（私有窗口 / 被禁用时静默回退到内存模式）。 */
function storage() {
  try {
    const s = window.localStorage;
    s.getItem('__test__');
    return s;
  } catch {
    return new Map(); // in-memory fallback, non-persistent
  }
}

export class MockComicGenerationAPI extends ComicGenerationAPI {
  constructor() {
    super();
    this.runs = new Map();
    this.scenario = 'success';
    this._store = storage();
    this._load();
    this._seed();
  }

  setScenario(value) { this.scenario = value; }

  /* ---------- persistence ---------- */

  _key() { return `${APP_CONFIG.storageKey}.runs`; }

  _meta(run) {
    // 不序列化 result / previewPages —— 它们可由 resultFor(run) 确定性重建，体积小很多。
    return {
      runId: run.runId, title: run.title, fileName: run.fileName,
      prompt: run.prompt, preferences: run.preferences,
      status: run.status, stage: run.stage, progress: run.progress,
      current: run.current, total: run.total, message: run.message,
      createdAt: run.createdAt, availablePages: run.availablePages,
    };
  }

  _persist() {
    try {
      const list = [...this.runs.values()].map((r) => this._meta(r)).slice(-12);
      this._store.setItem(this._key(), JSON.stringify(list));
    } catch { /* 忽略写入失败（隐私模式限流等） */ }
  }

  _load() {
    try {
      const raw = this._store.getItem?.(this._key());
      if (!raw) return;
      const list = JSON.parse(raw);
      for (const m of list) {
        if (!m || !m.runId) continue;
        // 页面刷新后内存中的 timer 已丢失，RUNNING 任务无法继续推进 → 收敛为已取消。
        if (m.status === 'RUNNING') {
          m.status = 'CANCELLED';
          m.message = '生成已中断（页面刷新导致）';
        }
        this.runs.set(m.runId, { ...m, result: null, previewPages: null });
      }
    } catch { /* 忽略损坏数据 */ }
  }

  /* ---------- API ---------- */

  async createGeneration(input) {
    const runId = `demo-${Date.now()}`;
    const run = {
      runId,
      title: (input.file?.name || '未命名漫画').replace(/\.txt$/i, '') || '未命名漫画',
      fileName: input.file?.name || '未命名漫画',
      prompt: input.prompt || '',
      preferences: input.preferences || {},
      status: 'RUNNING', stage: GENERATION_STAGES[0], progress: 4, current: 0, total: 12,
      message: '正在理解你的故事', createdAt: new Date().toISOString(), availablePages: 0,
      scenario: this.scenario, result: null, previewPages: null,
    };
    this.runs.set(runId, run);
    this._persist();
    this._advance(run);
    return structuredClone(this._decorate(run));
  }

  _decorate(run) {
    if (!run.previewPages) run.previewPages = resultFor(run).pages;
    return run;
  }

  async _advance(run) {
    const messages = ['正在理解故事脉络', '正在整理人物与世界', '正在规划漫画结构', '正在设计分镜', '正在绘制漫画页面', '正在进行漫画排版', '正在完成作品', '你的漫画完成了'];
    for (let i = 0; i < GENERATION_STAGES.length; i++) {
      await wait(i < 4 ? 650 : 900);
      if (run.status !== 'RUNNING') return;
      if (run.scenario === 'failure' && GENERATION_STAGES[i] === 'IMAGE_GENERATION') {
        Object.assign(run, { status: 'FAILED', stage: 'IMAGE_GENERATION', message: '绘制漫画时遇到问题，请重新尝试。', errorCode: 'DEMO_DRAWING_FAILED' });
        this._persist();
        return;
      }
      run.stage = GENERATION_STAGES[i];
      run.progress = Math.min(100, Math.round(((i + 1) / GENERATION_STAGES.length) * 100));
      run.message = messages[i];
      if (i >= 4) {
        run.availablePages = Math.min(12, (i - 3) * 4);
        run.current = run.availablePages;
      }
      this._persist();
    }
    run.status = 'COMPLETED';
    run.result = resultFor(run);
    this._persist();
  }

  async getGeneration(id) {
    await wait(60);
    const run = this.runs.get(id);
    if (!run) throw new Error('作品不存在');
    return structuredClone(this._decorate(run));
  }

  async getGenerationResult(id) {
    const run = this.runs.get(id);
    if (!run) throw new Error('作品不存在');
    if (run.status === 'RUNNING') throw new Error('作品仍在生成');
    run.result = resultFor(run); // 确定性重建，兼容 localStorage 恢复后的实例
    return structuredClone(run.result);
  }

  async listGenerations() {
    return [...this.runs.values()]
      .map((x) => structuredClone(this._decorate(x)))
      .sort((a, b) => b.createdAt.localeCompare(a.createdAt));
  }

  async cancelGeneration(id) {
    const run = this.runs.get(id);
    if (run?.status === 'RUNNING') Object.assign(run, { status: 'CANCELLED', message: '生成已取消' });
    this._persist();
    return structuredClone(run || { runId: id, status: 'CANCELLED' });
  }

  async retryGeneration(id) {
    const old = this.runs.get(id);
    return this.createGeneration({ file: { name: old?.fileName || '未命名漫画' }, prompt: old?.prompt || '', preferences: old?.preferences || {} });
  }

  async downloadComic(id, format) {
    await this.getGenerationResult(id);
    return { demo: true, format, message: `Demo 模式暂不提供真实 ${format.toUpperCase()} 下载` };
  }

  /* ---------- 内置示例项目 ---------- */

  _seed() {
    if (this.runs.has('demo-rain-night')) return;
    const run = {
      runId: 'demo-rain-night', title: '雨夜来客', fileName: '雨夜来客.txt',
      prompt: '电影写实风格，悬疑氛围，人物保持一致。',
      preferences: { style: '电影写实', aspectRatio: 'portrait', readingDirection: 'paged', length: '12页', dialogueDensity: '适中', pacing: '电影节奏' },
      status: 'COMPLETED', stage: 'COMPLETED', progress: 100, current: 12, total: 12,
      message: '你的漫画完成了', createdAt: new Date(Date.now() - 86400000).toISOString(),
      availablePages: 12, scenario: this.scenario, result: null, previewPages: null,
    };
    this.runs.set(run.runId, run);
    this._persist();
  }
}
