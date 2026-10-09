/* istanbul ignore file */

/**
 * Punto unico de acceso a los flags de entorno de Vite (`import.meta.env`).
 *
 * `import.meta` es sintaxis solo-ESM: ts-jest transpila a CommonJS y rompe al
 * verla en archivos de `src`. Por eso se centraliza aca y se mockea en el setup
 * de Jest (ver src/test/setup.ts), igual que runtime-env. El resto del codigo
 * consume estas funciones en vez de tocar `import.meta` directo.
 */

export const isProduction = (): boolean => import.meta.env.PROD

/** Vacío o inválido: no se carga Google Analytics ni se muestra el aviso. */
export const getGa4MeasurementId = (): string | undefined =>
  import.meta.env.VITE_GA4_MEASUREMENT_ID as string | undefined

/**
 * Contacto de Shifty, crudo, tal como llega del build (build args de
 * frontend/Dockerfile, que CI llena con variables del repo en GitHub). Los
 * valores reales no van al repo, que es publico. Lo valida y normaliza
 * shared/utils/contactInfo.ts; ningun otro modulo lo lee.
 */
export interface ContactEnv {
  /** VITE_SUPPORT_WHATSAPP: solo digitos, con codigo de pais (549...). */
  supportWhatsApp?: string
  /** VITE_CONTACT_EMAIL. */
  contactEmail?: string
  /** VITE_LEGAL_RESPONSABLES: texto libre, uno o mas nombres completos. */
  legalResponsables?: string
}

export const getContactEnv = (): ContactEnv => ({
  supportWhatsApp: import.meta.env.VITE_SUPPORT_WHATSAPP as string | undefined,
  contactEmail: import.meta.env.VITE_CONTACT_EMAIL as string | undefined,
  legalResponsables: import.meta.env.VITE_LEGAL_RESPONSABLES as string | undefined
})
