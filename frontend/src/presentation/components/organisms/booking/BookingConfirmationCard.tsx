import React, { useId, useState } from 'react'

import { CalendarCheck, Phone, WalletCards } from 'lucide-react'

import { buttonStyles2000s, colors2000s } from '../../../../theme/colors'
import { brandColor, brandCtaStyle } from '../../../lib/brandTheme'
import { createBookingAccentBoxStyle, createBookingSurfaceStyle } from '../../../lib/surfaceStyles'

// Una politica de seña mas larga que esto va plegada (unas 6 lineas en 390 px).
const LONG_DEPOSIT_POLICY_CHARS = 280

export type BookingPaymentMethod = 'manual' | 'mercadopago'

/** Que hace el boton principal y como se lee. */
export interface BookingSubmitAction {
  method: BookingPaymentMethod
  /** Texto del boton; con Mercado Pago lleva el importe de la seña. */
  label: string
  /** La reserva por WhatsApp debe la seña: el icono lo dice. */
  owesDepositByWhatsApp: boolean
  disabled: boolean
}

/** Los dos medios de la seña, cuando la tienda ofrece los dos. */
interface BookingPaymentChoice {
  value: BookingPaymentMethod
  /** "Por WhatsApp…" con seña obligatoria, "No la pago ahora" con una opcional. */
  manualLabel: string
  onChange: (method: BookingPaymentMethod) => void
}

interface BookingConfirmationCardProps {
  /** "Semipermanente + 3 Decoración"; null mientras carga el catalogo. */
  summaryServices: string | null
  /** El resto de la linea: duracion, dia, hora y quien atiende (sin cortar cada uno). */
  summaryDetails: readonly string[]
  /** Total, seña, codigo y avisos: lo arma el paso. */
  children: React.ReactNode
  storeName: string
  depositPolicy?: string | null
  acceptsTerms: boolean
  onAcceptsTermsChange: (accepts: boolean) => void
  paymentChoice: BookingPaymentChoice | null
  /** Importe que la barra fija muestra en el celular junto al boton (null: ya va en el boton). */
  barAmount: string | null
  /** null: no hay con que reservar (seña solo online sin Mercado Pago). */
  submit: BookingSubmitAction | null
  onSubmit: (method: BookingPaymentMethod) => void
}

const SubmitIcon: React.FC<{ submit: BookingSubmitAction }> = ({ submit }) => {
  if (submit.method === 'mercadopago') return <WalletCards className="w-4 h-4" />
  if (submit.owesDepositByWhatsApp) return <Phone className="w-4 h-4" />
  return <CalendarCheck className="w-4 h-4" />
}

/**
 * Tarjeta de pago de la confirmacion (S5): el turno en una linea, el importe,
 * la politica de seña, los terminos y UN solo boton. En el celular el boton
 * queda fijo al pie de la pantalla; en escritorio va dentro de la tarjeta.
 * Solo pinta: los importes y las reglas los decide el paso.
 */
