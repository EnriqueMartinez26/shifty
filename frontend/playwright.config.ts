import { defineConfig, devices } from '@playwright/test'

const baseURL = 'http://127.0.0.1:13000'
const apiURL = 'http://127.0.0.1:13000/api'

if (process.env.E2E_ISOLATED !== '1') {
  throw new Error('Playwright E2E requiere npm run e2e:isolated')
}
if (process.env.E2E_BASE_URL !== baseURL || process.env.E2E_API_URL !== apiURL) {
  throw new Error('Playwright E2E solo admite las URLs loopback del stack descartable')
}

export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['github'], ['html', { open: 'never' }]] : 'list',
  use: {
    baseURL,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure'
  },
  projects: [{ name: 'movil', use: { ...devices['Pixel 7'] } }]
})
