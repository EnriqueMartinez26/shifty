import { ForbiddenErrorHandler } from './SpecificHandlers'
import { ForbiddenError } from '../ForbiddenError'

// Solo lo usa el handler de 401; el cliente real arrastra `import.meta`.
jest.mock('@infrastructure/http/client', () => ({ setAuthToken: jest.fn() }))

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
