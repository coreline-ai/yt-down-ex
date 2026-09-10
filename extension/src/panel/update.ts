type Options={request:(type:string,payload?:object)=>Promise<any>;refresh:()=>Promise<void>};
export function setupUpdates({request,refresh}:Options){
 const $=<T extends HTMLElement=HTMLElement>(id:string)=>document.getElementById(id) as T;
 const box=$('diagnostics'),status=$('update-status');let working=false;
 const describe=async()=>{
  const d=await request('diagnose');box.hidden=false;
  box.textContent=`확장 ${chrome.runtime.getManifest().version} · 호스트 ${d.version}\n설치: ${d.release}\n프로토콜 ${d.protocolVersion} · 기록 DB ${d.schemaVersion}\n`+Object.entries(d.tools).map(([name,t]:[string,any])=>`${t.ok?'✓':'×'} ${name}: ${t.ok?t.version:'설치 필요'}${t.path?`\n  ${t.path}`:''}`).join('\n')+`\nEJS: ${d.ejs||'미설치'}\n검증 조합: ${d.compatible?'일치':'확인 필요'}`;
 };
 const setWorking=(value:boolean)=>{working=value;for(const id of ['check-update','install-update','rollback-update'])$<HTMLButtonElement>(id).disabled=value;};
 async function poll(){
  const deadline=Date.now()+300000;
  while(Date.now()<deadline){
   await new Promise(resolve=>setTimeout(resolve,2000));
   try{
    const s=await request('getUpdateStatus');status.textContent=s.message||s.state;
    if(['completed','failed','interrupted','idle'].includes(s.state)){if(s.updateReconnect)await new Promise(resolve=>setTimeout(resolve,500));await describe();await refresh();setWorking(false);return;}
   }catch{status.textContent='엔진을 설치하고 있습니다. 완료 후 다시 연결합니다…';}
  }
  status.textContent='업데이트 결과 확인 시간이 초과되었습니다. 잠시 후 진단을 눌러 상태를 확인하세요.';setWorking(false);
 }
 $('diagnose').addEventListener('click',async()=>{try{await describe();const s=await request('getUpdateStatus');if(s.state!=='idle')status.textContent=s.message;}catch(e){box.hidden=false;box.textContent=(e as Error).message;}});
 $('check-update').addEventListener('click',async()=>{
  if(working)return;setWorking(true);status.textContent='공식 배포 정보와 검증 목록을 확인합니다…';
  try{await describe();const s=await request('checkUpdate');const names:Record<string,string>={offline:'공식 배포 정보를 확인할 수 없습니다. 네트워크 연결을 확인하세요.',hash_mismatch:'공식 파일 해시가 검증 목록과 다릅니다. 설치하지 마세요.',up_to_date:'검증된 엔진 버전을 사용 중입니다.',available:'검증된 엔진 버전을 설치할 수 있습니다.'};status.textContent=(names[s.status]||s.status)+`\n권장: yt-dlp ${s.recommended['yt-dlp']} · EJS ${s.recommended['yt-dlp-ejs']}`+(s.unverifiedLatest?'\n더 최신 배포는 앱에서 검증하지 않아 설치 대상에 포함하지 않습니다.':'');}
  catch(e){status.textContent=(e as Error).message;}finally{setWorking(false);}
 });
 async function start(action:string){
  if(working)return;setWorking(true);status.textContent='업데이트 가능 상태를 확인합니다…';
  try{await request('startUpdate',{action});status.textContent='엔진 연결을 종료하고 설치를 시작합니다…';await poll();}
  catch(e){status.textContent=(e as Error).message;setWorking(false);}
 }
 $('install-update').addEventListener('click',()=>void start('install'));
 $('rollback-update').addEventListener('click',()=>void start('rollback'));
 void request('getUpdateStatus').then(s=>{if(!['idle','completed','failed','interrupted'].includes(s.state)){setWorking(true);void poll();}else if(s.state!=='idle')status.textContent=s.message;}).catch(()=>{});
}
