import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import federation from '@originjs/vite-plugin-federation'
export default defineConfig({
  plugins: [vue(), federation({name:'ThemeStudio',filename:'remoteEntry.js', exposes:{'./Page':'./src/PageEntry.vue','./AppPage':'./src/Page.vue','./Config':'./src/Config.vue'}, shared:{vue:{import:false,requiredVersion:'^3.5.0'}}})],
  base:'', build:{target:'esnext',assetsDir:'',outDir:fileURLToPath(new URL('../../plugins.v2/themestudio/dist', import.meta.url)),emptyOutDir:true,minify:true}
})
