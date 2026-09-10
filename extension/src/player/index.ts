import './style.css';
const $=<T extends HTMLElement=HTMLElement>(id:string)=>document.getElementById(id) as T;
const video=$<HTMLVideoElement>('video'),status=$('status'),seek=$<HTMLInputElement>('seek');
const jobId=new URLSearchParams(location.search).get('jobId');
const keepalive=chrome.runtime.connect({name:'player'});
let sessionId:string|undefined,sequence=0,restoring=0,closed=false,opening=false,removed=false;
const time=(n:number)=>Number.isFinite(n)?`${Math.floor(n/60)}:${Math.floor(n%60).toString().padStart(2,'0')}`:'0:00';
async function request(type:string,payload:object) {
 const result=await chrome.runtime.sendMessage({nativeRequest:{protocolVersion:1,requestId:crypto.randomUUID(),type,payload}});
 if(!result?.ok)throw new Error(result?.error?.message||'엔진에 연결할 수 없습니다.');return result.payload;
}
async function save(ended=false) {
 if(!sessionId||!Number.isFinite(video.duration)||removed||opening)return;
 const token=sessionId;
 try{await request('savePlaybackPosition',{sessionId:token,seconds:video.currentTime,seq:++sequence,ended});}
 catch(e){if(token===sessionId&&!closed)status.textContent=(e as Error).message;}
}
async function open() {
 if(opening||removed)return;opening=true;$<HTMLButtonElement>('reconnect').disabled=true;status.textContent='영상 연결 중…';
 try {
  if(sessionId)await request('closePlayback',{sessionId}).catch(()=>{});
  sessionId=undefined;video.removeAttribute('src');video.load();
  const session=await request('openPlayback',{jobId});sessionId=session.sessionId;keepalive.postMessage({sessionId});sequence=0;restoring=session.position||0;
  $('title').textContent=session.title;document.title=`${session.title} · Stash Local`;
  const streams=session.result.streams||[],v=streams.find((s:any)=>s.codec_type==='video');
  $('metadata').textContent=[session.result.container.toUpperCase(),v?`${v.width} × ${v.height}`:'오디오',time(session.result.duration),streams.some((s:any)=>s.codec_type==='audio')?'음성 포함':'무음 영상'].join(' · ');
  video.src=session.url;status.textContent=restoring?`${time(restoring)}부터 이어볼 수 있습니다.`:'재생 버튼을 누르세요.';
 }catch(e){status.textContent=(e as Error).message;}
 finally{opening=false;$<HTMLButtonElement>('reconnect').disabled=false;}
}
function update() {
 $('toggle').textContent=video.paused?'재생 ▶':'일시정지 Ⅱ';$('toggle').setAttribute('aria-label',video.paused?'재생':'일시정지');
 $('time').textContent=`${time(video.currentTime)} / ${time(video.duration)}`;
 seek.max=Number.isFinite(video.duration)?String(video.duration):'1';seek.value=String(video.currentTime);
 $('mute').textContent=video.muted?'음소거 해제':'음소거';
}
async function toggle(){try{if(video.paused)await video.play();else video.pause();}catch{status.textContent='재생을 시작하지 못했습니다. 연결과 파일 형식을 확인하세요.';}}
function jump(delta:number){if(Number.isFinite(video.duration))video.currentTime=Math.max(0,Math.min(video.duration,video.currentTime+delta));}
async function fullscreen(){try{if(document.fullscreenElement)await document.exitFullscreen();else await $('screen').requestFullscreen();}catch{status.textContent='전체화면으로 전환하지 못했습니다.';}}
video.addEventListener('loadedmetadata',()=>{if(restoring>0&&restoring<video.duration)video.currentTime=restoring;restoring=0;update();});
video.addEventListener('timeupdate',update);
video.addEventListener('play',()=>{status.textContent='재생 중';update();});
video.addEventListener('pause',()=>{update();if(!removed&&!opening){status.textContent='일시정지';void save();}});
video.addEventListener('ended',()=>{status.textContent='재생 완료';void save(true);});
video.addEventListener('seeked',()=>{update();void save();});
video.addEventListener('error',()=>{status.textContent=video.error?.code===4?'이 파일 형식은 브라우저에서 재생할 수 없습니다. MP4 호환 형식으로 다시 다운로드하세요.':video.error?.code===3?'영상 디코딩에 실패했습니다. 파일이 손상되었을 수 있습니다.':'영상 연결이 끊겼습니다. 다시 연결하세요.';});
chrome.runtime.onMessage.addListener(m=>{
 if(m.nativeDisconnected){sessionId=undefined;video.pause();status.textContent='엔진 연결이 종료되었습니다. 다시 연결하세요.';}
 if(m.nativeEvent?.type==='jobDeleted'&&m.nativeEvent.payload.jobId===jobId){removed=true;sessionId=undefined;video.pause();video.removeAttribute('src');video.load();status.textContent='이 영상의 기록이 삭제되어 재생을 종료했습니다. 영상 파일은 유지됩니다.';$<HTMLButtonElement>('reconnect').disabled=true;}
});
$('toggle').addEventListener('click',()=>void toggle());$('back').addEventListener('click',()=>jump(-10));$('forward').addEventListener('click',()=>jump(10));
$('mute').addEventListener('click',()=>{video.muted=!video.muted;update();});
$<HTMLInputElement>('volume').addEventListener('input',e=>{video.volume=Number((e.target as HTMLInputElement).value);video.muted=video.volume===0;update();});
$<HTMLSelectElement>('speed').addEventListener('change',e=>{video.playbackRate=Number((e.target as HTMLSelectElement).value);});
seek.addEventListener('input',()=>{video.currentTime=Number(seek.value);});$('fullscreen').addEventListener('click',()=>void fullscreen());$('reconnect').addEventListener('click',()=>void open());
document.addEventListener('keydown',e=>{if((e.target as HTMLElement).matches('input,select,button'))return;if(['Space','ArrowLeft','ArrowRight','KeyM','KeyF'].includes(e.code))e.preventDefault();if(e.code==='Space')void toggle();if(e.code==='ArrowLeft')jump(-10);if(e.code==='ArrowRight')jump(10);if(e.code==='KeyM'){$('mute').click();}if(e.code==='KeyF')void fullscreen();});
const timer=setInterval(()=>void save(),5000);
window.addEventListener('pagehide',()=>{closed=true;clearInterval(timer);const token=sessionId;void save().finally(()=>{if(token)void request('closePlayback',{sessionId:token}).catch(()=>{});keepalive.disconnect();});});
void open();
