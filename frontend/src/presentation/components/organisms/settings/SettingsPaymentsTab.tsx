import React from 'react'

import { Check, RefreshCcw, Save, Unplug } from 'lucide-react'

import type { GatewayConfig } from '@application/services/PaymentsService'

import { getErrorCode } from '@shared/errors/getErrorMessage'

import { buttonStyles2000s, colors2000s } from '../../../../theme/colors'
import type { SettingsFormData } from '../../../lib/settingsDraft'
import { createSettingsInputStyle } from '../../../lib/surfaceStyles'
import { QueryErrorNotice } from '../../molecules/QueryErrorNotice'

type DepositConditions = Pick<SettingsFormData, 'allow_manual_coordination' | 'deposit_policy'>

interface SettingsPaymentsTabProps {
  gateway: GatewayConfig | undefined
  /** Error de GET /payments/gateway-config; un FEATURE_DISABLED es "cobros apagados". */
  gatewayError?: unknown
  /** Que mutacion de OAuth esta en curso. */
  pending: { connect: boolean; refresh: boolean; disconnect: boolean }
  onConnect: () => void
  onRefresh: () => void
  onDisconnect: () => void
  /** Volvio del OAuth de Mercado Pago con `?mercadopago=connected`. */
  justConnected: boolean
  value: DepositConditions
  onChange: (patch: Partial<DepositConditions>) => void
  /** "Guardar condiciones" es el mismo guardado (PATCH /stores/me) que el de la cabecera. */
  onSave: () => void
  saveDisabled: boolean
  saveStatus: 'idle' | 'saving' | 'success' | 'error'
  saveBlockedNotice: React.ReactNode
  /** Tienda suspendida: PATCH /stores/me responde 402; el OAuth sigue (FF-15). */
  readOnlyReason?: string | null
}

/**
 * Pestana "Mercado Pago" de Configuracion (F11b-08). Solo pinta: conectar,
 * renovar y desconectar los resuelve la pagina, que escribe el cartel de error
 * compartido.
 */
