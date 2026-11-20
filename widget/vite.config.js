import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { resolve } from 'path'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      'door-renderer': resolve(__dirname, '../packages/door-renderer/src/index.js'),
    },
  },
  build: {
    lib: {
      entry: 'src/index.jsx',
      name: 'OpenDCDesigner',
      fileName: 'opendc-door-designer',
      formats: ['iife']
    },
    outDir: 'dist',
    rollupOptions: {
      // Bundle React inside the widget (no external deps)
    },
    cssCodeSplit: false
  },
  define: {
    'process.env.NODE_ENV': JSON.stringify('production')
  }
})
