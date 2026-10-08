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
  // POST /staff/me: la cuenta ya figura en la agenda (otra pestana la agrego).
  ['STAFF_SELF_ALREADY_EXISTS', 'Ya figurás como profesional. Actualizá la lista del personal.'],
  // PUT /staff/{id} sobre la propia ficha: el email de login no cambia sin la
  // contrasena (mismo criterio que SELF_PASSWORD_CHANGE_DENIED en /users/).
  ['SELF_EMAIL_CHANGE_DENIED', 'Tu email de acceso no se cambia desde Personal.'],
  ['STAFF_SELF_GLOBAL_ADMIN_DENIED', 'La cuenta SuperAdmin no se agrega como profesional.'],
  // Solo lo emite la reprogramacion del cliente (public_api/service.py). Sin
  // BOOKING_NOTICE_REQUIRED ni CANCELLATION_WINDOW_EXPIRED a proposito: el
  // texto del servidor dice cuantas horas pide la tienda (FF-06).
  [
    'PAID_APPOINTMENT_RESCHEDULE_DENIED',
    'Este turno ya tiene un pago registrado. Para cambiarlo, comunicate con el negocio.'
  ],
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
  // Regla 14 (backend/modules/users/guards.py). El panel corta antes la
  // propia cuenta (D-20260930-05); "ultimo SuperAdmin activo" solo lo sabe
  // el backend.
  ['SELF_SUPERADMIN_DEACTIVATION_DENIED', 'No podés desactivar tu propia cuenta de SuperAdmin.'],
  ['LAST_SUPERADMIN_DEACTIVATION_DENIED', 'No se puede desactivar al último SuperAdmin activo.'],
  ['SELF_SUPERADMIN_REVOCATION_DENIED', 'No podés revocar tu propio permiso de SuperAdmin.'],
  ['LAST_SUPERADMIN_REVOCATION_DENIED', 'No se puede revocar al último SuperAdmin activo.'],
  // core/roles.py::assert_client_not_global_admin. El panel no ofrece el boton.
  ['CLIENT_GLOBAL_ADMIN_DENIED', 'Una cuenta de cliente no puede ser SuperAdmin.'],
  ['RATE_LIMITED', 'Hiciste demasiados intentos seguidos. Esperá un momento y volvé a intentar.'],
  // Lo arma el front: una lectura que vencio su timeout de 15 s (D-20260930-02).
  ['REQUEST_TIMEOUT', 'La consulta tardó demasiado. Probá de nuevo.'],
  // Tope de codigos por telefono (OTP_MAX_REQUESTS_PER_HOUR): la ventana es
  // deslizante, asi que no se promete una espera concreta (F4-11).
  [
    'OTP_RATE_LIMITED',
    'Pediste demasiados códigos para este teléfono. Esperá un rato antes de pedir otro.'
  ],
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

/**
 * Textos exactos de un 422 VALIDATION_ERROR de negocio -> texto para el
 * usuario. El texto del servidor de ese codigo no se muestra nunca (regla 20,
 * SERVER_TEXT_DENYLIST); los que el usuario si necesita entender se
 * traducen aca, por igualdad exacta: uno parecido sigue en el fallback.
 */
export const VALIDATION_MESSAGES: ReadonlyMap<string, string> = new Map([
  // staff/repository.py y superadmin/repository.py, alta o edicion con un
  // email de login ya usado (QA movil 2026-10-08: el modal decia "No se pudo
  // guardar" y el motivo solo llegaba a la consola).
  ['Ya existe un usuario con ese email', 'Ese email ya lo usa otra cuenta. Usá otro email.']
])
