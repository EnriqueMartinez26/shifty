import { expect, test, type Page } from '@playwright/test'

interface IsolatedFixture {
  kind: 'shifty-isolated-e2e-v1'
  runId: string
  storeSlug: string
  staffId: string
  services: Array<{ id: string; name: string; durationMinutes: number; price: number }>
}

const fixtureJson = process.env.E2E_FIXTURE_JSON
if (process.env.E2E_ISOLATED !== '1' || !fixtureJson) {
  throw new Error('E2E requiere el fixture generado por npm run e2e:isolated')
}

const fixture = JSON.parse(fixtureJson) as IsolatedFixture
const runId = process.env.E2E_ISOLATED_RUN_ID
if (
  fixture.kind !== 'shifty-isolated-e2e-v1' ||
  !runId ||
  fixture.runId !== runId ||
  fixture.storeSlug !== `qa-e2e-${runId}` ||
  !fixture.staffId ||
  fixture.services.length !== 2
) {
  throw new Error('El fixture no pertenece a esta corrida aislada')
}
const [primaryService, extraService] = fixture.services
if (!primaryService || !extraService) {
  throw new Error('El fixture requiere un servicio principal y uno adicional')
}

const apiUrl = process.env.E2E_API_URL
if (!apiUrl || apiUrl !== 'http://127.0.0.1:13000/api') {
  throw new Error('E2E solo admite la API loopback del stack descartable')
}

// El nombre con el que run-isolated.mjs da de alta la tienda de esta corrida.
const storeName = `Tienda QA ${runId}`
// El profesional del fixture es un recurso: la linea del turno muestra su nombre.
const staffName = 'Recurso QA'
// El fixture no tiene seña ni adicionales: el envio es "Confirmar reserva" (o el
// de la seña por WhatsApp, si la tienda la pidiera).
const SUBMIT_NAME = /^(confirmar reserva|reservar y pagar la seña por whatsapp)$/i
const SUCCESS_HEADING = /^Reserva (Confirmada|Registrada|Pendiente de Pago)$/
const TERMS_CHECKBOX = /acepto los términos y condiciones/i
const FORM_HUMAN_DWELL_MS = 3_000

const escapeRegExp = (value: string) => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

const runSuffix = runId
  .replace(/[^a-f0-9]/gi, '')
  .slice(-12)
  .split('')
  .map((character) => (Number.parseInt(character, 16) % 10).toString())
  .join('')

const sinScrollHorizontal = async (page: Page, paso: string) => {
  const desborde = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth
  )
  expect(desborde, `el paso "${paso}" desborda horizontalmente`).toBeLessThanOrEqual(0)
}

/** Toca cada servicio del fixture (reserva multiservicio) y verifica que quede elegido. */
const elegirServicios = async (page: Page) => {
  for (const service of fixture.services) {
    const card = page.getByRole('button', { name: new RegExp(escapeRegExp(service.name)) })
    await card.click()
    await expect(card).toHaveAttribute('aria-pressed', 'true')
  }
}

/** Recorre los dias hasta el primero con horarios y toca el primer horario libre. */
const elegirPrimerHorario = async (page: Page, motivo: string) => {
  const days = page.locator('[data-testid^="date-"]')
  const slots = page.locator('button:not([disabled])', { hasText: /^\d{2}:\d{2}/ })
  const empty = page.getByText(/^(No hay turnos disponibles\.|Este día no hay atención\.)$/)
  for (let index = 0; index < (await days.count()); index += 1) {
    await days.nth(index).click()
    // Esperar a que ese dia termine de cargar: aparece un slot o uno de los
    // estados vacios (dia sin atencion o agenda completa).
    await expect(slots.first().or(empty).first()).toBeVisible({ timeout: 10_000 })
    if ((await slots.count()) > 0) break
  }
  await expect(slots.first(), motivo).toBeVisible()
  await slots.first().click()
}

