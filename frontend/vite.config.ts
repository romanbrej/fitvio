import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react()],
  // the demo (VITE_DEMO=1) is served from a sub-path on GitHub Pages: relative asset URLs work anywhere
  base: process.env.VITE_DEMO === '1' ? './' : '/',
  server: {
    host: true,
    proxy: { '/api': 'http://127.0.0.1:8765' },
  },
})
