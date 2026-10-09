import { ConflictError } from './ConflictError'
import { ForbiddenError } from './ForbiddenError'
import {
  getErrorCode,
  getErrorMessage,
  getHttpStatus,
  getInvalidFields,
  isStateConflictError
} from './getErrorMessage'
import { InternalServerError } from './InternalServerError'
import { NetworkError } from './NetworkError'
import { ServiceUnavailableError } from './ServiceUnavailableError'
import { UnauthorizedError } from './UnauthorizedError'
import { ValidationError } from './ValidationError'

const FALLBACK = 'No se pudo guardar'

// Asi llega un error del backend despues de normalizeApiError (FF-02: antes
// se leia `response.data.error_code`, que el cliente HTTP ya no deja).
const conflict = (errorCode: string, message = 'texto del servidor') =>
  new ConflictError(message, { errorCode, statusCode: 409 })

// BaseService envuelve lo que no es ApplicationError en un Error plano.
const wrapped = (originalError: unknown) =>
  Object.assign(new Error('Ocurrió un error inesperado en la operación.'), { originalError })

describe('getErrorMessage', () => {
  it('traduce DEPOSIT_PENDING_RESCHEDULE_DENIED al texto accionable', () => {
    expect(getErrorMessage(conflict('DEPOSIT_PENDING_RESCHEDULE_DENIED'), FALLBACK)).toBe(
      'Cobrá la seña o cancelá el turno antes de moverlo.'
    )
  })

  // Revision de #133 (2026-10-08): el email de acceso propio no se cambia por
  // Personal y la cuenta SuperAdmin no se agrega como profesional.
  it.each([
    [
      'SELF_EMAIL_CHANGE_DENIED',
      new ValidationError('x', { errorCode: 'SELF_EMAIL_CHANGE_DENIED', statusCode: 400 }),
      'Tu email de acceso no se cambia desde Personal.'
    ],
    [
      'STAFF_SELF_GLOBAL_ADMIN_DENIED',
      new ForbiddenError('x', { errorCode: 'STAFF_SELF_GLOBAL_ADMIN_DENIED', statusCode: 403 }),
      'La cuenta SuperAdmin no se agrega como profesional.'
    ]
  ])('traduce %s', (_code, error, texto) => {
    expect(getErrorMessage(error, FALLBACK)).toBe(texto)
  })

  it('un VALIDATION_ERROR devuelve el fallback, nunca el texto de Pydantic', () => {
    const pydantic = 'body -> email: value is not a valid email address'
    const error = new ValidationError(pydantic, { errorCode: 'VALIDATION_ERROR', statusCode: 422 })

    const message = getErrorMessage(error, FALLBACK)

    expect(message).toBe(FALLBACK)
    expect(message).not.toContain('email')
  })

  it('el override de la pantalla le gana a la tabla', () => {
    const message = getErrorMessage(conflict('APPOINTMENT_CONFLICT'), FALLBACK, {
      APPOINTMENT_CONFLICT: 'Ese horario se ocupó recién.'
    })

    expect(message).toBe('Ese horario se ocupó recién.')
  })

  it('un override de otro codigo no tapa la tabla', () => {
    const message = getErrorMessage(conflict('SCHEDULE_BLOCKED'), FALLBACK, {
      APPOINTMENT_CONFLICT: 'otro'
    })

    expect(message).toBe('Ese horario está bloqueado en la agenda. Elegí otro.')
  })

  it('encuentra el codigo aunque venga envuelto en originalError', () => {
    const error = wrapped(conflict('CONCURRENT_MODIFICATION'))

    expect(getErrorCode(error)).toBe('CONCURRENT_MODIFICATION')
    expect(getErrorMessage(error, FALLBACK)).toBe(
      'Alguien más modificó este turno mientras lo editabas. Actualizá y volvé a intentar.'
    )
  })

  it('muestra el mensaje del servidor de un 4xx operacional sin codigo conocido', () => {
    const error = new UnauthorizedError('Email o contraseña incorrectos', {
      errorCode: 'AUTHENTICATION_FAILED',
      statusCode: 401
    })

    expect(getErrorMessage(error, FALLBACK)).toBe('Email o contraseña incorrectos')
  })

  it('usa el mensaje del ApplicationError envuelto por BaseService', () => {
    const error = wrapped(new ForbiddenError('Solo el dueño puede hacer esto', { statusCode: 403 }))

    expect(getErrorMessage(error, FALLBACK)).toBe('Solo el dueño puede hacer esto')
  })

  it.each([
    ['un 500', new InternalServerError('Error interno del servidor', { statusCode: 500 })],
    [
      'un 503 sin codigo conocido',
      new ServiceUnavailableError('upstream timeout', { statusCode: 503 })
    ],
    ['un 4xx con HTTP_ERROR', new ValidationError('Bad Request', { errorCode: 'HTTP_ERROR' })],
    ['un Error plano', new Error("Database operation 'x' failed: boom")],
    ['algo que no es un error', 'boom'],
    ['null', null]
  ])('%s cae en el fallback', (_caso, error) => {
    expect(getErrorMessage(error, FALLBACK)).toBe(FALLBACK)
  })

  it('un ApplicationError con mensaje vacio cae en el fallback', () => {
    expect(getErrorMessage(new ConflictError('  ', { statusCode: 409 }), FALLBACK)).toBe(FALLBACK)
  })

  it('la falla de red conserva su texto, que es del front', () => {
    const error = new NetworkError('No se pudo conectar con el servidor.')

    expect(getErrorMessage(error, FALLBACK)).toBe('No se pudo conectar con el servidor.')
  })

  it('un 422 con codigo de la tabla usa la tabla aunque la clase sea ValidationError', () => {
    const error = new ValidationError("No se puede pasar de 'cancelled' a 'confirmed'.", {
      errorCode: 'INVALID_STATUS_TRANSITION',
      statusCode: 422
    })

    expect(getErrorMessage(error, FALLBACK)).toBe(
      'El turno ya cambió de estado. Actualizá la agenda para ver cómo está ahora.'
    )
  })
})

