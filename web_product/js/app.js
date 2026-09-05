import { APP_CONFIG, saveConnection } from './config.js';
import { MockComicGenerationAPI } from './api/mock-comic-generation-api.js';
import { RealComicGenerationAPI } from './api/real-comic-generation-api.js';
import { GenerationStore } from './state/generation-store.js';
import { homeView, libraryView, modalView, readerView, regenerateModal, resultView, workspaceView } from './components/ui.js';

const API_MODE = APP_CONFIG.apiMode;
// 真实后端地址集中在 config.js；real 模式下此处注入给 adapter 使用。
if (API_MODE === 'real') window.__COMIC_API_BASE_URL__ = APP_CONFIG.apiBaseUrl;
const api = API_MODE === 'real' ? new RealComicGenerationAPI() : new MockComicGenerationAPI();
const store=new GenerationStore(api);
const app=document.querySelector('#app'),modalRoot=document.querySelector('#modal-root'),toastRoot=document.querySelector('#toast-root');
let library=[];
let submitting=false;
window.addEventListener('unhandledrejection', e=>{e.preventDefault();toast(e.reason?.message||'操作失败，请重试','error');});
if(API_MODE==='real') document.querySelector('.demo-switch').hidden=true;
function toast(message,type='info'){const node=document.createElement('div');node.className=`toast ${type}`;node.textContent=message;toastRoot.append(node);setTimeout(()=>node.remove(),2800);}
async function render(){const {view,run,result,readerPage}=store.state;if(view==='home')app.innerHTML=homeView(store.state);else if(view==='workspace')app.innerHTML=workspaceView(run);else if(view==='result')app.innerHTML=resultView(result);else if(view==='reader')app.innerHTML=readerView(result,readerPage);else if(view==='library'){library=await api.listGenerations();app.innerHTML=libraryView(library);}bindView();}
store.addEventListener('change',render);render();

function bindView(){const zone=document.querySelector('#upload-zone'),input=document.querySelector('#story-file');if(zone&&input){input.addEventListener('change',()=>chooseFile(input.files[0]));['dragenter','dragover'].forEach(name=>zone.addEventListener(name,e=>{e.preventDefault();zone.classList.add('dragging')}));['dragleave','drop'].forEach(name=>zone.addEventListener(name,e=>{e.preventDefault();zone.classList.remove('dragging')}));zone.addEventListener('drop',e=>chooseFile(e.dataTransfer.files[0]));}
  document.querySelectorAll('[data-template]').forEach(button=>button.addEventListener('click',()=>{const prompt=document.querySelector('#prompt');prompt.value={电影写实:'电影感强烈，光影写实，角色外观始终保持一致。',日系漫画:'日系漫画风格，细腻情绪，大量表情特写。',轻松喜剧:'明快轻松的喜剧风格，节奏活泼，突出有趣互动。',悬疑惊悚:'低饱和悬疑氛围，强化阴影、未知感与线索细节。',热血动作:'热血动作风格，动态构图，关键冲突使用更多分镜。'}[button.dataset.template];store.state.prompt=prompt.value;}));
  document.querySelector('#generation-form')?.addEventListener('submit',async e=>{e.preventDefault();if(!store.state.file)return toast('请先选择故事文件','error');const form=new FormData(e.currentTarget),prompt=document.querySelector('#prompt').value.trim();if(!prompt)return toast('请填写创作要求','error');const preferences={...store.state.preferences};['style','aspectRatio','readingDirection','length','dialogueDensity','pacing'].forEach(k=>preferences[k]=form.get(k)||preferences[k]);store.set({prompt,preferences});if(submitting)return;submitting=true;const button=document.querySelector('#start-button');button.disabled=true;button.textContent='正在提交…';try{await store.start({file:store.state.file,prompt,preferences});}catch(error){toast(error.message,'error');}finally{submitting=false;if(button.isConnected){button.disabled=false;button.textContent='开始创作';}}});
  const readerImage=document.querySelector('[data-reader-image]');readerImage?.addEventListener('load',e=>e.currentTarget.parentElement.classList.remove('skeleton'));readerImage?.addEventListener('error',e=>{e.currentTarget.parentElement.classList.remove('skeleton');e.currentTarget.parentElement.innerHTML='<div class="image-error"><b>该页加载失败</b><button class="secondary" data-action="reload-reader">重新加载</button></div>';});
}
function chooseFile(file){const error=document.querySelector('#file-error');if(error)error.textContent='';if(!file)return;const ok=file.name.toLowerCase().endsWith('.txt');if(!ok){if(error)error.textContent='暂时只支持 TXT 文件';toast('暂时只支持 TXT 文件','error');return;}store.set({file,fileName:file.name,fileSize:file.size});}
document.addEventListener('click',e=>{if(e.target.closest('[data-action="reload-reader"]'))render();});
document.addEventListener('click',async e=>{const target=e.target.closest('[data-action],[data-page],[data-open-run],[data-download]');if(!target)return;const action=target.dataset.action;if(action==='home')store.set({view:'home'});if(action==='library')store.set({view:'library'});if(action==='remove-file')store.set({file:null});if(target.dataset.openRun)try{await store.openResult(target.dataset.openRun);}catch(err){toast(err.message,'error');}if(target.dataset.page!==undefined)store.set({readerPage:Number(target.dataset.page),view:'reader'});if(action==='read')store.set({readerPage:0,view:'reader'});if(action==='close-reader')store.set({view:'result'});if(action==='previous')movePage(-1);if(action==='next')movePage(1);if(action==='fit')document.querySelector('.reader-image')?.classList.toggle('natural');if(action==='fullscreen')toggleFullscreen();if(action==='confirm-cancel')modalRoot.innerHTML=modalView();if(action==='cancel-now'){modalRoot.innerHTML='';await store.cancel();toast('生成已取消');}if(action==='close-modal')modalRoot.innerHTML='';if(action==='retry'){modalRoot.innerHTML='';await store.retry();}if(action==='restart')await store.retry();if(action==='edit'){modalRoot.innerHTML='';store.set({view:'home'});}if(action==='regenerate')modalRoot.innerHTML=regenerateModal();if(target.dataset.download){const out=await api.downloadComic(store.state.result.runId,target.dataset.download);toast(out.message);}});
document.addEventListener('change',e=>{if(e.target.matches('[data-action="jump"]'))store.set({readerPage:Number(e.target.value)});});
document.addEventListener('keydown',e=>{if(store.state.view!=='reader')return;if(e.key==='ArrowLeft')movePage(-1);if(e.key==='ArrowRight')movePage(1);if(e.key==='Escape'&&!document.fullscreenElement)store.set({view:'result'});});
function movePage(delta){const max=store.state.result.pages.length-1;store.set({readerPage:Math.max(0,Math.min(max,store.state.readerPage+delta))});}
  async function toggleFullscreen(){const reader=document.querySelector('#reader');if(!reader)return;try{if(document.fullscreenElement){await document.exitFullscreen();}else{await reader.requestFullscreen();}}catch{toast('浏览器不支持全屏','error');}}
