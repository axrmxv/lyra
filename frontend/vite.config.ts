import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// VITE_API_PROXY задаётся в docker-compose (http://api:8000);
// локальный запуск вне compose проксирует на localhost.
const apiProxyTarget = process.env.VITE_API_PROXY ?? 'http://localhost:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5173,
    proxy: {
      '/api': apiProxyTarget,
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: './src/setupTests.ts',
    // Правило .claude/rules/typescript.md: тесты рядом с кодом
    include: ['src/**/*.test.{ts,tsx}'],
  },
})
