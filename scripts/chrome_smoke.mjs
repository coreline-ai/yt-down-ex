import {chromium,expect} from '@playwright/test';
import {mkdtemp,realpath,mkdir,readFile,writeFile,rm,stat,cp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join,resolve} from 'node:path';
import {execFileSync} from 'node:child_process';
import {startMediaServer} from '../tests/e2e/helpers.js';
const identity=JSON.parse(await readFile('shared/extension-id.json','utf8'));
const base=await realpath(await mkdtemp(join(tmpdir(),'stash-chrome-')));
const profile=join(base,'profile'),data=join(base,'native'),output=join(base,'downloads');
await mkdir(profile,{recursive:true});await mkdir('artifacts/chrome',{recursive:true});
let context,server,inspectPanel;
const report={timestamp:new Date().toISOString(),status:'running',browser:'Google Chrome',isolatedProfile:true};
try{
  execFileSync('python3',['scripts/install.py','--root',data,'--browser-data-dir',profile,'--wheel-dir',resolve('artifacts/wheels')],{stdio:'pipe'});
  context=await chromium.launchPersistentContext(profile,{channel:'chrome',headless:false,env:{...process.env,STASH_OUTPUT_DIR:output},args:['--enable-unsafe-extension-debugging'],ignoreDefaultArgs:['--disable-extensions']});
  const browser=context.browser();report.version=browser.version();
  const cdp=await browser.newBrowserCDPSession();
  const loaded=await cdp.send('Extensions.loadUnpacked',{path:resolve('dist')});
  report.extensionId=loaded.id;
  if(loaded.id!==identity.id)throw new Error('Unexpected extension ID');
  const worker=context.serviceWorkers().find(w=>w.url().includes(identity.id)) || await context.waitForEvent('serviceworker');
  await expect.poll(()=>worker.evaluate(()=>chrome.sidePanel.getPanelBehavior())).toEqual({openPanelOnActionClick:true});
  server=await startMediaServer(join(base,'fixtures'));
  const longTest=process.env.STASH_LONG_TEST==='1';
  if(longTest)await cp('artifacts/long/synthetic-30min.mp4',join(base,'fixtures/long.mp4'));
  report.fixture=longTest?'30 minute generated video':'2 second generated video';
  const web=await context.newPage();await web.goto(server.url+'/error.html');
  const {targetInfos}=await cdp.send('Target.getTargets',{filter:[{}]});
  const tabTarget=targetInfos.find(t=>t.type==='tab'&&t.url===web.url());
  if(!tabTarget){report.targets=targetInfos;throw new Error('Browser tab target not found');}
  await cdp.send('Extensions.triggerAction',{id:identity.id,targetId:tabTarget.targetId});
  let panelTarget;
  await expect.poll(async()=>{
    const list=(await cdp.send('Target.getTargets',{filter:[{}]})).targetInfos;
    panelTarget=list.find(t=>t.type==='page'&&t.url===`chrome-extension://${identity.id}/panel.html`);
    return !!panelTarget;
  },{timeout:15000}).toBe(true);
  report.panelTarget=panelTarget;
  // Chrome exposes the side panel outside Playwright's tab attachment filter.
  // Attach using the documented CDP session transport, never a replacement tab.
  const {sessionId}=await cdp.send('Target.attachToTarget',{targetId:panelTarget.targetId,flatten:false});
  let sequence=0;const pending=new Map();
  cdp.on('Target.receivedMessageFromTarget',event=>{
    if(event.sessionId!==sessionId)return;
    const message=JSON.parse(event.message),entry=pending.get(message.id);
    if(entry){pending.delete(message.id);clearTimeout(entry.timer);message.error?entry.reject(new Error(message.error.message)):entry.resolve(message.result);}
  });
  const send=(method,params={})=>new Promise((resolve,reject)=>{
    const id=++sequence,timer=setTimeout(()=>{pending.delete(id);reject(new Error('CDP timeout '+method));},15000);
    pending.set(id,{resolve,reject,timer});
    cdp.send('Target.sendMessageToTarget',{sessionId,message:JSON.stringify({id,method,params})}).catch(reject);
  });
  const evaluate=async expression=>{
    const result=await send('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});
    if(result.exceptionDetails)throw new Error(JSON.stringify(result.exceptionDetails));
    return result.result.value;
  };
  inspectPanel=()=>evaluate('document.body.innerText');
  await expect.poll(()=>evaluate('document.querySelector("#connection")?.textContent'),{timeout:15000}).toBe('로컬 엔진 연결됨');
  await evaluate('document.querySelector("#url").focus()');
  await send('Input.insertText',{text:server.url+(longTest?'/long.mp4':'/sample.mp4')});
  await send('Input.dispatchKeyEvent',{type:'keyDown',key:'Enter',code:'Enter',text:'\r',unmodifiedText:'\r',windowsVirtualKeyCode:13});
  await send('Input.dispatchKeyEvent',{type:'keyUp',key:'Enter',code:'Enter',windowsVirtualKeyCode:13});
  await expect.poll(()=>evaluate('document.querySelector("#download").disabled'),{timeout:30000}).toBe(false);
  await evaluate('document.querySelector("#download").click()');
  await expect.poll(()=>evaluate(`document.querySelectorAll('.job[data-state="completed"]').length`),{timeout:30000}).toBe(1);
  const nativeRequest=type=>evaluate(`chrome.runtime.sendMessage({nativeRequest:{protocolVersion:1,requestId:crypto.randomUUID(),type:${JSON.stringify(type)},payload:{}}})`);
  const reply=await nativeRequest('getSnapshot');report.result=reply.payload.jobs[0].result;
  report.diagnostics=(await nativeRequest('diagnose')).payload;
  if(!(await stat(report.result.path)).size)throw new Error('Empty result');
  execFileSync('ffmpeg',['-v','error','-xerror','-i',report.result.path,'-f','null','-']);
  const reveal=await evaluate(`chrome.runtime.sendMessage({nativeRequest:{protocolVersion:1,requestId:crypto.randomUUID(),type:'revealFile',payload:{jobId:${JSON.stringify(reply.payload.jobs[0].jobId)}}}})`);
  if(!reveal.ok)throw new Error('Reveal file failed');report.revealFile=true;
  const screenshot=await send('Page.captureScreenshot',{format:'png',captureBeyondViewport:true});
  await writeFile('artifacts/chrome/side-panel.png',Buffer.from(screenshot.data,'base64'));
  if(!longTest)await cp(report.result.path,'artifacts/chrome/sample.mp4');
  const player=await context.newPage();
  await player.goto(`chrome-extension://${identity.id}/player.html?jobId=${reply.payload.jobs[0].jobId}`);
  await expect.poll(()=>player.locator('video').evaluate(v=>v.readyState)).toBeGreaterThanOrEqual(1);
  await player.locator('video').evaluate(async v=>{v.muted=true;await v.play()});
  await expect.poll(()=>player.locator('video').evaluate(v=>v.currentTime)).toBeGreaterThan(.2);
  const seekTarget=longTest?900:1.2;
  await player.locator('video').evaluate((v,t)=>{v.pause();v.currentTime=t},seekTarget);
  await expect.poll(()=>player.locator('video').evaluate(v=>!v.seeking&&v.currentTime)).toBeGreaterThan(seekTarget-.1);
  if(longTest){await player.locator('video').evaluate(async v=>{await v.play()});await expect.poll(()=>player.locator('video').evaluate(v=>v.currentTime)).toBeGreaterThan(900.5);await player.locator('video').evaluate(v=>v.pause());}
  report.playback=await player.locator('video').evaluate(v=>({duration:v.duration,currentTime:v.currentTime,readyState:v.readyState,width:v.videoWidth,height:v.videoHeight}));
  await player.screenshot({path:longTest?'artifacts/long/chrome-player.png':'artifacts/chrome/player.png'});
  report.status='passed';report.decodeExitCode=0;report.actualSidePanel=true;
}catch(error){report.status='failed';report.error=String(error);if(inspectPanel)report.failureUI=await inspectPanel().catch(()=>null);process.exitCode=1;}
finally{
  if(server)await server.close();if(context)await context.close();
  await writeFile(process.env.STASH_LONG_TEST==='1'?'artifacts/long/chrome-report.json':'artifacts/chrome/report.json',JSON.stringify(report,null,2));
  console.log(JSON.stringify(report,null,2));
  await rm(base,{recursive:true,force:true});
}
