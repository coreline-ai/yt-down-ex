import {test,expect} from '@playwright/test';
import {launchExtension,extensionId,request,startMediaServer} from './helpers.js';
import {join} from 'node:path';
test('real host streams completed media to player with seeking and panel-independent lifetime',async()=>{
 const app=await launchExtension();const media=await startMediaServer(join(app.base,'fixtures'));
 try{
  const panel=await app.context.newPage();await panel.goto(`chrome-extension://${extensionId}/panel.html`);
  await expect(panel.locator('#connection')).toHaveText('로컬 엔진 연결됨');
  const reply=await request(panel,'enqueue',{url:media.url+'/sample.mp4'});expect(reply.ok).toBe(true);
  await expect(panel.locator('.job[data-state="completed"]')).toHaveCount(1,{timeout:30000});
  const player=await app.context.newPage();await player.goto(`chrome-extension://${extensionId}/player.html?jobId=${reply.payload.jobId}`);
  await expect.poll(()=>player.locator('video').evaluate(v=>v.readyState)).toBeGreaterThanOrEqual(1);
  await player.locator('video').evaluate(async v=>{v.muted=true;await v.play()});
  await expect.poll(()=>player.locator('video').evaluate(v=>v.currentTime)).toBeGreaterThan(.2);
  await player.locator('video').evaluate(v=>{v.pause();v.currentTime=1.2});
  await expect.poll(()=>player.locator('video').evaluate(v=>v.currentTime)).toBeGreaterThan(1);
  await panel.close();await player.waitForTimeout(16000);
  const check=await request(player,'hello');expect(check.ok).toBe(true);
  await player.locator('video').evaluate(v=>{v.currentTime=.1;return v.play()});
  await expect.poll(()=>player.locator('video').evaluate(v=>v.currentTime)).toBeGreaterThan(.2);
  await player.close();
 }finally{await media.close();await app.close();}
});

test('player controls resume saved position and stop when history is deleted',async()=>{
 const {execFileSync}=await import('node:child_process');
 const app=await launchExtension();const media=await startMediaServer(join(app.base,'fixtures'));
 try {
  execFileSync('ffmpeg',['-v','error','-stream_loop','19','-i',join(app.base,'fixtures/sample.mp4'),'-c','copy',join(app.base,'fixtures/longclip.mp4')]);
  const panel=await app.context.newPage();await panel.goto(`chrome-extension://${extensionId}/panel.html`);
  await expect(panel.locator('#connection')).toHaveText('로컬 엔진 연결됨');
  const reply=await request(panel,'enqueue',{url:media.url+'/longclip.mp4',outputProfile:'mp4'});
  await expect(panel.locator('.job[data-state="completed"]')).toHaveCount(1,{timeout:30000});
  let player=await app.context.newPage();const url=`chrome-extension://${extensionId}/player.html?jobId=${reply.payload.jobId}`;
  await player.goto(url);await expect.poll(()=>player.locator('video').evaluate(v=>v.readyState)).toBeGreaterThanOrEqual(1);
  await player.locator('#toggle').click();await expect.poll(()=>player.locator('video').evaluate(v=>v.currentTime)).toBeGreaterThan(.2);
  await player.locator('#toggle').click();await player.locator('#speed').selectOption('1.5');
  expect(await player.locator('video').evaluate(v=>v.playbackRate)).toBe(1.5);
  await player.locator('#mute').click();expect(await player.locator('video').evaluate(v=>v.muted)).toBe(true);
  await player.locator('#forward').click();await player.locator('#forward').click();
  await expect.poll(async()=>{const r=await request(panel,'getSnapshot');return r.payload.jobs[0].playbackPosition?.seconds||0;}).toBeGreaterThan(20);
  const historyCheckbox=panel.locator('.job input[type=checkbox]');await historyCheckbox.focus();
  const stableCheckbox=await historyCheckbox.elementHandle();
  await player.locator('video').evaluate(v=>{v.currentTime=22;});
  await expect.poll(async()=>{const r=await request(panel,'getSnapshot');return r.payload.jobs[0].playbackPosition?.seconds||0;}).toBe(22);
  expect(await stableCheckbox.evaluate(el=>el.isConnected)).toBe(true);await expect(historyCheckbox).toBeFocused();
  await player.locator('#fullscreen').click();await expect.poll(()=>player.evaluate(()=>!!document.fullscreenElement)).toBe(true);
  await player.locator('#fullscreen').click();
  await player.close();player=await app.context.newPage();await player.goto(url);
  await expect.poll(()=>player.locator('video').evaluate(v=>v.currentTime)).toBeGreaterThan(20);
  const {readFile}=await import('node:fs/promises');
  const pid=Number((await readFile(join(app.base,'host.pid'),'utf8')).trim());expect(pid).toBeGreaterThan(1);process.kill(pid,'SIGTERM');
  await expect(player.locator('#status')).toContainText('엔진 연결이 종료');
  await player.locator('#reconnect').click();
  await expect.poll(()=>player.locator('video').evaluate(v=>v.currentTime)).toBeGreaterThan(20);
  await panel.getByRole('button',{name:'기록 삭제',exact:true}).click();await expect(player.locator('#status')).toContainText('기록이 삭제');
  expect(await player.locator('video').evaluate(v=>v.hasAttribute('src'))).toBe(false);
 }finally{await media.close();await app.close();}
});
