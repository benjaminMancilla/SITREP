import { defineConfig } from 'vite'
import { svelte } from '@sveltejs/vite-plugin-svelte'

export default defineConfig(({ command }) => ({
  plugins: [svelte()],
  root: 'frontend',
  base: command === 'build' ? '/static/dist/' : '/static/',
  build: {
    manifest: true,
    outDir: '../static/dist',
    emptyOutDir: true,
    rollupOptions: {
      input: {
        urgencia: 'entrypoints/urgencia.js',
        fallos_feed: 'entrypoints/fallos_feed.js',
        naves_tabla: 'entrypoints/naves_tabla.js',
        calendario: 'entrypoints/calendario.js',
        heatmap_fleet: 'entrypoints/heatmap_fleet.js',
      },
    },
  },
  server: {
    port: 5173,
    strictPort: true,
    origin: 'http://localhost:5173',
  },
}))
