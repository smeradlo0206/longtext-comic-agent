export class GenerationStore extends EventTarget {
  constructor(api){super();this.api=api;
    const saved=this._loadDraft();
    this.state={view:'home',run:null,result:null,readerPage:0,file:null,fileName:null,fileSize:null,prompt:saved.prompt,preferences:saved.preferences};}
  _draftKey(){return 'huijuan.comic.draft';}
  _loadDraft(){try{const raw=localStorage.getItem(this._draftKey());if(raw)return JSON.parse(raw);}catch{/* ignore */}const preferences={style:'电影写实',aspectRatio:'portrait',readingDirection:'paged',length:'12页',dialogueDensity:'适中',pacing:'电影节奏'};return {prompt:'',preferences};}
  _saveDraft(){try{localStorage.setItem(this._draftKey(),JSON.stringify({prompt:this.state.prompt,preferences:this.state.preferences}));}catch{/* ignore */}}
  set(patch){Object.assign(this.state,patch);if(patch.prompt!==undefined||patch.preferences!==undefined)this._saveDraft();this.dispatchEvent(new Event('change'));}
  async start(input){const run=await this.api.createGeneration(input);this.set({run,result:null,view:'workspace'});this._poll(run.runId);}
  async _poll(id){while(this.state.run?.runId===id&&this.state.run.status==='RUNNING'){await new Promise(r=>setTimeout(r,250));const run=await this.api.getGeneration(id);this.set({run});if(run.status==='COMPLETED'){this.set({result:await this.api.getGenerationResult(id),view:'result'});}}}
  async cancel(){this.set({run:await this.api.cancelGeneration(this.state.run.runId)});}
  async retry(){const run=await this.api.retryGeneration(this.state.run.runId);this.set({run,result:null,view:'workspace'});this._poll(run.runId);}
  async openResult(id){this.set({run:await this.api.getGeneration(id),result:await this.api.getGenerationResult(id),view:'result'});}
}
