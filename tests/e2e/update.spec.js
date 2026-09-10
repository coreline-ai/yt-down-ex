import {test,expect} from '@playwright/test';
import {launchExtension,extensionId,startMediaServer,request} from './helpers.js';
import {join} from 'node:path';
import {readFile,writeFile} from 'node:fs/promises';
test('installed engine GUI refuses busy work, recovers from hash failure, installs and rolls back preserving media',async()=>{
 test.setTimeout(180000);
 const app=await launchExtension({installed:true});const media=await startMediaServer(join(app.base,'fixtures'));
 const active=async()=>JSON.parse(await readFile(join(app.base,'data/active.json'),'utf8'));
 try{
  const page=await app.context.newPage();await page.goto(`chrome-extension://${extensionId}/panel.html`);await expect(page.locator('#connection')).toHaveText('로컬 엔진 연결됨');await page.locator('#settings-toggle').click();
  await page.locator('#diagnose').click();await expect(page.locator('#diagnostics')).toContainText('호스트 0.2.0');
  const slow=(await request(page,'enqueue',{url:media.url+'/slow.mp4'})).payload;
  await expect(page.locator('.job[data-state="downloading"]')).toHaveCount(1);
  expect((await request(page,'startUpdate')).error.code).toBe('UPDATE_BUSY');await request(page,'cancel',{jobId:slow.jobId});
  const job=(await request(page,'enqueue',{url:media.url+'/sample.mp4',outputProfile:'mp4'})).payload;
  await expect(page.locator('.job[data-state="completed"]')).toHaveCount(1,{timeout:30000});
  const completed=(await request(page,'getSnapshot')).payload.jobs.find(j=>j.jobId===job.jobId);const bytes=await readFile(completed.result.path);
  const player=await app.context.newPage();await player.goto(`chrome-extension://${extensionId}/player.html?jobId=${job.jobId}`);
  await expect.poll(()=>player.locator('video').evaluate(v=>v.readyState)).toBeGreaterThan(0);
  expect((await request(page,'startUpdate')).error.code).toBe('UPDATE_BUSY');
  await player.locator('video').evaluate(v=>{v.currentTime=.5;});await player.waitForTimeout(700);await player.close();
  const original=await active();const catalogPath=join(original.release,'shared/engine-releases.json');const catalog=await readFile(catalogPath,'utf8');const broken=JSON.parse(catalog);broken.packages[0].sha256='0'.repeat(64);await writeFile(catalogPath,JSON.stringify(broken));
  await page.locator('#install-update').click();await expect(page.locator('#update-status')).toContainText('해시',{timeout:60000});await expect(page.locator('#install-update')).toBeEnabled();expect(await active()).toEqual(original);await writeFile(catalogPath,catalog);
  await page.locator('#install-update').click();await expect(page.locator('#update-status')).toContainText('설치가 완료',{timeout:60000});await expect(page.locator('#install-update')).toBeEnabled();const updated=await active();expect(updated.release).not.toBe(original.release);await expect(page.locator('#diagnostics')).toContainText(updated.release);
  expect((await readFile(completed.result.path)).equals(bytes)).toBe(true);
  let saved=(await request(page,'getSnapshot')).payload.jobs.find(j=>j.jobId===job.jobId);expect(saved.playbackPosition.seconds).toBeCloseTo(.5,1);
  await page.locator('#rollback-update').click();await expect(page.locator('#update-status')).toContainText('복원이 완료',{timeout:60000});await expect(page.locator('#install-update')).toBeEnabled();expect(await active()).toEqual(original);
  saved=(await request(page,'getSnapshot')).payload.jobs.find(j=>j.jobId===job.jobId);expect(saved.result.path).toBe(completed.result.path);expect((await readFile(saved.result.path)).equals(bytes)).toBe(true);
  await request(page,'enqueue',{url:media.url+'/sample.mp4',outputProfile:'mp4'});await expect(page.locator('.job[data-state="completed"]')).toHaveCount(2,{timeout:30000});
  const again=await app.context.newPage();await again.goto(`chrome-extension://${extensionId}/player.html?jobId=${job.jobId}`);await expect.poll(()=>again.locator('video').evaluate(v=>v.readyState)).toBeGreaterThan(0);await again.locator('video').evaluate(async v=>{v.muted=true;await v.play();});await expect.poll(()=>again.locator('video').evaluate(v=>v.currentTime)).toBeGreaterThan(.7);
 }finally{await media.close();await app.close();}
});
