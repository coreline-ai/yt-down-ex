import {test,expect} from '@playwright/test';
import {launchExtension,extensionId,startMediaServer,request} from './helpers.js';
import {join} from 'node:path';
import {readdir} from 'node:fs/promises';
test('real transient HTTP error waits then saves once; waiting job can be cancelled',async()=>{
 const app=await launchExtension();const media=await startMediaServer(join(app.base,'fixtures'));
 try{
  const page=await app.context.newPage();await page.goto(`chrome-extension://${extensionId}/panel.html`);
  await expect(page.locator('#connection')).toHaveText('로컬 엔진 연결됨');
  const job=(await request(page,'enqueue',{url:media.url+'/transient.mp4',outputProfile:'mp4'})).payload;
  const card=page.locator(`[data-job-id="${job.jobId}"]`);
  await expect(card).toHaveAttribute('data-state','retry_wait',{timeout:10000});
  await expect(card.locator('.job-status')).toContainText('2/4회');
  await expect(card.locator('input[type="checkbox"]')).toHaveCount(0);
  await expect(card).toHaveAttribute('data-state','completed',{timeout:20000});
  const result=(await request(page,'getSnapshot')).payload.jobs[0];expect(result.attempt).toBe(2);expect(result.attemptHistory).toHaveLength(1);
  expect((await readdir(join(app.base,'downloads'))).filter(n=>n.endsWith('.mp4'))).toHaveLength(1);
  // Independent reset endpoint provides another actual retry window.
  const second=(await request(page,'enqueue',{url:media.url+'/reset.mp4'})).payload;
  const waiting=page.locator(`[data-job-id="${second.jobId}"]`);await expect(waiting).toHaveAttribute('data-state','retry_wait',{timeout:10000});
  await waiting.getByRole('button',{name:'취소',exact:true}).click();await expect(waiting).toHaveAttribute('data-state','cancelled');
  await page.waitForTimeout(6500);await expect(waiting).toHaveAttribute('data-state','cancelled');
  expect((await readdir(join(app.base,'downloads'))).filter(n=>n.endsWith('.mp4'))).toHaveLength(1);
 }finally{await media.close();await app.close();}
});