export const SettingsPaymentsTab: React.FC<SettingsPaymentsTabProps> = ({
  gateway,
  gatewayError = null,
  pending,
  onConnect,
  onRefresh,
  onDisconnect,
  justConnected,
  value,
  onChange,
  onSave,
  saveDisabled,
  saveStatus,
  saveBlockedNotice,
  readOnlyReason = null
}) => {
  // Con los cobros apagados el backend responde 403 a todo /payments: no es una
  // falla. La politica de sena se sigue guardando aca (activar los cobros la
  // exige), pero conectar la cuenta espera a que se activen.
  const paymentsOff = getErrorCode(gatewayError) === 'FEATURE_DISABLED'
  return (
    <div className="space-y-6">
      <div>
        <h3
          className="text-lg font-black uppercase tracking-tight"
          style={{ color: colors2000s.orange.accent }}
        >
          Mercado Pago de la tienda
        </h3>
        <p className="mt-2 text-xs font-bold" style={{ color: colors2000s.text.secondary }}>
          La tienda autoriza su propia cuenta. Shifty nunca te pide ni muestra tus claves de Mercado
          Pago.
        </p>
      </div>

      {paymentsOff ? (
        <div
          role="status"
          className="rounded-md p-4 text-xs font-bold"
          style={{
            background: colors2000s.status.info.bg,
            border: `1px solid ${colors2000s.status.info.border}`,
            color: colors2000s.status.info.text
          }}
        >
          Los cobros online están apagados para tu negocio. Guardá acá tu política de seña y
          activalos en la pestaña Funciones para conectar Mercado Pago.
        </div>
      ) : (
        <QueryErrorNotice
          error={gatewayError}
          message="No se pudo cargar la cuenta de Mercado Pago."
        />
      )}

      <div
        className="rounded-md p-6 space-y-4"
        style={{
          background: 'white',
          border: `1px solid ${colors2000s.border.light}`,
          boxShadow: colors2000s.shadows.outer
        }}
      >
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <p className="font-black uppercase tracking-tight">
              {gateway?.configured ? 'Cuenta conectada' : 'Cuenta no conectada'}
            </p>
            <p className="text-xs font-bold text-gray-500 mt-1">
              {gateway?.oauth_user_id
                ? `Cuenta Mercado Pago ${gateway.oauth_user_id}`
                : 'Conectá la cuenta que recibirá las señas de esta tienda.'}
            </p>
          </div>
          <span
            className="px-3 py-1.5 rounded-full text-[10px] font-black uppercase tracking-widest"
            style={{
              background: gateway?.configured
                ? colors2000s.status.success.bg
                : colors2000s.status.warning.bg,
              color: gateway?.configured
                ? colors2000s.status.success.text
                : colors2000s.status.warning.text
            }}
          >
            {gateway?.configured ? 'Activa' : 'Pendiente'}
          </span>
        </div>

        {!gateway?.configured ? (
          <button
            type="button"
            onClick={onConnect}
            disabled={paymentsOff || pending.connect || !gateway?.oauth_supported}
            className="w-full py-4 rounded-xl text-white font-black uppercase tracking-widest text-xs disabled:opacity-50"
            style={buttonStyles2000s.selected}
          >
            {pending.connect ? 'Conectando...' : 'Conectar con Mercado Pago'}
          </button>
        ) : (
          <div className="grid sm:grid-cols-2 gap-3">
            <button
              type="button"
              onClick={onRefresh}
              disabled={pending.refresh}
              className="py-3 font-black uppercase tracking-widest text-xs"
              style={buttonStyles2000s.default}
            >
              <RefreshCcw className="w-4 h-4 inline mr-2" />
              Renovar acceso
            </button>
            <button
              type="button"
              onClick={onDisconnect}
              disabled={pending.disconnect}
              className="py-3 rounded-xl font-black uppercase tracking-widest text-xs text-red-700 border border-red-200 bg-red-50"
            >
              <Unplug className="w-4 h-4 inline mr-2" />
              Desconectar
            </button>
          </div>
        )}

        {/* Sin respuesta del servidor no se sabe si faltan las credenciales. */}
        {gateway && !gateway.oauth_supported && (
          <p role="alert" className="text-xs font-bold text-red-600">
            Shifty todavía no tiene habilitada la conexión con Mercado Pago.
          </p>
        )}
        {justConnected && (
          <p className="text-xs font-bold text-green-700">
            La cuenta quedó conectada correctamente.
          </p>
        )}
      </div>

      <div className="space-y-4 pt-2">
        <h4
          className="text-sm font-black uppercase tracking-tight"
          style={{ color: colors2000s.orange.accent }}
        >
          Condiciones de la seña
        </h4>

        <label className="flex items-start gap-3 text-xs font-bold cursor-pointer select-none">
          <input
            type="checkbox"
            checked={value.allow_manual_coordination}
            onChange={(e) => onChange({ allow_manual_coordination: e.target.checked })}
            className="mt-0.5 w-4 h-4 accent-orange-500 cursor-pointer"
          />
          <span style={{ color: colors2000s.text.secondary }}>
            Permitir coordinar el pago por fuera (WhatsApp).
            <span className="block font-medium mt-1" style={{ color: colors2000s.text.disabled }}>
              Si lo desactivás, los servicios con seña obligatoria solo se van a poder reservar
              pagando con Mercado Pago.
            </span>
          </span>
        </label>

        <div className="space-y-2">
          <label
            className="text-[10px] font-black uppercase tracking-widest"
            style={{ color: colors2000s.text.secondary }}
          >
            Política de seña, cancelación y reembolso
          </label>
          <textarea
            rows={5}
            maxLength={2000}
            value={value.deposit_policy}
            onChange={(e) => onChange({ deposit_policy: e.target.value })}
            placeholder="Ej: La seña equivale al 30% del servicio y se descuenta del total. Se devuelve si cancelás con 24 horas de anticipación."
            className="w-full rounded-2xl px-5 py-3.5 font-bold outline-none"
            style={createSettingsInputStyle()}
          />
          <p className="text-[11px] font-medium" style={{ color: colors2000s.text.disabled }}>
            Se le muestra al cliente antes de reservar y queda registrada su aceptación. Es tu
            respaldo ante un reclamo, así que conviene ser concreto.
          </p>
        </div>

        <button
          type="button"
          onClick={onSave}
          disabled={saveDisabled}
          title={readOnlyReason ?? undefined}
          className="rounded-2xl px-5 py-3 font-black uppercase tracking-widest text-xs inline-flex items-center gap-2 transition-all active:scale-95 cursor-pointer disabled:cursor-not-allowed disabled:opacity-50"
          style={{
            background: `linear-gradient(180deg, ${colors2000s.orange.light} 0%, ${colors2000s.orange.dark} 100%)`,
            border: `1px solid ${colors2000s.orange.accent}`,
            color: colors2000s.text.onOrange,
            boxShadow: `${colors2000s.shadows.insetLight}, ${colors2000s.shadows.outerOrange}`
          }}
        >
          {saveStatus === 'success' ? <Check className="w-4 h-4" /> : <Save className="w-4 h-4" />}
          {saveStatus === 'saving'
            ? 'Guardando...'
            : saveStatus === 'success'
              ? 'Guardado'
              : 'Guardar condiciones'}
        </button>
        {saveBlockedNotice}
      </div>
    </div>
  )
}
