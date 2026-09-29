import {
  PaymentRequiredError,
  RateLimitError,
  ServiceUnavailableError,
  UnauthorizedError
} from '@shared/errors'
import { ForbiddenError } from '@shared/errors/ForbiddenError'

import {
  ForbiddenErrorHandler,
  TransientErrorHandler,
  UnauthorizedErrorHandler
} from './SpecificHandlers'

describe('ForbiddenErrorHandler', () => {
  let warn: jest.SpyInstance

  beforeEach(() => {
    warn = jest.spyOn(console, 'warn').mockImplementation(() => {})
  })

  afterEach(() => {
    warn.mockRestore()
  })

  it('una funcion apagada por feature flag no se anuncia como falta de permisos', async () => {
    // Forma real: FeatureDisabledException -> 403 con error_code FEATURE_DISABLED,
    // que normalizeApiError deja en context.errorCode.
    const error = new ForbiddenError('Funcionalidad no disponible: deuda.', {
      errorCode: 'FEATURE_DISABLED',
      statusCode: 403
    })

    await new ForbiddenErrorHandler().handle(error)

    expect(warn).toHaveBeenCalledWith(
      '[Toast INFO]: Esta función no está habilitada para tu negocio.'
    )
  })

  it('cualquier otro 403 sigue diciendo que faltan permisos', async () => {
    const error = new ForbiddenError('No tiene permiso para ver deudas.', {
      errorCode: 'PERMISSION_DENIED',
      statusCode: 403
    })

    await new ForbiddenErrorHandler().handle(error)

    expect(warn).toHaveBeenCalledWith(
      '[Toast ERROR]: No tienes permisos suficientes para realizar esta acción.'
    )
  })
})

describe('TransientErrorHandler (402, 429, 502/503)', () => {
  it('avisa con el texto neutro, nunca con el del servidor', async () => {
    const warn = jest.spyOn(console, 'warn').mockImplementation(() => {})
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

    const avisos = warn.mock.calls.map(([texto]) => String(texto))
    expect(avisos[0]).toContain('Tu suscripción está suspendida')
    expect(avisos.join()).not.toContain(crudo)
    warn.mockRestore()
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
    const warn = jest.spyOn(console, 'warn').mockImplementation(() => {})
    localStorage.setItem('shifty_user', '{"public_id":"usr-a"}')
    const antes = window.location.href
    const handler = new UnauthorizedErrorHandler()

    expect(handler.canHandle(new UnauthorizedError('x'))).toBe(true)
    await handler.handle(new UnauthorizedError('x'))

    expect(warn).toHaveBeenCalledWith(expect.stringContaining('Sesión expirada'))
    expect(localStorage.getItem('shifty_user')).not.toBeNull()
    expect(window.location.href).toBe(antes)
    warn.mockRestore()
    localStorage.clear()
  })
})
