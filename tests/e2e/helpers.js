import {chromium} from '@playwright/test';
import {mkdtemp, mkdir, writeFile, rm, readFile, realpath} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join, resolve} from 'node:path';
import {execFileSync} from 'node:child_process';
const identity = JSON.parse(await readFile('shared/extension-id.json','utf8'));
export const extensionId = identity.id;
export async function launchExtension({installed=false}={}) {
  const base = await realpath(await mkdtemp(join(tmpdir(),'stash-e2e-')));
  const home = join(base,'home');
  const profile = join(home,'Library/Application Support/Chromium');
  const hosts = join(profile,'NativeMessagingHosts');
  await mkdir(hosts,{recursive:true});
  const python = execFileSync('python3',['-c','import sys; print(sys.executable)'],{encoding:'utf8'}).trim();
  const launcher = join(base,'host');
  const quote = value => `'${value.replaceAll("'", "'\\''")}'`;
  await writeFile(launcher,`#!/bin/sh\necho $$ > ${quote(join(base,'host.pid'))}\ncd ${quote(resolve('.'))}\nexec ${quote(python)} -m native.host "$@"\n`,{mode:0o755});
  if(!installed)await writeFile(join(hosts,identity.host+'.json'),JSON.stringify({name:identity.host,description:'Stash test host',path:launcher,type:'stdio',allowed_origins:[`chrome-extension://${identity.id}/`]}));
  if(installed)execFileSync(python,['scripts/install.py','--root',join(base,'data'),'--browser-data-dir',profile,'--wheel-dir',resolve('artifacts/wheels')],{timeout:60000});
  const context = await chromium.launchPersistentContext(profile,{channel:'chromium',headless:true,env:{...process.env,STASH_DATA_DIR:join(base,'data'),STASH_OUTPUT_DIR:join(base,'downloads')},args:[`--disable-extensions-except=${resolve('dist')}`,`--load-extension=${resolve('dist')}`]});
  return {context,base,home,profile,async close(){await context.close();await rm(base,{recursive:true,force:true});}};
}
export async function request(page,type,payload={},extra={}) {
  return page.evaluate(async ({type,payload,extra})=>chrome.runtime.sendMessage({nativeRequest:{protocolVersion:1,requestId:crypto.randomUUID(),type,payload,...extra}}),{type,payload,extra});
}
export async function startMediaServer(directory) {
  const {spawn} = await import('node:child_process');
  const child=spawn('python3',['scripts/fixture_server.py',directory],{stdio:['ignore','pipe','pipe']});
  const url=await new Promise((resolve,reject)=>{
    let output='';child.stdout.on('data',chunk=>{output+=chunk;if(output.includes('\n')){try{resolve(JSON.parse(output.split('\n')[0]).url);}catch(e){reject(e);}}});
    child.on('error',reject);child.on('exit',code=>reject(new Error('fixture server exited '+code)));
  });
  return {url,async close(){child.kill('SIGTERM');await new Promise(resolve=>child.once('exit',resolve));}};
}
