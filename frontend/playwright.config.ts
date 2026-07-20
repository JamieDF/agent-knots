import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './tests',
  timeout: 60000,  // 60s — some tests create real agent sessions
  retries: 0,
  use: {
    baseURL: 'http://127.0.0.1:8090',
  },
})