/** El backend rechaza `form_elapsed_ms < 2500`; simula el tiempo humano con margen. */
const waitForBookingFormDwell = async (page: Page) => {
  await expect(page.getByPlaceholder('Ej: Juan Perez')).toBeVisible()
  await page.waitForTimeout(FORM_HUMAN_DWELL_MS)
}

/**
 * En el celular el boton de envio vive en la barra fija al pie (S5) y es el
 * unico control que reserva: ningun otro boton confirma, paga ni reserva.
 */
const botonDeEnvioEnLaBarra = async (page: Page) => {
  const payBar = page.getByTestId('booking-pay-bar')
  const confirm = payBar.getByRole('button', { name: SUBMIT_NAME })
  await expect(payBar).toHaveCSS('position', 'fixed')
  await expect(confirm).toBeInViewport()
  await expect(confirm).toHaveCSS('min-height', '44px')
  await expect(page.getByRole('button', { name: /confirmar|pagar|reservar/i })).toHaveCount(1)
  return confirm
}

test.describe('reserva pública aislada desde el celular', () => {
  test.beforeAll(async ({ request }) => {
    let health: Awaited<ReturnType<typeof request.get>>
    try {
      health = await request.get(`${apiUrl}/ops/health/ready`, { timeout: 5_000 })
    } catch {
      throw new Error('No responde la API del stack E2E aislado')
    }
    expect(health.ok(), 'la API aislada debe estar lista antes de reservar').toBe(true)
  })

  test('reserva dos servicios con el mismo profesional y verifica el contrato creado', async ({
    page
  }) => {
    page.on('requestfailed', (request) => {
      const url = new URL(request.url())
      if (url.origin === apiUrl) {
        console.error(
          `Falló request API aislada: ${request.method()} ${url.pathname} (${request.failure()?.errorText ?? 'sin detalle'})`
        )
      }
    })
    page.on('response', (response) => {
      const url = new URL(response.url())
      if (url.origin === apiUrl && response.status() >= 400) {
        console.error(
          `Respuesta API aislada: ${response.status()} ${response.request().method()} ${url.pathname}`
        )
      }
    })
    await page.goto(`/b/${fixture.storeSlug}`)
    const tituloServicio = page.getByRole('heading', { name: '¿Qué servicio necesitás?' })
    const tituloHorario = page.getByRole('heading', { name: /eleg[ií] fecha y hora/i })
    await expect(tituloServicio).toBeVisible()
    // Encabezado de la tienda (S1, S9): el nombre de la tienda es el h1.
    await expect(page.getByRole('heading', { level: 1 })).toHaveText(storeName)
    // En el celular "Mis turnos" es solo el icono: el nombre accesible sigue
    // siendo el texto y el blanco tactil, de 44 px por lado.
    const misTurnos = page.getByRole('link', { name: 'Mis turnos' })
    await expect(misTurnos).toHaveCSS('min-height', '44px')
    await expect(misTurnos).toHaveCSS('min-width', '44px')
    for (const nombre of ['Términos y condiciones', 'Privacidad']) {
      await expect(page.getByRole('link', { name: nombre })).toHaveCSS('min-height', '44px')
    }
    await sinScrollHorizontal(page, 'servicios')

    await elegirServicios(page)

    const selectedSummary = page.getByTestId('booking-services-bar')
    const totalDuration = fixture.services.reduce(
      (sum, service) => sum + service.durationMinutes,
      0
    )
    const totalPrice = fixture.services.reduce((sum, service) => sum + service.price, 0)
    await expect(selectedSummary).toContainText('2 servicios')
    await expect(selectedSummary).toContainText(`${totalDuration} min`)
    await expect(selectedSummary).toContainText(totalPrice.toLocaleString('es-AR'))
    await selectedSummary.getByRole('button', { name: 'Continuar' }).click()

    await expect(tituloHorario).toBeVisible()
    await sinScrollHorizontal(page, 'horario')
    await elegirPrimerHorario(page, 'el fixture debe ofrecer al menos un horario')
    await waitForBookingFormDwell(page)

    await expect(page.getByPlaceholder('Ej: 351 1234567')).toBeVisible()
    await sinScrollHorizontal(page, 'datos')
    // El turno en una linea (S5): servicios, duracion, horario y quien atiende.
    const summaryLine = page.getByTestId('booking-summary-line')
    await expect(summaryLine).toContainText(`${primaryService.name} + ${extraService.name}`)
    await expect(summaryLine).toContainText(`${totalDuration} min`)
    await expect(summaryLine).toContainText(/\d{2}:\d{2} hs/)
    await expect(summaryLine).toContainText(staffName)
    // El mensaje para la tienda queda plegado hasta que el cliente lo pide.
    await expect(
      page.getByRole('button', { name: 'Agregar un mensaje para la tienda' })
    ).toBeVisible()
    await expect(page.getByPlaceholder('Algo que debamos saber?')).toHaveCount(0)

    await page.getByPlaceholder('Ej: Juan Perez').fill('Cliente QA descartable')
    await page.getByPlaceholder('juan@email.com').fill(`cliente-${runSuffix}@example.com`)
    await page.getByPlaceholder('Ej: 351 1234567').fill(`+54911${runSuffix.slice(-6)}00`)
    await page.getByRole('checkbox', { name: TERMS_CHECKBOX }).check()
    const confirm = await botonDeEnvioEnLaBarra(page)

    const bookingRequest = page.waitForRequest(
      (request) =>
        request.method() === 'POST' &&
        new URL(request.url()).pathname.endsWith('/public/appointments')
    )
    const bookingResponse = page.waitForResponse(
      (response) =>
        response.request().method() === 'POST' &&
        new URL(response.url()).pathname.endsWith('/public/appointments')
    )
    await confirm.click()

    const request = await bookingRequest
    const payload = request.postDataJSON() as {
      service_id?: string
      extra_service_ids?: string[]
      staff_id?: string
    }
    expect(payload.service_id).toBe(primaryService.id)
    expect(payload.extra_service_ids).toEqual([extraService.id])
    expect(payload.staff_id).toBe(fixture.staffId)

    const response = await bookingResponse
    expect(response.status()).toBe(201)
    const responseBody = (await response.json()) as {
      data?: {
        starts_at?: string
        ends_at?: string
        service_price?: number
        extra_services_amount?: number
        final_price?: number
        extra_services?: Array<{ public_id: string }>
      }
      starts_at?: string
      ends_at?: string
      service_price?: number
      extra_services_amount?: number
      final_price?: number
      extra_services?: Array<{ public_id: string }>
    }
    const confirmation = responseBody.data ?? responseBody
    expect(confirmation.extra_services?.map((service) => service.public_id)).toEqual([
      extraService.id
    ])
    expect(confirmation.service_price).toBe(primaryService.price)
    expect(confirmation.extra_services_amount).toBe(extraService.price)
    expect(confirmation.final_price).toBe(totalPrice)
    expect(
      Math.round(
        (Date.parse(confirmation.ends_at ?? '') - Date.parse(confirmation.starts_at ?? '')) / 60_000
      )
    ).toBe(totalDuration)

    await expect(page.getByRole('heading', { name: SUCCESS_HEADING })).toBeVisible({
      timeout: 20_000
    })
    await expect(page.getByText('Detalles del Turno')).toBeVisible()
    await expect(
      page.getByText(`${primaryService.name} + ${extraService.name}`, { exact: true })
    ).toBeVisible()
    await expect(page.getByText('Resumen comercial')).toBeVisible()
    // Ya reservado, la barra de pago no queda tapando la pantalla de exito.
    await expect(page.getByTestId('booking-pay-bar')).toHaveCount(0)
    await sinScrollHorizontal(page, 'confirmación')
  })

  test('mantiene los datos y reintenta un fallo temporal sin marcarlo como horario ocupado', async ({
    page
  }) => {
    const requestBodies: Array<Record<string, unknown>> = []
    let attempts = 0
    let createdBooking: unknown
    await page.route('**/api/public/appointments', async (route) => {
      if (route.request().method() !== 'POST') {
        await route.continue()
        return
      }

      attempts += 1
      requestBodies.push(route.request().postDataJSON() as Record<string, unknown>)
      if (attempts === 1) {
        const upstreamResponse = await route.fetch()
        expect(upstreamResponse.status()).toBe(201)
        createdBooking = await upstreamResponse.json()
        await route.fulfill({
          response: upstreamResponse,
          status: 503,
          contentType: 'application/json',
          body: JSON.stringify({
            success: false,
            error_code: 'SERVICE_UNAVAILABLE',
            message: 'Servicio temporalmente no disponible.'
          })
        })
        return
      }

      await route.continue()
    })

    await page.goto(`/b/${fixture.storeSlug}`)
    await expect(page.getByRole('heading', { name: '¿Qué servicio necesitás?' })).toBeVisible()
    await elegirServicios(page)
    await page
      .getByTestId('booking-services-bar')
      .getByRole('button', { name: 'Continuar' })
      .click()
    await expect(page.getByRole('heading', { name: /elegí fecha y hora/i })).toBeVisible()

    await elegirPrimerHorario(page, 'el fixture debe ofrecer otro horario disponible')
    await waitForBookingFormDwell(page)

    const clientPhone = `+54911${runSuffix.slice(-6)}00`
    await page.getByPlaceholder('Ej: Juan Perez').fill('Cliente QA reintento')
    await page.getByPlaceholder('juan@email.com').fill(`retry-${runSuffix}@example.com`)
    await page.getByPlaceholder('Ej: 351 1234567').fill(clientPhone)
    const terms = page.getByRole('checkbox', { name: TERMS_CHECKBOX })
    await terms.check()

    const confirm = await botonDeEnvioEnLaBarra(page)
    await confirm.click()

    await expect(page.getByText('No pudimos procesar tu reserva. Probá de nuevo.')).toBeVisible()
    await expect(page.getByText(/horario.*ocupad/i)).toHaveCount(0)
    await expect(page.getByPlaceholder('Ej: Juan Perez')).toHaveValue('Cliente QA reintento')
    await expect(page.getByPlaceholder('Ej: 351 1234567')).toHaveValue(clientPhone)
    await expect(terms).toBeChecked()
    // El reintento sale del mismo boton, que sigue siendo el unico envio.
    await botonDeEnvioEnLaBarra(page)
    await expect(confirm).toBeEnabled()

    const retryResponsePromise = page.waitForResponse(
      (response) =>
        response.request().method() === 'POST' &&
        new URL(response.url()).pathname.endsWith('/public/appointments')
    )
    await confirm.click()
    const retryResponse = await retryResponsePromise
    expect(retryResponse.status()).toBe(201)
    expect(await retryResponse.json()).toEqual(createdBooking)
    await expect(page.getByRole('heading', { name: SUCCESS_HEADING })).toBeVisible({
      timeout: 20_000
    })
    await expect(page.getByText('Detalles del Turno')).toBeVisible()

    expect(attempts).toBe(2)
    expect(requestBodies).toHaveLength(2)
    expect(requestBodies[0]?.idempotency_key).toBeTruthy()
    // El reintento manda el mismo pedido y la misma clave; solo cambia el
    // tiempo de llenado del formulario (trampa para bots, #256), que no entra
    // en la clave de idempotencia y crece entre un intento y el otro.
    const sinTiempo = (body: Record<string, unknown> | undefined) =>
      Object.fromEntries(Object.entries(body ?? {}).filter(([key]) => key !== 'form_elapsed_ms'))
    expect(sinTiempo(requestBodies[1])).toEqual(sinTiempo(requestBodies[0]))
    expect(requestBodies[0]?.website).toBe('')
    const [primero, segundo] = requestBodies.map((body) => Number(body.form_elapsed_ms))
    expect(Number.isInteger(primero)).toBe(true)
    expect(segundo).toBeGreaterThanOrEqual(primero ?? 0)
  })
})
