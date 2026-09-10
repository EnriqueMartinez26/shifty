export interface BookingPreselect {
  serviceId: string | null
  staffId: string | null
  /** yyyy-MM-dd (hora argentina); solo si viene con un servicio valido. */
  date: string | null
}

export const EMPTY_PRESELECT: BookingPreselect = { serviceId: null, staffId: null, date: null }

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/

/**
 * Resuelve `?service=&staff=&date=` de la URL contra las listas publicas: un
 * id que no existe (servicio dado de baja, profesional de otra tienda) se
 * ignora en vez de arrancar el wizard sobre algo que no se puede reservar. El
 * profesional solo vale si el servicio tambien vale, porque la lista de
 * profesionales depende del servicio. La fecha solo se acepta con formato
 * yyyy-MM-dd; el paso de horario decide si ya paso.
 */
export const resolveBookingPreselect = (
  wanted: { service: string | null; staff: string | null; date?: string | null },
  services: ReadonlyArray<{ public_id: string }> | undefined,
  staff: ReadonlyArray<{ public_id: string }> | undefined
): BookingPreselect => {
  const serviceId =
    wanted.service && services?.some((s) => s.public_id === wanted.service) ? wanted.service : null
  if (!serviceId) return EMPTY_PRESELECT
  const staffId =
    wanted.staff && staff?.some((s) => s.public_id === wanted.staff) ? wanted.staff : null
  const date = wanted.date && DATE_RE.test(wanted.date) ? wanted.date : null
  return { serviceId, staffId, date }
}

/** Paso inicial del wizard: 0 servicio, 1 profesional, 2 horario. */
export const initialStepFor = (preselect: BookingPreselect): number => {
  if (!preselect.serviceId) return 0
  return preselect.staffId ? 2 : 1
}
