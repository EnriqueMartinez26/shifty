import React from 'react'

import { AlertTriangle, Lock } from 'lucide-react'

import type { StoreSubscriptionStatus } from '@application/services/StoreSettingsService'

import { formatArgentinaDateDisplay } from '@shared/utils/argentinaTime'
import { getContactInfo, supportWhatsAppUrl } from '@shared/utils/contactInfo'

import { colors2000s } from '../../../theme/colors'

const ACTION_CLASS =
  'inline-flex min-h-11 items-center justify-center rounded-xl px-4 py-2 text-center text-[10px] font-black uppercase tracking-widest whitespace-normal sm:whitespace-nowrap'

interface BannerContent {
  tone: 'warn' | 'blocked'
  title: string
  detail: string
}

/**
 * Que decirle al dueno segun el estado del plan. Devuelve null cuando no hay
 * nada que avisar (sin plan, plan al dia o cancelado por el propio dueno).
 */
export const subscriptionBanner = (
  subscription: StoreSubscriptionStatus | undefined
): BannerContent | null => {
  if (!subscription) return null
  const vence = subscription.current_period_end
    ? formatArgentinaDateDisplay(subscription.current_period_end)
    : null
  if (subscription.status === 'suspended') {
    return {
      tone: 'blocked',
      title: 'Tu suscripción está suspendida',
      detail:
        'Tu página de reservas no se ve y el panel quedó en solo lectura. Renová el plan para volver a operar.'
    }
  }
  if (subscription.status === 'past_due') {
    return {
      tone: 'blocked',
      title: 'Tu suscripción venció',
      detail: subscription.grace_until
        ? `Podés seguir usando Shifty hasta el ${formatArgentinaDateDisplay(subscription.grace_until)}. Después se suspende.`
        : 'Renovala para no perder el acceso.'
    }
  }
  if (subscription.warn && subscription.status === 'active') {
    const dias = subscription.days_left ?? 0
    const cuando = dias <= 0 ? 'hoy' : dias === 1 ? 'mañana' : `en ${dias} días`
    return {
      tone: 'warn',
      title: `Tu plan vence ${cuando}`,
      detail: vence ? `${subscription.plan_name ?? 'Tu plan'} vence el ${vence}.` : ''
    }
  }
  return null
}

interface SubscriptionBannerProps {
  subscription: StoreSubscriptionStatus | undefined
  storeName?: string
}

export const SubscriptionBanner: React.FC<SubscriptionBannerProps> = ({
  subscription,
  storeName
}) => {
  const content = subscriptionBanner(subscription)
  if (!content) return null
  const bloqueado = content.tone === 'blocked'
  const actionStyle: React.CSSProperties = {
    background: 'white',
    border: `1px solid ${colors2000s.border.default}`,
    color: bloqueado ? colors2000s.status.danger.text : colors2000s.status.warning.text
  }
  const texto = `Hola! Soy de ${storeName || 'mi negocio'} y quiero renovar mi plan de Shifty.`
  // El WhatsApp de soporte es configuracion del build (VITE_SUPPORT_WHATSAPP),
  // nunca un numero en el codigo: el repo es publico. Sin uno valido no hay
  // link roto, queda un texto neutro (al email, si esta configurado).
  const supportHref = supportWhatsAppUrl(texto)
  const supportEmail = supportHref ? null : getContactInfo().email
  return (
    <div
      role="status"
      className="mb-6 rounded-2xl px-5 py-4 flex flex-wrap items-center gap-3 justify-between"
      style={{
        background: bloqueado ? colors2000s.status.danger.bg : colors2000s.status.warning.bg,
        border: `1px solid ${bloqueado ? colors2000s.status.danger.border : colors2000s.status.warning.border}`,
        color: bloqueado ? colors2000s.status.danger.text : colors2000s.status.warning.text
      }}
    >
      <div className="flex min-w-0 items-start gap-3">
        {bloqueado ? (
          <Lock className="w-5 h-5 mt-0.5 flex-shrink-0" />
        ) : (
          <AlertTriangle className="w-5 h-5 mt-0.5 flex-shrink-0" />
        )}
        <div className="min-w-0 break-words">
          <p className="text-xs font-black uppercase tracking-widest">{content.title}</p>
          {content.detail && <p className="text-xs font-bold mt-1">{content.detail}</p>}
        </div>
      </div>
      {supportHref ? (
        <a
          href={supportHref}
          target="_blank"
          rel="noreferrer"
          className={ACTION_CLASS}
          style={actionStyle}
        >
          Renovar por WhatsApp
        </a>
      ) : supportEmail ? (
        <a href={`mailto:${supportEmail}`} className={ACTION_CLASS} style={actionStyle}>
          Escribinos para renovar
        </a>
      ) : (
        <p className="min-w-0 whitespace-normal break-words text-[10px] font-black uppercase tracking-widest">
          Escribinos para renovar
        </p>
      )}
    </div>
  )
}
