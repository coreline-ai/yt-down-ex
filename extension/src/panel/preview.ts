type Options={request:(type:string,payload?:object,id?:string)=>Promise<any>;refresh:()=>Promise<void>;error:(message?:string)=>void};
export function setupPreview({request,refresh,error}:Options) {
 const $=<T extends HTMLElement=HTMLElement>(id:string)=>document.getElementById(id) as T;
 const url=$<HTMLInputElement>('url'),mode=$<HTMLSelectElement>('mode'),quality=$<HTMLSelectElement>('quality');
 const analyze=$<HTMLButtonElement>('analyze'),download=$<HTMLButtonElement>('download');
 let generation=0,analyzing:string|undefined,readyUrl='',submitting=false;
 function invalidate(){generation++;readyUrl='';download.disabled=true;$('preview').hidden=true;if(analyzing){void request('cancelInspect',{inspectRequestId:analyzing}).catch(()=>{});analyzing=undefined;}analyze.disabled=false;analyze.textContent='주소 분석';}
 url.addEventListener('input',invalidate);
 async function inspect(){
  if(submitting)return;const value=url.value.trim();invalidate();const gen=generation;
  if(!value){error('영상 주소를 입력하세요.');return;}
  const id=crypto.randomUUID();analyzing=id;analyze.disabled=true;analyze.textContent='분석 중…';error();
  try {
   const info=await request('inspect',{url:value},id);if(gen!==generation)return;
   readyUrl=value;$('preview').hidden=false;$('preview-title').textContent=info.title;
   const known=(v:boolean|null)=>v===true?'있음':v===false?'없음':'미확인';
   const duration=info.duration!=null?`${Math.floor(info.duration/60)}분 ${Math.floor(info.duration%60)}초`:'길이 미확인';
   $('preview-meta').textContent=`${duration} · 영상 ${known(info.hasVideo)} · 음성 ${known(info.hasAudio)}`;
   $('preview-size').textContent=info.size!=null?`${info.sizeIsEstimate?'추정':'원본'} 용량 ${(info.size/1048576).toFixed(1)} MB · 최고 화질 기준, 변환 후 크기는 달라질 수 있습니다.`:'용량 미확인';
   $('preview-quality').textContent=info.heights.length?`제공 해상도: ${info.heights.map((h:number)=>h+'p').join(', ')}`:'화질 정보 미확인 · 최고 화질로 다운로드할 수 있습니다.';
   for(const option of quality.options)option.disabled=option.value!=='best'&&(!info.heights.length||!info.heights.some((h:number)=>h<=Number(option.value)));
   if(quality.selectedOptions[0]?.disabled)quality.value='best';
   const img=$<HTMLImageElement>('preview-image');$('preview-placeholder').hidden=!!info.thumbnail;img.hidden=!info.thumbnail;if(info.thumbnail)img.src=info.thumbnail;else img.removeAttribute('src');
   download.disabled=false;
  }catch(e){if(gen===generation)error((e as Error).message);}
  finally{if(gen===generation){analyzing=undefined;analyze.disabled=false;analyze.textContent='다시 분석';}}
 }
 $('download-form').addEventListener('submit',e=>{e.preventDefault();void inspect();});
 analyze.addEventListener('click',()=>void inspect());
 download.addEventListener('click',async()=>{
  if(submitting||!readyUrl||readyUrl!==url.value.trim())return;
  submitting=true;download.disabled=true;error();const target=readyUrl;
  try{await request('enqueue',{url:target,mode:mode.value==='audio'?'audio':'video',outputProfile:mode.value==='mp4'?'mp4':mode.value==='audio'?'mp3':'original',quality:quality.value,folder:$<HTMLInputElement>('folder').value.trim()});if(url.value.trim()===target){url.value='';invalidate();}await refresh();}
  catch(e){error((e as Error).message);download.disabled=!readyUrl;}
  finally{submitting=false;}
 });
 return {invalidate};
}
