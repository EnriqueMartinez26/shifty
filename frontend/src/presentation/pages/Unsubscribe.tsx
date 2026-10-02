import React from 'react'

import { MailX } from 'lucide-react'
import { Link, useSearchParams } from 'react-router'

import { getHttpStatus } from '@shared/errors/getErrorMessage'

import { buttonStyles2000s, colors2000s } from '../../theme/colors'
import { AuthShell } from '../components/organisms/AuthShell'
import { useUnsubscribeFromMarketing } from '../hooks/usePublic'

const BUTTON_CLASS =
  'w-full font-bold py-4 rounded-2xl flex items-center justify-center gap-2 transition-all active:scale-[0.98]'

const TEXT_CLASS = 'text-sm font-medium text-center'

/**
 * 400 `UNSUBSCRIBE_LINK_INVALID` (firma adulterada o vencida) o 422 (token
 * vacio o enorme): el link no sirve y reintentar no cambia nada. Sin red, un
 * 429 o un 5xx son pasajeros y se puede volver a probar.
 */
const isInvalidLink = (error: unknown): boolean => {
  const status = getHttpStatus(error)
  return status === 400 || status === 422
}

const PrivacyLink: React.FC = () => (
  <Link to="/legal/privacidad" className={BUTTON_CLASS} style={buttonStyles2000s.default}>
    Ver la política de privacidad
  </Link>
)

const InvalidLink: React.FC = () => (
  <AuthShell title="El enlace no es válido" subtitle="Puede haber vencido o estar incompleto.">
    <div className="space-y-4">
      <p className={TEXT_CLASS} style={{ color: colors2000s.text.primary }}>
        Si querés dejar de recibir las invitaciones para volver a reservar, usá el enlace del último
        correo que te llegó o pedíselo a la tienda.
      </p>
      <PrivacyLink />
    </div>
  </AuthShell>
)

/**
 * Baja del mail promocional "volve a reservar" (art. 27 Ley 25.326). El link
 * del mail trae el token firmado en `?token=`. Abrir la pagina no da de baja:
 * los escaneres de correo abren los links, asi que la baja se registra recien
 * con el boton, por `POST /public/unsubscribe` (2026-10-02).
 */
const UnsubscribePage: React.FC = () => {
  const [searchParams] = useSearchParams()
  const token = searchParams.get('token')?.trim() ?? ''
  const unsubscribe = useUnsubscribeFromMarketing()

  if (!token || (unsubscribe.isError && isInvalidLink(unsubscribe.error))) {
    return <InvalidLink />
  }

  if (unsubscribe.isSuccess) {
    return (
      <AuthShell
        title="Baja registrada"
        subtitle="No vas a recibir más invitaciones para volver a reservar de esta tienda."
      >
        <div className="space-y-4">
          <p className={TEXT_CLASS} style={{ color: colors2000s.text.primary }}>
            Los avisos de los turnos que reserves (registro, confirmación, recordatorios y cambios)
            se siguen enviando porque son parte de la reserva.
          </p>
          <PrivacyLink />
        </div>
      </AuthShell>
    )
  }

  return (
    <AuthShell
      title="Dejar de recibir invitaciones"
      subtitle="Confirmá que no querés recibir más correos de esta tienda invitándote a volver a reservar."
    >
      <div className="space-y-4">
        <p className={TEXT_CLASS} style={{ color: colors2000s.text.primary }}>
          Los avisos de tus turnos (registro, confirmación, recordatorios y cambios) se siguen
          enviando.
        </p>
        {unsubscribe.isError && (
          <div
            role="alert"
            className="text-sm p-3 rounded-xl font-medium"
            style={{
              background: colors2000s.status.danger.bg,
              border: `1px solid ${colors2000s.status.danger.border}`,
              color: colors2000s.status.danger.text
            }}
          >
            No pudimos registrar la baja. Probá de nuevo en unos minutos.
          </div>
        )}
        <button
          type="button"
          onClick={() => unsubscribe.mutate(token)}
          disabled={unsubscribe.isPending}
          className={BUTTON_CLASS}
          style={unsubscribe.isPending ? buttonStyles2000s.disabled : buttonStyles2000s.selected}
        >
          <MailX className="w-4 h-4" aria-hidden="true" />
          {unsubscribe.isPending ? 'Procesando...' : 'Darme de baja'}
        </button>
      </div>
    </AuthShell>
  )
}

export default UnsubscribePage