document.querySelector('#demo-scenario').addEventListener('change',e=>{if('setScenario' in api)api.setScenario(e.target.value);toast(`下一次生成将演示${e.target.value==='failure'?'失败':'成功'}流程`);});
window.__COMIC_APP__={API_MODE,api,store};
document.querySelector('#mode-notice').textContent=API_MODE==='real'
  ? '真实服务模式 · 文件将上传到已配置的 API，生图由服务器执行'
  : '演示模式 · 展示内置示例图片，不根据上传文本生图，也不会上传文件';
const connectionDialog=document.querySelector('#connection-dialog');
document.querySelector('#connection-settings').addEventListener('click',()=>{
  document.querySelector('#api-address').value=APP_CONFIG.apiBaseUrl;
  document.querySelector('#connection-error').textContent='';
  connectionDialog.showModal();
});
document.querySelector('#close-connection').addEventListener('click',()=>connectionDialog.close());
document.querySelector('#use-demo').addEventListener('click',()=>{
  saveConnection('mock'); location.reload();
});
document.querySelector('#connection-form').addEventListener('submit',async event=>{
  event.preventDefault();
  const error=document.querySelector('#connection-error');
  const button=event.currentTarget.querySelector('[type="submit"]');
  button.disabled=true; error.textContent='正在检查 API 和参考素材配置…';
  try {
    const address=document.querySelector('#api-address').value.trim();
    const url=new URL(address);
    if(url.protocol!=='https:' && !(url.protocol==='http:' && ['localhost','127.0.0.1','[::1]'].includes(url.hostname))) {
      throw new Error('请使用 HTTPS，或本机 http://127.0.0.1:8000 地址');
    }
    if(url.username||url.password||url.search||url.hash) throw new Error('API 地址不能包含账号、密码、查询参数或片段');
    await new RealComicGenerationAPI(address)._request('/product-capabilities');
    saveConnection('real',address); location.reload();
  } catch(cause) { error.textContent=cause.message; }
  finally { button.disabled=false; }
});
if(API_MODE==='real') {
  const status=document.querySelector('#service-status');
  status.textContent='正在连接生成服务…';
  api._request('/product-capabilities').then(info=>{
    status.textContent='已连接生成服务 · 参考素材：'+info.referenceNames.join('、');
  }).catch(error=>{status.textContent=error.message;});
}
