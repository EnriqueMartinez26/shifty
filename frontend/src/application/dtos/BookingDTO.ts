export interface AppointmentResponseDTO {
  public_id: string
  service_id: string
  service_name: string
  staff_id: string
  // Nombre autoritativo del profesional (viene del join en el backend). Opcional
  // para tolerar payloads que aun no lo traigan.
  staff_name?: string | null
  client_name: string
  // Solo lo manda el backend a administradores; el resto recibe null.
  client_phone?: string | null
  /**
   * El turno tiene un email entregable (no el tecnico .noreply de una reserva
   * sin email). Ausente en respuestas viejas: se asume que si.
   */
  client_has_email?: boolean | null
  starts_at: string
  ends_at: string
  status: string
  notes: string | null
  /** Adicionales del turno: solo nombre y cantidad (recepcion no ve importes). */
  addons?: { name: string; quantity: number }[] | null
  /** Servicios sumados al principal en el mismo turno (vacio si no hay). */
  extra_services?: { public_id: string; name: string; duration_minutes: number }[] | null
  /** "Corte + Barba"; ausente en una respuesta vieja. */
  services_label?: string | null
}
