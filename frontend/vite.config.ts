import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

const proxy = {
  '/api': {
    target: process.env.FINSIGHT_API_ORIGIN ?? 'http://127.0.0.1:8000',
    // Keep the browser host so the backend can verify same-origin mutations.
    changeOrigin: false,
  },
}

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { proxy },
  preview: { proxy },
})
