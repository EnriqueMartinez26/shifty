import { expect, test, type Page } from '@playwright/test'

/**
 * Reserva publica completa desde un telefono (Fase 7, pendiente desde
 * 2026-09-11): servicio -> horario -> datos -> confirmacion, sin scroll
 * horizontal en ningun paso.
 *
 * Necesita un stack local con una tienda publicada (el alta es solo desde el
 * superadmin, asi que no se crea desde aca):
 *   E2E_STORE_SLUG   slug de la tienda (obligatorio; sin el, se salta)
 *   E2E_API_URL      API para el chequeo previo (default http://localhost:8000)
 *   E2E_BASE_URL     front (default http://localhost:5173, ver playwright.config.ts)
 * La tienda no debe exigir OTP ni seña obligatoria: el flujo que se prueba es
 * el de "reservar y coordinar por WhatsApp".
 */

const slug = process.env.E2E_STORE_SLUG
const apiUrl = process.env.E2E_API_URL ?? 'http://localhost:8000'

const sinScrollHorizontal = async (page: Page, paso: string) => {
  const desborde = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth
  )
  expect(desborde, `el paso "${paso}" desborda horizontalmente`).toBeLessThanOrEqual(0)
}

test.describe('reserva publica desde el celular', () => {
  test.skip(!slug, 'Definir E2E_STORE_SLUG con una tienda publicada del stack local')

  test.beforeAll(async ({ request }) => {
    const salud = await request.get(`${apiUrl}/ops/health/live`).catch(() => null)
    test.skip(!salud || !salud.ok(), `no hay API en ${apiUrl}: levantar el stack local`)
  })

  test('elige servicio y horario, deja sus datos y ve la reserva registrada', async ({ page }) => {
    await page.goto(`/b/${slug}`)

    // Paso 1: servicio. Con un solo servicio el wizard lo elige solo y ya
    // muestra el horario; con varios, se toca el primero.
    const tituloServicio = page.getByText('¿Qué servicio necesitás?')
    const tituloHorario = page.getByText('Elegi fecha y hora')
    await expect(tituloServicio.or(tituloHorario)).toBeVisible()
    if (await tituloServicio.isVisible()) {
      await sinScrollHorizontal(page, 'servicio')
      await page
        .getByRole('button', { name: /\d+ min/ })
        .first()
        .click()
    }

    // Paso 2: horario. Se recorre la tira de dias hasta encontrar un slot
    // disponible (los primeros dias pueden estar llenos o fuera de horario).
    await expect(tituloHorario).toBeVisible()
    await sinScrollHorizontal(page, 'horario')
    const dias = page.locator('[data-testid^="date-"]')
    const cantidad = await dias.count()
    const slot = page.locator('button:not([disabled])', { hasText: /^\d{2}:\d{2}/ }).first()
    const sinTurnos = page.getByText('No hay turnos disponibles.')
    for (let i = 0; i < cantidad; i += 1) {
      await dias.nth(i).click()
      // Esperar a que ese dia termine de cargar: o hay un slot o dice que no
      // hay (isVisible() no espera; revisar antes de la carga miraba vacio).
      await expect(slot.or(sinTurnos).first()).toBeVisible({ timeout: 10_000 })
      if ((await slot.count()) > 0) break
    }
    await expect(slot, 'ningun dia de la tira tiene un horario disponible').toBeVisible()
    await slot.click()

    // Paso 3: datos y confirmacion.
    await expect(page.getByPlaceholder('PREFIJO + NUM')).toBeVisible()
    await sinScrollHorizontal(page, 'datos')
    const sufijo = `${Date.now()}`.slice(-6)
    await page.getByPlaceholder('Ej: Juan Perez').fill('Prueba E2E Movil')
    await page.getByPlaceholder('juan@email.com').fill(`e2e-${sufijo}@example.com`)
    await page.getByPlaceholder('PREFIJO + NUM').fill(`+54911${sufijo}00`)
    await page.getByRole('checkbox').first().check()
    await page.getByRole('button', { name: /reservar y pagar por whatsapp/i }).click()

    // Los tres finales validos del flujo: confirmada, registrada (pendiente de
    // revision de la tienda) o pendiente de pago.
    await expect(
      page.getByRole('heading', {
        name: /^Reserva (Confirmada|Registrada|Pendiente de Pago)$/
      })
    ).toBeVisible({ timeout: 20_000 })
    await expect(page.getByText('Detalles del Turno')).toBeVisible()
    await sinScrollHorizontal(page, 'confirmacion')
  })
})
