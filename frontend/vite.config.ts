import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // In development the API runs separately (uv run uvicorn cheiron.main:app); in Docker, nginx proxies /api.
    proxy: { '/api': process.env.API_URL ?? 'http://localhost:8000' },
  },
})
