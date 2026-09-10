import './style.css';
import {setupPreview} from './preview';
import {setupUpdates} from './update';
type Job={attempt?:number;nextRetryAt?:number;attemptHistory?:{attempt:number;error:{message:string}}[];created:number;jobId:string;seq:number;state:string;title:string;url:string;mode:string;quality:string;progress?:number;speed?:number;eta?:number;error?:{message:string;code:string};result?:{path:string;size:number;container:string;duration:number}};
const icon=(path:string)=>`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${path}</svg>`;
const down=icon('<path d="M12 3v12m-5-5 5 5 5-5M4 16v4h16v-4"/>');
const settings=icon('<path d="M4 7h16M4 17h16"/><circle cx="9" cy="7" r="3" fill="currentColor"/><circle cx="15" cy="17" r="3" fill="currentColor"/>');
const link=icon('<path d="m10 13 4-4m-6 6-2 2a4 4 0 0 1-6-6l4-4m10 2 2-2a4 4 0 0 1 6 6l-4 4" transform="translate(2 0) scale(.85)"/>');
const app=document.querySelector<HTMLElement>('#app')!;
app.innerHTML=`
<header><div class="brand"><span class="brand-mark">${down}</span><div>stash<span class="brand-local">LOCAL</span></div></div><button class="icon-button" id="settings-toggle" aria-label="설정 열기" title="설정">${settings}</button></header>
<div class="connection-row"><span class="dot" id="status-dot"></span><span id="connection">연결 확인 중…</span><button id="reconnect" class="text-button" hidden>다시 연결</button></div>
<section class="intro"><p class="eyebrow">YOUR LINKS. YOUR LIBRARY.</p><h1>좋은 콘텐츠를,<br><span>내 공간에.</span></h1><p class="intro-copy">주소를 붙여넣으면 내 PC에 바로 저장해요.</p></section>
<form id="download-form">
<label for="url" class="label">다운로드 주소</label>
<div class="url-wrap">${link}<input id="url" type="url" required maxlength="8192" placeholder="https://…" autocomplete="off" spellcheck="false" aria-describedby="url-help"></div>
<div class="input-tools"><span id="url-help">개별 영상 또는 미디어 파일 주소</span><button type="button" id="current-tab" class="text-button">현재 탭 가져오기 ↗</button></div>
<button id="analyze" type="button" class="secondary">주소 분석</button>
<section id="preview" class="preview-card" hidden aria-live="polite"><img id="preview-image" alt="영상 미리보기" hidden><span id="preview-placeholder" role="img" aria-label="썸네일 미제공">▷</span><h2 id="preview-title"></h2><p id="preview-meta"></p><p id="preview-quality"></p><p id="preview-size"></p></section>
<div class="options"><label>형식<select id="mode"><option value="mp4">MP4 · 호환 영상</option><option value="video">원본 유지 · 영상</option><option value="audio">오디오 · MP3</option></select></label><label>화질<select id="quality"><option value="best">최고 화질</option><option value="1080">최대 1080p</option><option value="720">최대 720p</option><option value="480">최대 480p</option></select></label></div>
<button id="download" class="primary" type="button" disabled>${down}<span>다운로드</span><kbd>↓</kbd></button>
<p class="error" id="error" role="alert" hidden></p>
</form>
<section id="settings" class="settings-card" hidden><h2>저장 설정</h2><label class="label" for="folder">저장 폴더 · 절대 경로</label><input id="folder" placeholder="기본: ~/Downloads/yt-down-interface"><p>설정은 이 브라우저에 저장됩니다.<br>파일과 다운로드 처리는 내 PC에서만 이루어집니다.</p><button id="diagnose" class="secondary">엔진 진단</button><pre id="diagnostics" hidden></pre><h2>엔진 업데이트</h2><div class="update-actions"><button id="check-update" class="secondary">업데이트 확인</button><button id="install-update" class="secondary">검증 버전 설치 · 재설치</button><button id="rollback-update" class="secondary">이전 엔진으로 복원</button></div><p id="update-status" role="status"></p><p>다운로드·분석·재생을 종료한 뒤 실행하세요. 설치 중에는 잠시 연결이 끊깁니다.<br>이 기능은 로컬 엔진만 갱신합니다. 확장은 검증된 로컬 빌드 후 chrome://extensions에서 새로고침하세요.</p></section>
<section class="queue"><div class="section-heading"><h2>다운로드 <span id="job-count">0</span></h2><span class="queue-caption" id="queue-caption">준비됐어요</span></div><div class="tabs" role="tablist" aria-label="작업 필터"><button class="selected" id="filter-all" role="tab" aria-selected="true">전체</button><button id="filter-active" role="tab" aria-selected="false">진행 중</button><button id="filter-completed" role="tab" aria-selected="false">완료</button><button id="filter-failed" role="tab" aria-selected="false">실패</button></div><label class="label" for="history-search">기록 검색 · 제목/사이트</label><input id="history-search" maxlength="200" placeholder="전체 기록에서 검색"><div class="history-actions"><label><input type="checkbox" id="select-page"> 현재 목록 선택</label><button id="delete-selected" class="text-button" disabled>선택 삭제</button><button id="delete-failed" class="text-button">실패 기록 삭제</button></div><p id="history-result" role="status"></p><div id="jobs" aria-live="polite"></div><div class="empty" id="empty"><div class="empty-icon">${down}</div><h3>첫 번째 링크를 기다리고 있어요</h3><p>저장한 콘텐츠와 진행 상태를<br>여기서 확인할 수 있어요.</p></div><button id="more" class="secondary" hidden>이전 작업 더 보기</button></section>
<footer><span class="local-shield">◇</span> 내 PC에 저장 · 서버 업로드 없음 <span class="version">v0.2</span></footer>
<section class="install-note" id="install-note" hidden><strong>로컬 엔진을 연결해 주세요</strong><p>프로젝트에서 <code>npm run install:host</code>를 실행한 뒤 다시 연결하세요. 설치된 Python·FFmpeg가 필요합니다.</p></section>`;
const $=<T extends HTMLElement=HTMLElement>(id:string)=>document.getElementById(id) as T;
const url=$<HTMLInputElement>('url'), mode=$<HTMLSelectElement>('mode'), quality=$<HTMLSelectElement>('quality'), folder=$<HTMLInputElement>('folder');
const jobs=new Map<string,Job>();const selected=new Set<string>();let filter='all',nextCursor:any=null,total=0,online=false,queryGeneration=0,snapshotGeneration=0,storagePaused=false;let refreshTimer:ReturnType<typeof setTimeout>|undefined;
const keepalive=chrome.runtime.connect({name:'panel'});
window.addEventListener('unload',()=>keepalive.disconnect());
function error(message='') {$('error').textContent=message;$('error').hidden=!message;}
function connection(connected:boolean) {
  online=connected;$('connection').textContent=connected?'로컬 엔진 연결됨':'로컬 엔진 연결 필요';$('status-dot').classList.toggle('online',connected);$('reconnect').hidden=connected;$('install-note').hidden=connected;
}
async function request(type:string,payload:object={},requestId:string=crypto.randomUUID()) {
  const response=await chrome.runtime.sendMessage({nativeRequest:{protocolVersion:1,requestId,type,payload}});
  if (!response?.ok) {
    if (response?.error?.code==='HOST_DISCONNECTED') connection(false);
    throw new Error(response?.error?.message || '로컬 엔진에 연결할 수 없습니다.');
  }
  connection(true);return response.payload;
}
const deleted=new Set<string>();
function removeJob(id:string) {
  if(deleted.has(id))return;
  deleted.add(id);jobs.delete(id);selected.delete(id);total=Math.max(0,total-1);
  render();
}
function merge(job:Job) {if (!deleted.has(job.jobId)&&(!jobs.has(job.jobId) || jobs.get(job.jobId)!.seq<job.seq)) jobs.set(job.jobId,job);}
async function refresh(cursor:any=null) {
  const generation=queryGeneration,read=++snapshotGeneration;
  const snapshot=await request('getSnapshot',{filter,search:$<HTMLInputElement>('history-search').value,cursor});
  if(generation!==queryGeneration||read!==snapshotGeneration)return;
  if(cursor===null)jobs.clear();
  for(const job of snapshot.jobs)merge(job);
  storagePaused=!!snapshot.storageError;if(snapshot.storageError)error(snapshot.storageError.message);
  total=snapshot.total;nextCursor=snapshot.nextCursor;render();
}
function scheduleRefresh(){clearTimeout(refreshTimer);refreshTimer=setTimeout(()=>void refresh().catch(e=>error(e.message)),150);}
async function initialize() {jobs.clear();total=0;nextCursor=null;render();try {await request('hello');await refresh();} catch {connection(false);}}
const terminal=['completed','failed','cancelled','interrupted'];
const names:Record<string,string>={retry_wait:'자동 재시도 대기',queued:'대기 중',inspecting:'분석 중',downloading:'다운로드 중',postprocessing:'미디어 변환 중',verifying:'파일 검증 중',completed:'완료',failed:'실패',cancelled:'취소됨',interrupted:'중단됨'};
const bytes=(value:number)=>value>=1048576?`${(value/1048576).toFixed(1)} MB`:`${Math.round(value/1024)} KB`;
function render() {
  const all=[...jobs.values()].sort((a,b)=>b.created-a.created);
  const active=all.filter(j=>!terminal.includes(j.state));
  $('job-count').textContent=String(Math.max(total,jobs.size));$('queue-caption').textContent=storagePaused?'기록 저장 오류 · 대기열 멈춤':active.length?`${active.length}개 진행 중`:'내 PC에 안전하게 저장';
  const visible=all.filter(j=>filter==='all'||(filter==='completed'?j.state==='completed':filter==='failed'?j.state==='failed':!terminal.includes(j.state)));
  const container=$('jobs');container.replaceChildren();$('empty').hidden=!!visible.length;$('more').hidden=nextCursor===null;
  $<HTMLButtonElement>('delete-selected').disabled=selected.size===0;$('delete-selected').textContent=`선택 삭제 (${selected.size})`;
  const selectable=visible.filter(j=>terminal.includes(j.state));$<HTMLInputElement>('select-page').checked=!!selectable.length&&selectable.every(j=>selected.has(j.jobId));
  for (const job of visible) {
    const card=document.createElement('article');card.className='job';card.dataset.jobId=job.jobId;card.dataset.state=job.state;
    const top=document.createElement('div');top.className='job-top';
    if(terminal.includes(job.state)){const check=document.createElement('input');check.type='checkbox';check.checked=selected.has(job.jobId);check.setAttribute('aria-label',job.title+' 기록 선택');check.addEventListener('change',()=>{check.checked?selected.add(job.jobId):selected.delete(job.jobId);render();});top.append(check);}
    const symbol=document.createElement('span');symbol.className='media-symbol';symbol.textContent=job.mode==='audio'?'♫':'▷';
    const detail=document.createElement('div');detail.className='job-detail';
    const title=document.createElement('h3');title.textContent=job.title;title.title=job.title;
    const meta=document.createElement('p');let host='';try {host=new URL(job.url).hostname;}catch{}
    meta.textContent=[host,job.mode==='audio'?'MP3':job.quality==='best'?'최고 화질':`${job.quality}p 이하`,job.mode==='audio'?undefined:job.result?.container.toUpperCase()].filter(Boolean).join(' · ');
    detail.append(title,meta);top.append(symbol,detail);card.append(top);
    const state=document.createElement('div');state.className='job-status '+job.state;
    const label=document.createElement('span');label.textContent=(names[job.state]||job.state)+(job.attempt&&job.attempt>1?` · ${job.attempt}/4회`:'');
    if(job.state==='retry_wait'&&job.nextRetryAt){label.dataset.retryAt=String(job.nextRetryAt);label.dataset.attempt=String(job.attempt);}
    const metric=document.createElement('span');metric.textContent=job.state==='completed'&&job.result?bytes(job.result.size):['downloading','postprocessing'].includes(job.state)?[job.progress!=null?`${Math.round(job.progress)}%`:null,job.speed?`${bytes(job.speed)}/s`:null].filter(Boolean).join(' · '):'';
    state.append(label,metric);card.append(state);
    if (!terminal.includes(job.state)) {
      const bar=document.createElement('div');bar.className='progress';bar.setAttribute('role','progressbar');bar.setAttribute('aria-label','다운로드 진행률');
      const fill=document.createElement('span');fill.style.width=`${job.progress??12}%`;if(job.progress==null)fill.className='indeterminate';else bar.setAttribute('aria-valuenow',String(Math.round(job.progress)));bar.append(fill);card.append(bar);
    }
    if (job.error) {const note=document.createElement('p');note.className='job-error';note.textContent=job.error.message;card.append(note);}
    if(job.attemptHistory?.length){const history=document.createElement('details');const summary=document.createElement('summary');summary.textContent=`시도 이력 (${job.attemptHistory.length})`;history.append(summary);for(const entry of job.attemptHistory){const note=document.createElement('p');note.textContent=`${entry.attempt}회: ${entry.error.message}`;history.append(note);}card.append(history);}
    if (job.result) {const path=document.createElement('p');path.className='file-path';path.textContent=job.result.path;path.title=job.result.path;card.append(path);}
    const actions=document.createElement('div');actions.className='job-actions';
    const button=document.createElement('button');button.className='text-button';
    const command=job.state==='completed'?'revealFile':terminal.includes(job.state)?'retry':'cancel';
    button.textContent=command==='revealFile'?'폴더에서 보기 ↗':command==='retry'?'다시 시도':'취소';
    button.addEventListener('click',async()=>{button.disabled=true;try{await request(command,{jobId:job.jobId});await refresh();}catch(e){error(String((e as Error).message));}finally{button.disabled=false;}});
    actions.append(button);
    if(job.state==='completed'){
      const play=document.createElement('button');play.className='text-button';play.textContent='재생 ▶';
      play.addEventListener('click',()=>void chrome.tabs.create({url:chrome.runtime.getURL('player.html')+'?jobId='+encodeURIComponent(job.jobId)}));actions.append(play);
    }
    if(terminal.includes(job.state)) {
      const remove=document.createElement('button');remove.className='text-button';remove.textContent='기록 삭제';
      remove.title='목록의 기록만 삭제합니다. 저장된 파일은 유지됩니다.';
      remove.addEventListener('click',async()=>{
        remove.disabled=true;error();
        try{await request('deleteJob',{jobId:job.jobId});removeJob(job.jobId);await refresh();}
        catch(e){error((e as Error).message);}finally{remove.disabled=false;}
      });
      actions.append(remove);
    }
    card.append(actions);container.append(card);
  }
}
chrome.runtime.onMessage.addListener(message=>{
  if(message.nativeDisconnected)connection(false);
  if(message.nativeEvent?.type==='engineError'){storagePaused=true;error(message.nativeEvent.payload.message);render();}
  if(message.nativeEvent?.type==='jobDeleted'){removeJob(message.nativeEvent.payload.jobId);scheduleRefresh();}
  if(message.nativeEvent?.type==='jobUpdated'){
    const job=message.nativeEvent.payload,previous=jobs.get(job.jobId);
    if(previous){
      const visibleFields=['state','title','progress','speed','error','result','attempt','nextRetryAt','attemptHistory'] as const;
      const changed=visibleFields.some(key=>JSON.stringify(previous[key])!==JSON.stringify(job[key]));
      merge(job);if(changed)render();
    }
    if(!previous||previous.state!==job.state)scheduleRefresh();
  }
});
const preview=setupPreview({request,refresh,error});
$('current-tab').addEventListener('click',async()=>{
  const [tab]=await chrome.tabs.query({active:true,currentWindow:true});
  if(tab?.url?.startsWith('http')){url.value=tab.url;preview.invalidate();url.focus();error();}else error('저장할 영상이 있는 웹페이지에서 확장을 열어 주세요.');
});
$('settings-toggle').addEventListener('click',()=>{$('settings').hidden=!$('settings').hidden;});
$('reconnect').addEventListener('click',()=>void initialize());
$('more').addEventListener('click',()=>{if(nextCursor!==null)refresh(nextCursor).catch(e=>error(e.message));});
setupUpdates({request,refresh});
for (const value of ['all','active','completed','failed']) $('filter-'+value).addEventListener('click',()=>{
  filter=value;for(const v of ['all','active','completed','failed']){$('filter-'+v).classList.toggle('selected',v===value);$('filter-'+v).setAttribute('aria-selected',String(v===value));}queryGeneration++;selected.clear();jobs.clear();nextCursor=null;void refresh().catch(e=>error(e.message));
});
function save(){quality.disabled=mode.value==='audio';void chrome.storage.local.set({settings:{mode:mode.value,quality:quality.value,folder:folder.value}});}
for(const input of [mode,quality,folder])input.addEventListener('change',save);
void chrome.storage.local.get('settings').then(({settings})=>{const s=settings as {mode?:string;quality?:string;folder?:string}|undefined;if(s){mode.value=s.mode||'video';quality.value=s.quality||'best';folder.value=s.folder||'';quality.disabled=mode.value==='audio';}});
void initialize();

