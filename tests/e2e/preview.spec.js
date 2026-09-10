import {test,expect} from '@playwright/test';
import {launchExtension,extensionId,startMediaServer,request} from './helpers.js';
import {join} from 'node:path';
test('analysis is required and stale analysis cannot submit a different URL',async()=>{
 const app=await launchExtension();const media=await startMediaServer(join(app.base,'fixtures'));
 try{
  const page=await app.context.newPage();await page.goto(`chrome-extension://${extensionId}/panel.html`);
  await expect(page.locator('#connection')).toHaveText('로컬 엔진 연결됨');await expect(page.locator('#download')).toBeDisabled();
  await page.locator('#url').fill(media.url+'/slow.mp4');await page.locator('#analyze').click();
  await page.locator('#url').fill(media.url+'/sample.mp4');await page.locator('#analyze').click();
  await expect(page.locator('#preview-title')).toHaveText('sample');
  await expect(page.locator('#preview-placeholder')).toBeVisible();
  await expect(page.locator('#preview-quality')).toContainText('미확인');
  await expect(page.locator('#download')).toBeEnabled();
  await page.locator('#url').fill(media.url+'/missing.mp4');await expect(page.locator('#download')).toBeDisabled();
  await page.locator('#analyze').click();await expect(page.locator('#error')).toContainText('HTTP 404');
  expect((await request(page,'getSnapshot')).payload.total).toBe(0);
  await page.locator('#url').fill(media.url+'/sample.mp4');await page.locator('#url').press('Enter');
  await expect(page.locator('#download')).toBeEnabled();await page.locator('#download').dblclick();
  await expect(page.locator('.job[data-state="completed"]')).toHaveCount(1,{timeout:30000});
  const snapshot=(await request(page,'getSnapshot')).payload;expect(snapshot.total).toBe(1);expect(snapshot.jobs[0].url).toBe(media.url+'/sample.mp4');
 }finally{await media.close();await app.close();}
});
