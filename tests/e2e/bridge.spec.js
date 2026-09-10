import {test,expect} from '@playwright/test';
import {launchExtension,extensionId,request} from './helpers.js';
test('real extension and native host handshake, malformed version and absent host',async()=>{
  const app=await launchExtension();
  try {
    const page=await app.context.newPage();
    page.on("pageerror",e=>console.log("PAGE ERROR",e.message));
    page.on("console",m=>console.log("CONSOLE",m.text()));
    await page.goto(`chrome-extension://${extensionId}/panel.html`);
    await expect(page.locator('#connection')).toHaveText('로컬 엔진 연결됨');
    expect((await request(page,'hello')).ok).toBe(true);
    expect((await request(page,'hello',{}, {protocolVersion:999})).ok).toBe(false);
    const absent=await page.evaluate(()=>new Promise(resolve=>{const p=chrome.runtime.connectNative('io.stashlocal.missing');p.onDisconnect.addListener(()=>resolve(chrome.runtime.lastError?.message));}));
    expect(absent).toContain('not found');
  } finally {await app.close();}
});
