/**
 * `error_code` del backend -> texto para el usuario.
 *
 * Neutro a proposito (regla 20): el mensaje crudo del servidor puede traer
 * datos internos (el motivo de un bloqueo de agenda, el texto de un
 * ValueError, el nombre de un permiso). Cada codigo existe en `backend/`; uno
 * que no esta aca cae en el mensaje del servidor solo si es un 4xx
 * operacional, y si no en el fallback de la pantalla (ver getErrorMessage).
 */
export const ERROR_CODE_MESSAGES: ReadonlyMap<string, string> = new Map([
  // Estado del turno: la vista quedo vieja respecto del servidor.
  [
    'INVALID_STATUS_TRANSITION',
    'El turno ya cambió de estado. Actualizá la agenda para ver cómo está ahora.'
  ],
  [
    'CONCURRENT_MODIFICATION',
    'Alguien más modificó este turno mientras lo editabas. Actualizá y volvé a intentar.'
  ],
  // Solo lo emite la API publica (el cliente cancelando o moviendo su turno):
  // mandarlo a "Liberar", un boton del panel, no le servia de nada.
  [
    'PAYMENT_APPOINTMENT_REQUIRES_RELEASE',
    'Este turno tiene un pago en curso. Para cancelarlo o cambiarlo, comunicate con el negocio.'
  ],
  ['DEPOSIT_PENDING_RESCHEDULE_DENIED', 'Cobrá la seña o cancelá el turno antes de moverlo.'],
  // Cancelar desde el panel (D-20260929-05): lo que empezo se completa o se
  // marca ausente, no se cancela.
  [
    'APPOINTMENT_ALREADY_STARTED',
    'El turno ya empezó: no se puede cancelar. Completalo o marcá la ausencia.'
  ],
  ['APPOINTMENT_ALREADY_CANCELLED', 'El turno ya estaba cancelado. Actualizá la agenda.'],
  [
    'APPOINTMENT_NOT_ACTIVE',
    'El turno ya terminó o fue cancelado: no se puede mover. Actualizá la agenda.'
  ],
  // Reserva y reprogramacion.
  ['APPOINTMENT_CONFLICT', 'Ese horario ya no está disponible. Elegí otro.'],
  ['SCHEDULE_BLOCKED', 'Ese horario está bloqueado en la agenda. Elegí otro.'],
  ['OUT_OF_SCHEDULE', 'El profesional no atiende en ese horario. Elegí otro.'],
  ['NO_STAFF_AVAILABLE', 'No hay profesionales disponibles en ese horario. Elegí otro.'],
  [
    'IDEMPOTENCY_IN_PROGRESS',
    'La operación ya se está procesando. Esperá unos segundos y revisá antes de reintentar.'
  ],
  // Cuenta, permisos y limites.
  [
    'SUBSCRIPTION_SUSPENDED',
    'Tu suscripción está suspendida: renovala para volver a operar. Mientras tanto podés ver tu información.'
  ],
  ['FEATURE_DISABLED', 'Esta función no está habilitada para tu negocio.'],
  ['PERMISSION_DENIED', 'No tenés permiso para hacer esto.'],
  ['RATE_LIMITED', 'Hiciste demasiados intentos seguidos. Esperá un momento y volvé a intentar.'],
  [
    'RATE_LIMIT_UNAVAILABLE',
    'El servicio no está disponible en este momento. Probá de nuevo en unos minutos.'
  ],
  [
    'RESOURCE_CONFLICT',
    'Los datos chocan con un registro existente. Revisalos y volvé a intentar.'
  ],
  // Reportes.
  ['EXPORT_TOO_LARGE', 'El reporte es demasiado grande para exportarlo. Acotá el rango de fechas.'],
  // Imagenes (logo, portada, foto de servicio).
  ['EMPTY_MEDIA', 'El archivo está vacío.'],
  ['MEDIA_TOO_LARGE', 'La imagen supera el tamaño máximo permitido.'],
  ['REQUEST_TOO_LARGE', 'El archivo supera el tamaño máximo permitido.'],
  ['UNSUPPORTED_MEDIA_TYPE', 'Formato no permitido. Subí una imagen PNG, JPEG o WebP.'],
  ['INVALID_IMAGE', 'No pudimos leer la imagen. Probá exportarla de nuevo como PNG, JPEG o WebP.'],
  ['IMAGE_TOO_LARGE_DIMENSIONS', 'La imagen tiene demasiados píxeles. Achicala y volvé a subirla.']
])
