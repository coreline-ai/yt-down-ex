import {defineConfig} from 'vite';
import {resolve} from 'node:path';
export default defineConfig({root:'extension',publicDir:'public',build:{outDir:'../dist',emptyOutDir:true,rollupOptions:{input:{panel:resolve('extension/panel.html'),player:resolve('extension/player.html'),background:resolve('extension/src/background.ts')},output:{entryFileNames:'[name].js'}}}});
