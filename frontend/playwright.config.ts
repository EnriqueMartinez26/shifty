import { defineConfig, devices } from '@playwright/test'

/**
 * E2E de la reserva publica en viewport movil, contra un stack local levantado
 * (docker compose up + `npm run dev`). No arranca el backend: si no hay API en
 * E2E_API_URL el spec se salta con el motivo. Ver docs/PLAN_PRODUCTO_2026-09.md
 * (Fase 7) y el workflow `.github/workflows/e2e.yml` (manual).
 */
export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['github'], ['html', { open: 'never' }]] : 'list',
  use: {
    baseURL: process.env.E2E_BASE_URL ?? 'http://localhost:5173',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure'
  },
  projects: [{ name: 'movil', use: { ...devices['Pixel 7'] } }],
  // Contra un entorno externo (E2E_NO_WEBSERVER=1, como en el workflow
  // manual) no se levanta vite; local, se reusa el `npm run dev` que ya corre.
  webServer: process.env.E2E_NO_WEBSERVER
    ? undefined
    : {
        command: 'npm run dev -- --port 5173 --strictPort',
        url: 'http://localhost:5173',
        reuseExistingServer: true,
        timeout: 120_000
      }
})
