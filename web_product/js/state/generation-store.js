export class GenerationStore extends EventTarget {
  constructor(api) {
    super(); this.api = api; this.pollToken = 0;
    const saved = this._loadDraft();
    this.state = { view: 'home', run: null, result: null, readerPage: 0, file: null,
      fileName: null, fileSize: null, prompt: saved.prompt, preferences: saved.preferences };
  }
  _draftKey() { return 'huijuan.comic.draft'; }
  _loadDraft() {
    try { const raw = localStorage.getItem(this._draftKey()); if (raw) return JSON.parse(raw); } catch { /* optional */ }
    return { prompt: '', preferences: { style: '电影写实', aspectRatio: 'portrait', readingDirection: 'paged', length: '12页', dialogueDensity: '适中', pacing: '电影节奏' } };
  }
  set(patch) {
    Object.assign(this.state, patch);
    if (patch.prompt !== undefined || patch.preferences !== undefined) {
      try { localStorage.setItem(this._draftKey(), JSON.stringify({ prompt: this.state.prompt, preferences: this.state.preferences })); } catch { /* optional */ }
    }
    this.dispatchEvent(new Event('change'));
  }
  async _accept(run) {
    ++this.pollToken; this.set({ run, result: null, view: 'workspace' });
    if (run.status === 'COMPLETED') await this.openResult(run.runId);
    else if (run.status === 'RUNNING') void this._poll(run.runId, this.pollToken);
  }
  async start(input) { await this._accept(await this.api.createGeneration(input)); }
  async _poll(id, token) {
    while (token === this.pollToken && this.state.run?.runId === id && this.state.run.status === 'RUNNING') {
      await new Promise(resolve => setTimeout(resolve, 2000));
      if (token !== this.pollToken) return;
      try {
        const run = await this.api.getGeneration(id);
        if (token !== this.pollToken) return;
        if (run.status === 'COMPLETED') {
          const result = await this.api.getGenerationResult(id);
          if (token !== this.pollToken) return;
          this.set({ run, result, view: 'result' });
        } else this.set({ run });
      } catch (error) {
        if (token !== this.pollToken) return;
        this.set({ run: { ...this.state.run, message: error.message + '，正在重连…' } });
      }
    }
  }
  async cancel() { const run = await this.api.cancelGeneration(this.state.run.runId); ++this.pollToken; this.set({ run }); }
  async retry() { await this._accept(await this.api.retryGeneration(this.state.run.runId)); }
  async openResult(id) {
    const run = await this.api.getGeneration(id); ++this.pollToken;
    if (run.status !== 'COMPLETED') { await this._accept(run); return; }
    this.set({ run, result: await this.api.getGenerationResult(id), view: 'result' });
  }
}
