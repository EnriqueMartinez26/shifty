/**
 * Contacto de Shifty: responsables, email y WhatsApp de soporte.
 *
 * Los valores reales no viven en el repo (es publico y el WhatsApp es un
 * telefono personal): llegan como build args de frontend/Dockerfile, que CI
 * llena con variables del repo en GitHub (docs/DEPLOY_RUNBOOK.md, seccion 2).
 * Un valor ausente, invalido o con forma de placeholder es `null`: la pantalla
 * omite esa linea en vez de mostrar texto de relleno o un link roto.
 */

import { getContactEnv, type ContactEnv } from './env'
import { buildWaMeUrl, normalizePhoneForWhatsApp } from './whatsAppPhone'

export interface ContactInfo {
  /** Uno o mas nombres completos, tal como se configuraron. */
  responsables: string | null
  email: string | null
  /** Numero para wa.me: solo digitos, con codigo de pais. */
  whatsAppNumber: string | null
}

// Lo que quedo de una plantilla sin completar no es un dato.
const PLACEHOLDER = /\[\[|\]\]|^(pendiente|completar|todo|tbd|placeholder|change_?me)$/i
// Forma de un email, sin espacios ni separadores de lista. No intenta
// cubrir todo RFC 5322: es configuracion propia, no entrada de un usuario.
const EMAIL = /^[^\s@<>(),;:"]+@[^\s@<>(),;:"]+\.[^\s@<>(),;:".]{2,}$/
const MAX_EMAIL_LENGTH = 254
const MAX_RESPONSABLES_LENGTH = 300

const configured = (raw: string | undefined): string | null => {
  const value = (raw ?? '').trim()
  return value && !PLACEHOLDER.test(value) ? value : null
}

const validEmail = (raw: string | undefined): string | null => {
  const value = configured(raw)
  return value && value.length <= MAX_EMAIL_LENGTH && EMAIL.test(value) ? value : null
}

const validResponsables = (raw: string | undefined): string | null => {
  const value = configured(raw)
  return value && value.length <= MAX_RESPONSABLES_LENGTH ? value : null
}

export const parseContactInfo = (env: ContactEnv): ContactInfo => ({
  responsables: validResponsables(env.legalResponsables),
  email: validEmail(env.contactEmail),
  whatsAppNumber: normalizePhoneForWhatsApp(configured(env.supportWhatsApp))
})

export const getContactInfo = (): ContactInfo => parseContactInfo(getContactEnv())

/** Link wa.me al soporte con el texto prearmado, o null si no hay numero valido. */
export const supportWhatsAppUrl = (text: string): string | null =>
  buildWaMeUrl(getContactInfo().whatsAppNumber, text)