describe('isStateConflictError', () => {
  it.each([
    'INVALID_STATUS_TRANSITION',
    'CONCURRENT_MODIFICATION',
    'PAYMENT_APPOINTMENT_REQUIRES_RELEASE'
  ])('detecta %s en el error normalizado', (code) => {
    expect(isStateConflictError(conflict(code))).toBe(true)
  })

  it('detecta el conflicto envuelto por BaseService', () => {
    expect(isStateConflictError(wrapped(conflict('INVALID_STATUS_TRANSITION')))).toBe(true)
  })

  it('no confunde otros codigos ni errores sin codigo', () => {
    expect(isStateConflictError(conflict('APPOINTMENT_CONFLICT'))).toBe(false)
    expect(isStateConflictError(new Error('x'))).toBe(false)
    expect(isStateConflictError(undefined)).toBe(false)
  })
})

describe('getErrorCode', () => {
  it('ignora un errorCode que no es texto', () => {
    expect(getErrorCode(new ConflictError('x', { errorCode: 42 }))).toBeUndefined()
    expect(getErrorCode(wrapped('no es objeto'))).toBeUndefined()
  })
})

describe('getHttpStatus', () => {
  it('prefiere el status real del contexto al de la clase', () => {
    expect(getHttpStatus(new ValidationError('x', { statusCode: 422 }))).toBe(422)
    expect(getHttpStatus(new ValidationError('x'))).toBe(400)
  })

  it('devuelve undefined si no hay ApplicationError', () => {
    expect(getHttpStatus(new Error('x'))).toBeUndefined()
  })
})