export const BookingConfirmationCard: React.FC<BookingConfirmationCardProps> = ({
  summaryServices,
  summaryDetails,
  children,
  storeName,
  depositPolicy,
  acceptsTerms,
  onAcceptsTermsChange,
  paymentChoice,
  barAmount,
  submit,
  onSubmit
}) => {
  const policyId = useId()
  const [policyOpen, setPolicyOpen] = useState(false)
  const longPolicy = Boolean(depositPolicy && depositPolicy.length > LONG_DEPOSIT_POLICY_CHARS)
  const policyBoxStyle = createBookingAccentBoxStyle(
    colors2000s.bg.button,
    colors2000s.border.default,
    colors2000s.text.secondary
  )

  return (
    <section
      aria-label="Tu reserva"
      className="p-4 sm:p-6 bg-white space-y-5"
      style={createBookingSurfaceStyle()}
    >
      <p
        data-testid="booking-summary-line"
        className="text-sm font-black text-gray-800 break-words"
      >
        {summaryServices && <span>{summaryServices}</span>}
        {summaryDetails.map((part, index) => (
          <React.Fragment key={`${index}-${part}`}>
            {(summaryServices || index > 0) && ' · '}
            <span className="whitespace-nowrap">{part}</span>
          </React.Fragment>
        ))}
      </p>

      {children}

      {/* La politica se muestra aca, junto a la seña y antes de aceptar
          (Legal.tsx: "se muestra al cliente antes de confirmar la reserva");
          el pie de la pagina no la repite en este paso. Una larga va plegada
          detras de un boton para no tapar el boton de pagar; corta, entera. */}
      {depositPolicy &&
        (longPolicy ? (
          <div className="p-4 text-xs leading-relaxed" style={policyBoxStyle}>
            <button
              type="button"
              aria-expanded={policyOpen}
              aria-controls={policyId}
              onClick={() => setPolicyOpen((open) => !open)}
              className="min-h-11 w-full text-left font-black uppercase tracking-widest text-[10px] underline"
            >
              Ver política de seña de {storeName}
            </button>
            {policyOpen && (
              <p id={policyId} className="mt-2 font-medium whitespace-pre-line">
                {depositPolicy}
              </p>
            )}
          </div>
        ) : (
          <div className="p-4 text-xs leading-relaxed" style={policyBoxStyle}>
            <p className="font-black uppercase tracking-widest text-[10px] mb-1">
              Política de seña de {storeName}
            </p>
            <p className="font-medium whitespace-pre-line">{depositPolicy}</p>
          </div>
        ))}

      <label
        className="flex items-start gap-3 text-xs font-bold cursor-pointer select-none"
        style={{ color: colors2000s.text.secondary }}
      >
        <input
          type="checkbox"
          checked={acceptsTerms}
          onChange={(event) => onAcceptsTermsChange(event.target.checked)}
          className="mt-0.5 w-4 h-4 cursor-pointer"
          style={{ accentColor: brandColor.fill }}
        />
        <span>
          Acepto los{' '}
          <a
            href="/legal/terminos"
            target="_blank"
            rel="noreferrer"
            className="underline"
            style={{ color: colors2000s.text.primary }}
          >
            términos y condiciones
          </a>
          , la{' '}
          <a
            href="/legal/privacidad"
            target="_blank"
            rel="noreferrer"
            className="underline"
            style={{ color: colors2000s.text.primary }}
          >
            política de privacidad
          </a>
          {depositPolicy ? ' y la política de seña de la tienda.' : '.'}
        </span>
      </label>

      {paymentChoice && (
        <div role="radiogroup" aria-label="Cómo pagás la seña" className="grid gap-2">
          {(
            [
              ['mercadopago', 'Ahora con Mercado Pago'],
              ['manual', paymentChoice.manualLabel]
            ] as const
          ).map(([method, label]) => (
            <label
              key={method}
              className="min-h-11 flex items-center gap-3 px-3 py-2 text-xs font-black cursor-pointer select-none"
              style={createBookingAccentBoxStyle('#ffffff', '#e5e7eb')}
            >
              <input
                type="radio"
                name="booking-payment-method"
                checked={paymentChoice.value === method}
                onChange={() => paymentChoice.onChange(method)}
                className="w-4 h-4 cursor-pointer"
                style={{ accentColor: brandColor.fill }}
              />
              {label}
            </label>
          ))}
        </div>
      )}

      {submit && (
        // En el celular la barra queda fija al pie (con el margen del gesto de
        // inicio); en escritorio es parte de la tarjeta. Es el mismo boton: un
        // solo control de envio en la pagina.
        <div
          data-testid="booking-pay-bar"
          className="fixed inset-x-0 bottom-0 z-30 border-t bg-white px-4 pt-3 pb-[var(--booking-pay-bar-bottom)] space-y-2 sm:static sm:z-auto sm:border-0 sm:bg-transparent sm:p-0 sm:pb-0"
          style={
            {
              '--booking-pay-bar-bottom': 'calc(0.75rem + env(safe-area-inset-bottom))',
              borderColor: colors2000s.border.light
            } as React.CSSProperties
          }
        >
          {barAmount && (
            <p className="text-xs font-black text-gray-700 text-center sm:hidden">{barAmount}</p>
          )}
          <button
            type="button"
            disabled={submit.disabled}
            onClick={() => onSubmit(submit.method)}
            className="w-full min-h-11 font-black py-4 rounded-xl transition-all uppercase tracking-widest text-xs active:scale-95 border cursor-pointer select-none inline-flex items-center justify-center gap-2 disabled:cursor-not-allowed"
            style={submit.disabled ? buttonStyles2000s.disabled : brandCtaStyle}
          >
            <SubmitIcon submit={submit} />
            {submit.label}
          </button>
        </div>
      )}
    </section>
  )
}
