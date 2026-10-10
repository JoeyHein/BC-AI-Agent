import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'
import { fileURLToPath } from 'url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const repoRoot = path.resolve(__dirname, '..')

export default defineConfig({
  plugins: [react()],
  resolve: {
    // Pin React to this package so the portal source we import does not
    // pull a second copy from frontend/node_modules.
    alias: {
      react: path.resolve(__dirname, 'node_modules/react'),
      'react-dom': path.resolve(__dirname, 'node_modules/react-dom'),
    },
    dedupe: ['react', 'react-dom'],
  },
  server: {
    fs: {
      allow: [repoRoot],
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
