import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import federation from '@originjs/vite-plugin-federation'

const identity = process.env.MEDIA_TOOL_PLUGIN
if (!['MediaArchive', 'DiscRemux'].includes(identity)) throw Error('Select MediaArchive or DiscRemux')
export default defineConfig({
  define: { __PLUGIN_ID__: JSON.stringify(identity) },
  plugins: [vue(), federation({name:identity, filename:'remoteEntry.js',
    exposes:{'./Page':'./src/Page.vue','./AppPage':'./src/Page.vue','./Config':'./src/Config.vue'},
    shared:{vue:{import:false,requiredVersion:'^3.5.0'}}})],
  base:'', build:{target:'esnext',assetsDir:'',
    outDir:fileURLToPath(new URL(`../../plugins.v2/${identity.toLowerCase()}/dist`,import.meta.url)),
    emptyOutDir:true,minify:true}
})
