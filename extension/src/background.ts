const HOST = 'io.stashlocal.downloader';
type Reply = {ok:boolean; payload?:any; error?:{code:string; message:string; retryable?:boolean}; requestId?:string};
let port: chrome.runtime.Port | undefined;
let panels = 0;
let activeCount = 0;
let storagePaused=false;
let idleTimer: ReturnType<typeof setTimeout> | undefined;
const activeJobs = new Set<string>();
const pending = new Map<string,{resolve:(value:Reply)=>void; timer:ReturnType<typeof setTimeout>}>();
const notify = (message:unknown) => { chrome.runtime.sendMessage(message).catch(()=>{}); };
function idle() {
  clearTimeout(idleTimer);
  if (panels || (!storagePaused&&activeCount) || pending.size || !port) return;
  idleTimer = setTimeout(()=>{
    if (panels || (!storagePaused&&activeCount) || pending.size) return;
    const old = port; port = undefined; old?.disconnect();
  },15000);
}
function connect() {
  if (port) return port;
  const current = chrome.runtime.connectNative(HOST); port = current;
  current.onMessage.addListener(message => {
    if(message.type==='engineError'&&message.payload?.code==='DB_WRITE_FAILED')storagePaused=true;
    if(message.payload?.storageError!==undefined)storagePaused=!!message.payload.storageError;
    if (message.type === 'jobUpdated') {
      if (['completed','failed','cancelled','interrupted'].includes(message.payload.state)) activeJobs.delete(message.jobId);
      else activeJobs.add(message.jobId);
      activeCount = activeJobs.size;
    }
    if (Array.isArray(message.payload?.activeJobIds)){activeJobs.clear();for(const id of message.payload.activeJobIds)activeJobs.add(id);}
    if (message.payload?.activeCount !== undefined) activeCount = message.payload.activeCount;
    const item = pending.get(message.requestId);
    if (item) {clearTimeout(item.timer); pending.delete(message.requestId); item.resolve(message);}
    notify({nativeEvent:message});
    if(message.ok&&(message.payload?.updateHandoff||message.payload?.updateReconnect)){setTimeout(()=>{current.disconnect();if(port===current){port=undefined;notify({nativeDisconnected:'엔진 업데이트 후 다시 연결합니다.'});}},100);}
    idle();
  });
  current.onDisconnect.addListener(()=>{
    const error = chrome.runtime.lastError?.message || '로컬 엔진 연결이 종료되었습니다.';
    if (port !== current) return;
    port = undefined; activeJobs.clear(); activeCount = 0;storagePaused=false;
    for (const item of pending.values()) {clearTimeout(item.timer); item.resolve({ok:false,error:{code:'HOST_DISCONNECTED',message:error,retryable:true}});}
    pending.clear(); notify({nativeDisconnected:error});
  });
  return current;
}
chrome.runtime.onConnect.addListener(p => {
  if (!['panel','player'].includes(p.name) || p.sender?.id !== chrome.runtime.id) return;
  panels++; clearTimeout(idleTimer);
  let playbackSession:string|undefined;
  p.onMessage.addListener(m=>{if(p.name==='player'&&typeof m.sessionId==='string')playbackSession=m.sessionId;});
  p.onDisconnect.addListener(()=>{
    if(playbackSession&&port){try{port.postMessage({protocolVersion:1,requestId:crypto.randomUUID(),type:'closePlayback',payload:{sessionId:playbackSession}});}catch{}}
    panels=Math.max(0,panels-1);idle();
  });
});
chrome.runtime.onMessage.addListener((message,sender,respond)=>{
  if (!message.nativeRequest || sender.id !== chrome.runtime.id) return;
  const request = message.nativeRequest;
  if(request.type==='hello')request.payload={...request.payload,extensionVersion:chrome.runtime.getManifest().version};
  if (typeof request.requestId !== 'string' || pending.size >= 8) {
    respond({ok:false,error:{code:'BUSY',message:'잠시 후 다시 시도하세요.'}});return;
  }
  clearTimeout(idleTimer);
  const timer=setTimeout(()=>{
    const item=pending.get(request.requestId);pending.delete(request.requestId);
    item?.resolve({ok:false,error:{code:'TIMEOUT',message:'응답 시간이 초과되었습니다. 대기열 상태를 확인하세요.',retryable:true}});idle();
  },45000);
  pending.set(request.requestId,{resolve:respond,timer});
  try {connect().postMessage(request);}
  catch(e) {clearTimeout(timer);pending.delete(request.requestId);respond({ok:false,error:{code:'HOST_DISCONNECTED',message:String(e)}});}
  return true;
});
chrome.sidePanel.setPanelBehavior({openPanelOnActionClick:true}).catch(()=>{});
