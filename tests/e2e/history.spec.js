import {test,expect} from '@playwright/test';
import {launchExtension,extensionId,startMediaServer,request} from './helpers.js';
import {join} from 'node:path';
import {stat,readFile} from 'node:fs/promises';
test('history search, failed filter and batch deletion synchronize without deleting files',async()=>{
 const app=await launchExtension();const media=await startMediaServer(join(app.base,'fixtures'));
 try{
  const page=await app.context.newPage();await page.goto(`chrome-extension://${extensionId}/panel.html`);await expect(page.locator('#connection')).toHaveText('로컬 엔진 연결됨');
  await request(page,'enqueue',{url:media.url+'/sample.mp4'});await expect(page.locator('.job[data-state="completed"]')).toHaveCount(1,{timeout:30000});
  const file=(await request(page,'getSnapshot')).payload.jobs[0].result.path;
  const original=await readFile(file);
  for(let n=0;n<3;n++)await request(page,'enqueue',{url:media.url+`/missing-${n}.mp4`});
  await expect(page.locator('.job[data-state="failed"]')).toHaveCount(3,{timeout:30000});
  const other=await app.context.newPage();await other.goto(`chrome-extension://${extensionId}/panel.html`);await expect(other.locator('.job')).toHaveCount(4);
  await page.locator('#history-search').fill('sample');await expect(page.locator('.job')).toHaveCount(1);
  await page.locator('#history-search').fill('');await page.locator('#filter-failed').click();await expect(page.locator('.job')).toHaveCount(3);
  await page.locator('.job input[type=checkbox]').first().check();page.once('dialog',d=>d.accept());await page.locator('#delete-selected').click();
  await expect(page.locator('.job')).toHaveCount(2);
  page.once('dialog',d=>d.accept());await page.locator('#delete-failed').click();await expect(page.locator('.job')).toHaveCount(0);
  await expect(other.locator('.job')).toHaveCount(1);await page.locator('#filter-all').click();await expect(page.locator('.job')).toHaveCount(1);
  await page.reload();await expect(page.locator('.job')).toHaveCount(1);expect((await stat(file)).size).toBeGreaterThan(0);
  await page.locator('#select-page').check();page.once('dialog',d=>d.accept());await page.locator('#delete-selected').click();await expect(other.locator('.job')).toHaveCount(0);
  await page.reload();await expect(page.locator('.job')).toHaveCount(0);expect((await readFile(file)).equals(original)).toBe(true);
 }finally{await media.close();await app.close();}
});