// 2026-10-02, QA en navegador: un 422 de Pydantic terminaba en el fallback
// generico de cada pantalla ("No se pudo registrar el movimiento") sin decir
// que campo fallo. El campo sale del `detail` (lista "campo: motivo") y la
// pantalla trae su propio texto: el motivo crudo de Pydantic nunca se muestra.
describe('getErrorMessage: errores de validacion por campo', () => {
  const pydantic422 = (...detail: string[]) =>
    new ValidationError(detail.join('; '), {
      errorCode: 'VALIDATION_ERROR',
      statusCode: 422,
      detail
    })

  it('nombra el campo invalido con el texto de la pantalla', () => {
    const error = pydantic422('amount: Input should be greater than or equal to 0')

    expect(getInvalidFields(error)).toEqual(['amount'])
    expect(getErrorMessage(error, FALLBACK, {}, { amount: 'Revisá el monto.' })).toBe(
      'Revisá el monto.'
    )
  })

  it('toma el ultimo tramo de la ruta y saltea los indices de lista', () => {
    const error = pydantic422('query -> limit: too big', 'items -> 0 -> name: required')

    expect(getInvalidFields(error)).toEqual(['limit', 'name'])
  })

  it('tambien encuentra el campo dentro de un error envuelto por BaseService', () => {
    const error = wrapped(pydantic422('client_phone: String should have at least 8 characters'))

    expect(
      getErrorMessage(error, FALLBACK, {}, { client_phone: 'El teléfono es muy corto.' })
    ).toBe('El teléfono es muy corto.')
  })

  it('sin un campo conocido cae en el fallback, no en el texto del servidor', () => {
    const error = pydantic422('otro: value is not valid')

    expect(getErrorMessage(error, FALLBACK, {}, { amount: 'Revisá el monto.' })).toBe(FALLBACK)
  })

  it('el override por codigo le gana al texto por campo', () => {
    const error = pydantic422('amount: bad')

    expect(
      getErrorMessage(
        error,
        FALLBACK,
        { VALIDATION_ERROR: 'Datos inválidos.' },
        { amount: 'Revisá el monto.' }
      )
    ).toBe('Datos inválidos.')
  })

  it('un detail que no es lista (ValidationException de negocio) sin campo no trae campos', () => {
    const error = new ValidationError('Ese movimiento ya fue revertido.', {
      errorCode: 'VALIDATION_ERROR',
      statusCode: 422,
      detail: { campo: 'x' }
    })

    expect(getInvalidFields(error)).toEqual([])
  })

  // 2026-10-02, QA en navegador (S\43): una sena de mas de 100% decia un
  // mensaje generico. El campo viene en el mensaje del model_validator (al
  // crear) o de la ValidationException (al editar).
  // Revision R3: un mensaje de negocio con dos puntos no inventa un campo.
  it('un mensaje de negocio con dos puntos no nombra un campo', () => {
    const error = new ValidationError('Horario no disponible: elegi otro', {
      errorCode: 'VALIDATION_ERROR',
      statusCode: 422,
      detail: {}
    })

    expect(getInvalidFields(error)).toEqual([])
  })

  it('lee el campo de un model_validator y de una ValidationException de negocio', () => {
    const alCrear = pydantic422(
      'Value error, deposit_amount: un porcentaje de sena no puede superar 100'
    )
    const alEditar = new ValidationError(
      'deposit_amount: un porcentaje de sena no puede superar 100',
      { errorCode: 'VALIDATION_ERROR', statusCode: 422, detail: {} }
    )

    expect(getInvalidFields(alCrear)).toEqual(['deposit_amount'])
    expect(getInvalidFields(alEditar)).toEqual(['deposit_amount'])
  })
})

// QA movil 2026-10-08: el alta de un profesional con un email ya usado
// responde 422 VALIDATION_ERROR "Ya existe un usuario con ese email"
// (staff/repository.py) y el modal decia solo "No se pudo guardar".
describe('getErrorMessage - textos de validacion conocidos', () => {
  const duplicado = new ValidationError('Ya existe un usuario con ese email', {
    errorCode: 'VALIDATION_ERROR',
    statusCode: 422,
    detail: {}
  })

  it('el email duplicado sale con un texto propio, no con el fallback', () => {
    expect(getErrorMessage(duplicado, FALLBACK)).toBe(
      'Ese email ya lo usa otra cuenta. Usá otro email.'
    )
  })

  it('tambien envuelto en originalError', () => {
    expect(getErrorMessage(wrapped(duplicado), FALLBACK)).toBe(
      'Ese email ya lo usa otra cuenta. Usá otro email.'
    )
  })

  it('el override de la pantalla le sigue ganando', () => {
    expect(getErrorMessage(duplicado, FALLBACK, { VALIDATION_ERROR: 'otro texto' })).toBe(
      'otro texto'
    )
  })

  it('un VALIDATION_ERROR con otro texto sigue en el fallback', () => {
    const otro = new ValidationError('Ya existe un usuario con ese email y algo mas', {
      errorCode: 'VALIDATION_ERROR',
      statusCode: 422
    })
    expect(getErrorMessage(otro, FALLBACK)).toBe(FALLBACK)
  })
})
