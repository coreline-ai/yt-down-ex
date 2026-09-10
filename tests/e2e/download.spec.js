import {test,expect} from '@playwright/test';
import {launchExtension,extensionId,request,startMediaServer} from './helpers.js';
import {join,resolve} from 'node:path';
import {mkdir,stat} from 'node:fs/promises';
import {execFileSync} from 'node:child_process';

test('URL input saves a verified video and MP3 through the real native host',async()=>{
  const app=await launchExtension();const media=await startMediaServer(join(app.base,'fixtures'));
  try {
    const page=await app.context.newPage();await page.setViewportSize({width:390,height:1000});await page.goto(`chrome-extension://${extensionId}/panel.html`);
    await expect(page.locator('#connection')).toHaveText('로컬 엔진 연결됨');
    await mkdir('artifacts/screenshots',{recursive:true});await page.screenshot({path:'artifacts/screenshots/empty.png',fullPage:true});
    await page.locator('#url').fill(media.url+'/manifest.mpd');await page.locator('#url').press('Enter');await expect(page.locator('#download')).toBeEnabled();await page.locator('#download').click();
    await expect(page.locator('.job[data-state="completed"]')).toHaveCount(1,{timeout:30000});
    const snapshot=(await request(page,'getSnapshot')).payload;const result=snapshot.jobs[0].result;
    expect(result.streams.map(s=>s.codec_type).sort()).toEqual(['audio','video']);expect((await stat(result.path)).size).toBeGreaterThan(0);
    execFileSync('ffmpeg',['-v','error','-i',result.path,'-f','null','-']);
    await page.locator('#mode').selectOption('audio');await expect(page.locator('#quality')).toBeDisabled();
    await page.locator('#url').fill(media.url+'/sample.mp4');await page.locator('#analyze').click();await expect(page.locator('#download')).toBeEnabled();await page.locator('#download').click();
    await expect(page.locator('.job[data-state="completed"]')).toHaveCount(2,{timeout:30000});
    const second=(await request(page,'getSnapshot')).payload.jobs[0];expect(second.result.container).toBe('mp3');
    await page.screenshot({path:'artifacts/screenshots/downloads.png',fullPage:true});
    await page.locator('#filter-completed').click();await expect(page.locator('.job')).toHaveCount(2);
    await page.locator('#settings-toggle').click();await page.locator('#diagnose').click();await expect(page.locator('#diagnostics')).toContainText('✓ ffmpeg');
    await page.locator('#mode').selectOption('video');await page.locator('#filter-all').click();
    await page.locator('#url').fill(media.url+'/long.html');await page.locator('#analyze').click();await expect(page.locator('#download')).toBeEnabled();await page.locator('#download').click();
    await expect(page.locator('.job[data-state="completed"]')).toHaveCount(3,{timeout:30000});
    await expect(page.locator('.job h3').first()).toContainText('아주 긴 제목');
    expect(await page.locator('.job script').count()).toBe(0);
    await page.screenshot({path:'artifacts/screenshots/long-title.png',fullPage:true});
    const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth);expect(overflow).toBe(false);
    const completed=page.locator(`.job[data-job-id="${snapshot.jobs[0].jobId}"]`);
    await completed.getByRole('button',{name:'기록 삭제',exact:true}).click();
    await expect(completed).toHaveCount(0);
    expect((await stat(result.path)).size).toBeGreaterThan(0);
  }finally{await media.close();await app.close();}
});

test('closing and reopening panel keeps download; cancel and retry are real',async()=>{
  const app=await launchExtension();const media=await startMediaServer(join(app.base,'fixtures'));
  try {
    let page=await app.context.newPage();await page.goto(`chrome-extension://${extensionId}/panel.html`);
    await expect(page.locator('#connection')).toHaveText('로컬 엔진 연결됨');
    await page.locator('#url').fill(media.url+'/slow.mp4');await page.locator('#analyze').click();await expect(page.locator('#download')).toBeEnabled();await page.locator('#download').click();
    await expect(page.locator('.job[data-state="downloading"]')).toHaveCount(1,{timeout:20000});
    await page.close();page=await app.context.newPage();await page.goto(`chrome-extension://${extensionId}/panel.html`);
    await expect(page.locator('.job')).toHaveCount(1);
    await page.getByRole('button',{name:'취소',exact:true}).click();
    await expect(page.locator('.job[data-state="cancelled"]')).toHaveCount(1);
    await page.getByRole('button',{name:'다시 시도',exact:true}).click();
    await expect(page.locator('.job[data-state="completed"]')).toHaveCount(1,{timeout:45000});
    expect((await request(page,'getSnapshot')).payload.total).toBe(2);
  }finally{await media.close();await app.close();}
});

test('invalid URL and missing media produce usable errors at narrow width',async()=>{
  const app=await launchExtension();const media=await startMediaServer(join(app.base,'fixtures'));
  try {
    const page=await app.context.newPage();await page.setViewportSize({width:320,height:900});await page.goto(`chrome-extension://${extensionId}/panel.html`);
    await page.locator('#url').fill('file:///tmp/foo');await page.locator('#analyze').click();
    await expect(page.locator('#error')).toContainText('HTTP(S)');
    await page.locator('#url').fill(media.url+'/missing.mp4');await page.locator('#analyze').click();
    await expect(page.locator('#error')).toContainText('HTTP 404');await expect(page.locator('#download')).toBeDisabled();
    await request(page,'enqueue',{url:media.url+'/missing.mp4'});
    await expect(page.locator('.job[data-state="failed"]')).toHaveCount(1,{timeout:30000});
    await expect(page.locator('.job-error')).toContainText('HTTP 404');
    await page.screenshot({path:'artifacts/screenshots/error-320.png',fullPage:true});
    expect(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)).toBe(false);
    const other=await app.context.newPage();await other.goto(`chrome-extension://${extensionId}/panel.html`);
    await expect(other.locator('.job')).toHaveCount(1);
    await page.getByRole('button',{name:'기록 삭제',exact:true}).click();
    await expect(page.locator('.job')).toHaveCount(0);
    await expect(other.locator('.job')).toHaveCount(0);
    await page.reload();await expect(page.locator('#connection')).toHaveText('로컬 엔진 연결됨');
    await expect(page.locator('#job-count')).toHaveText('0');
  }finally{await media.close();await app.close();}
});
