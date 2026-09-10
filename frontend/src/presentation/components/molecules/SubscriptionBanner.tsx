import React from 'react'

import { AlertTriangle, Lock } from 'lucide-react'

import type { StoreSubscriptionStatus } from '@application/services/StoreSettingsService'

import { formatArgentinaDateDisplay } from '@shared/utils/argentinaTime'
import { sanitizePhoneForUrl } from '@shared/utils/safeUrl'

import { colors2000s } from '../../../theme/colors'

/** WhatsApp de soporte de Shifty para renovar el plan. */
const SUPPORT_PHONE = '5493513000000'

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
  const texto = `Hola! Soy de ${storeName || 'mi negocio'} y quiero renovar mi plan de Shifty.`
  return (
    <div
      role="status"
      className="mb-6 rounded-2xl px-5 py-4 flex flex-wrap items-center gap-3 justify-between"
      style={{
        background: bloqueado ? '#fef2f2' : '#fffbeb',
        border: `1px solid ${bloqueado ? '#fecaca' : '#fde68a'}`,
        color: bloqueado ? '#991b1b' : '#92400e'
      }}
    >
      <div className="flex items-start gap-3 min-w-0">
        {bloqueado ? (
          <Lock className="w-5 h-5 mt-0.5 flex-shrink-0" />
        ) : (
          <AlertTriangle className="w-5 h-5 mt-0.5 flex-shrink-0" />
        )}
        <div className="min-w-0">
          <p className="text-xs font-black uppercase tracking-widest">{content.title}</p>
          {content.detail && <p className="text-xs font-bold mt-1">{content.detail}</p>}
        </div>
      </div>
      <a
        href={`https://wa.me/${sanitizePhoneForUrl(SUPPORT_PHONE)}?text=${encodeURIComponent(texto)}`}
        target="_blank"
        rel="noreferrer"
        className="rounded-xl px-4 py-2 text-[10px] font-black uppercase tracking-widest whitespace-nowrap"
        style={{
          background: 'white',
          border: `1px solid ${colors2000s.border.default}`,
          color: bloqueado ? '#991b1b' : '#92400e'
        }}
      >
        Renovar por WhatsApp
      </a>
    </div>
  )
}
