import {
  type ApplicationError,
  ConflictError,
  InternalServerError,
  NetworkError,
  NotFoundError,
  PaymentRequiredError,
  RateLimitError,
  RequestCanceledError,
  RequestTimeoutError,
  ServiceUnavailableError,
  UnauthorizedError,
  ValidationError
} from '@shared/errors'
import type { ErrorHandler } from '@shared/errors/ErrorHandler'
import { ForbiddenError } from '@shared/errors/ForbiddenError'

import {
  ConflictErrorHandler,
  ForbiddenErrorHandler,
  InternalServerErrorHandler,
  NetworkErrorHandler,
  NotFoundErrorHandler,
  setToastSink,
  TransientErrorHandler,
  UnauthorizedErrorHandler,
  ValidationErrorHandler
} from './SpecificHandlers'

/**
 * 2026-09-28 (FF-17). `showToast` era un `console.warn`: el usuario no veia
 * ningun aviso de los handlers globales. Ahora escriben en un puerto que
 * main.tsx conecta a sonner; aca el puerto es un doble.
 */
const sink = jest.fn()

beforeEach(() => {
  sink.mockReset()
  setToastSink(sink)
})

const CRUDO = 'sqlalchemy: duplicate key value violates "uq_users_email"'

describe('handlers globales: avisan por el puerto, nunca con el texto del servidor', () => {
  it.each<[string, ErrorHandler, ApplicationError]>([
    [
      'ValidationError',
      new ValidationErrorHandler(),
      new ValidationError(CRUDO, {
        statusCode: 422,
        errorCode: 'VALIDATION_ERROR',
        fields: { email: CRUDO }
      })
    ],
    ['NotFoundError', new NotFoundErrorHandler(), new NotFoundError(CRUDO, { statusCode: 404 })],
    ['ConflictError', new ConflictErrorHandler(), new ConflictError(CRUDO, { statusCode: 409 })],
    ['InternalServerError', new InternalServerErrorHandler(), new InternalServerError(CRUDO)],
    ['NetworkError', new NetworkErrorHandler(), new NetworkError(CRUDO)]
  ])('%s', async (_nombre, handler, error) => {
    jest.spyOn(console, 'error').mockImplementation(() => {})

    expect(handler.canHandle(error)).toBe(true)
    await handler.handle(error)

    expect(sink).toHaveBeenCalledTimes(1)
    const [texto] = sink.mock.calls[0] as [string, string]
    expect(texto.trim()).not.toBe('')
    expect(texto).not.toContain('sqlalchemy')
    jest.restoreAllMocks()
  })

  it('un codigo conocido usa el texto de la tabla', async () => {
    await new ConflictErrorHandler().handle(
      new ConflictError(CRUDO, { errorCode: 'APPOINTMENT_CONFLICT', statusCode: 409 })
    )

    expect(sink).toHaveBeenCalledWith('Ese horario ya no está disponible. Elegí otro.', 'warning')
  })
})

describe('ForbiddenErrorHandler', () => {
  it('una funcion apagada por feature flag no se anuncia como falta de permisos', async () => {
    // Forma real: FeatureDisabledException -> 403 con error_code FEATURE_DISABLED,
    // que normalizeApiError deja en context.errorCode.
    const error = new ForbiddenError('Funcionalidad no disponible: deuda.', {
      errorCode: 'FEATURE_DISABLED',
      statusCode: 403
    })

    await new ForbiddenErrorHandler().handle(error)

    expect(sink).toHaveBeenCalledWith('Esta función no está habilitada para tu negocio.', 'info')
  })

  it('cualquier otro 403 sigue diciendo que faltan permisos', async () => {
    const error = new ForbiddenError('No tiene permiso para ver deudas.', {
      errorCode: 'PERMISSION_DENIED',
      statusCode: 403
    })

    await new ForbiddenErrorHandler().handle(error)

    expect(sink).toHaveBeenCalledWith(
      'No tenés permisos suficientes para realizar esta acción.',
      'error'
    )
  })
})

