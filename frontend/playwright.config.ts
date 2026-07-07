import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './tests',
  timeout: 15000,
  retries: 0,
  use: {
    baseURL: 'http://127.0.0.1:8080',
  },
  webServer: {
    command: 'cd .. && uv run agentjam cockpit launch --web --port 8080',
    url: 'http://127.0.0.1:8080/api/health',
    reuseExistingServer: true,
    timeout: 10000,
  },
})