let searchTimer:ReturnType<typeof setTimeout>|undefined;
$('history-search').addEventListener('input',()=>{queryGeneration++;selected.clear();clearTimeout(searchTimer);searchTimer=setTimeout(()=>void refresh().catch(e=>error(e.message)),200);});
$('select-page').addEventListener('change',()=>{const checked=$<HTMLInputElement>('select-page').checked;for(const job of jobs.values())if(terminal.includes(job.state)){checked?selected.add(job.jobId):selected.delete(job.jobId);}render();});
async function deleteBatch(ids:string[]) {
  let removed=0,failed=0;
  for(let i=0;i<ids.length;i+=100){const result=await request('deleteJobs',{jobIds:ids.slice(i,i+100)});for(const id of result.deleted)removeJob(id);removed+=result.deleted.length;failed+=result.errors.length;}
  $('history-result').textContent=`${removed}개 기록 삭제${failed?` · ${failed}개 삭제하지 못함 (진행 상태 확인)`:''}. 영상 파일은 유지됩니다.`;
  selected.clear();await refresh();
}
$('delete-selected').addEventListener('click',async()=>{const ids=[...selected];if(!ids.length||!confirm(`${ids.length}개 기록을 삭제할까요? 영상 파일은 유지됩니다.`))return;try{await deleteBatch(ids);}catch(e){error((e as Error).message);}});
$('delete-failed').addEventListener('click',async()=>{
  const button=$<HTMLButtonElement>('delete-failed');button.disabled=true;
  try{const search=$<HTMLInputElement>('history-search').value;const ids:string[]=[];let cursor:any=null;do{const page=await request('getSnapshot',{filter:'failed',search,cursor});ids.push(...page.jobs.map((j:Job)=>j.jobId));cursor=page.nextCursor;}while(cursor);
  if(!ids.length){$('history-result').textContent='검색 조건에 맞는 실패 기록이 없습니다.';return;}
  if(confirm(`현재 검색 조건${search?` “${search}”`:''}의 실패 기록 ${ids.length}개를 삭제할까요? 영상 파일은 유지됩니다.`))await deleteBatch(ids);
  }catch(e){error((e as Error).message);}finally{button.disabled=false;}
});

setInterval(()=>{for(const label of document.querySelectorAll<HTMLElement>('[data-retry-at]')){const seconds=Math.max(0,Math.ceil(Number(label.dataset.retryAt)-Date.now()/1000));label.textContent=`자동 재시도 대기 · ${label.dataset.attempt}/4회 · ${seconds}초 후`; }},1000);