describe('TransientErrorHandler (402, 429, 502/503)', () => {
  it('avisa con el texto neutro, nunca con el del servidor', async () => {
    const crudo = 'upstream: pool exhausted'
    const handler = new TransientErrorHandler()
    const errores = [
      new PaymentRequiredError(crudo, { errorCode: 'SUBSCRIPTION_SUSPENDED' }),
      new RateLimitError(crudo),
      new ServiceUnavailableError(crudo)
    ]

    for (const error of errores) {
      expect(handler.canHandle(error)).toBe(true)
      await handler.handle(error)
    }

    const avisos = sink.mock.calls.map(([texto]) => String(texto))
    expect(avisos[0]).toContain('Tu suscripción está suspendida')
    expect(avisos.join()).not.toContain(crudo)
  })

  it('una lectura vencida avisa con su propio texto, no como falta de red (D-20260930-02)', async () => {
    // F4-04 b (2026-10-01): el refresco de una pantalla que vencia su timeout
    // no tenia aviso propio.
    const timeout = new RequestTimeoutError('x', { errorCode: 'REQUEST_TIMEOUT', statusCode: 0 })

    expect(new NetworkErrorHandler().canHandle(timeout)).toBe(false)
    expect(new TransientErrorHandler().canHandle(timeout)).toBe(true)
    await new TransientErrorHandler().handle(timeout)

    expect(sink).toHaveBeenCalledWith('La consulta tardó demasiado. Probá de nuevo.', 'warning')
  })

  it('una consulta cancelada no es ni falta de red ni un aviso transitorio', () => {
    // 2026-10-02: una consulta cancelada por react-query se reportaba como
    // error de red a Sentry y se anunciaba "Sin conexion a Internet".
    const canceled = new RequestCanceledError('x', {
      errorCode: 'REQUEST_CANCELED',
      statusCode: 0
    })

    expect(new NetworkErrorHandler().canHandle(canceled)).toBe(false)
    expect(new TransientErrorHandler().canHandle(canceled)).toBe(false)
    expect(new InternalServerErrorHandler().canHandle(canceled)).toBe(false)
  })

  it('con Retry-After dice en cuanto probar de nuevo (F4-04)', async () => {
    await new TransientErrorHandler().handle(
      new RateLimitError('x', { errorCode: 'RATE_LIMITED', retryAfter: 12 })
    )

    expect(sink).toHaveBeenCalledWith(expect.stringContaining('Probá de nuevo en 12 s.'), 'warning')
  })

  it('un Retry-After largo se dice en minutos', async () => {
    await new TransientErrorHandler().handle(new ServiceUnavailableError('x', { retryAfter: 600 }))

    expect(sink).toHaveBeenCalledWith(
      expect.stringContaining('Probá de nuevo en 10 min.'),
      'warning'
    )
  })

  it('sin Retry-After no inventa una espera', async () => {
    await new TransientErrorHandler().handle(new RateLimitError('x'))

    expect(sink).toHaveBeenCalledWith(expect.not.stringContaining(' s.'), 'warning')
  })
})

/**
 * 2026-09-28 (FF-26, FF-36). El handler limpiaba el token y recargaba a /login
 * con `window.location.href`: perdia la ruta y, en el portal publico, mandaba
 * a /login a quien no tenia sesion. La limpieza de sesion y cache ahora vive
 * en AuthContext.resetSession (ver AuthContext.test.tsx); aca solo se avisa.
 */
describe('UnauthorizedErrorHandler', () => {
  it('solo avisa: no toca el perfil guardado ni recarga la pagina', async () => {
    localStorage.setItem('shifty_user', '{"public_id":"usr-a"}')
    const antes = window.location.href
    const handler = new UnauthorizedErrorHandler()

    expect(handler.canHandle(new UnauthorizedError('x'))).toBe(true)
    await handler.handle(new UnauthorizedError('x'))

    expect(sink).toHaveBeenCalledWith(expect.stringContaining('Sesión expirada'), 'info')
    expect(localStorage.getItem('shifty_user')).not.toBeNull()
    expect(window.location.href).toBe(antes)
    localStorage.clear()
  })
})
