import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
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
