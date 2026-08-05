import React from 'react'

import { CheckCircle2, Clock3, MapPin, Phone, Store, XCircle } from 'lucide-react'
import { useParams, useSearchParams } from 'react-router'

import { BookingWizardContainer } from '@presentation/components/organisms/booking/BookingWizardContainer'

import { buttonStyles2000s, colors2000s } from '../../theme/colors'
import LegalFooterLinks from '../components/navigation/LegalFooterLinks'
import { usePublicPaymentStatus, usePublicStore } from '../hooks/usePublic'

const PublicBooking: React.FC = () => {
  const { slug = '' } = useParams()
  const [searchParams] = useSearchParams()
  const paymentId = searchParams.get('payment_id') || undefined
  const { data: store, isLoading, isError } = usePublicStore(slug)
  const paymentStatus = usePublicPaymentStatus(store?.public_id, paymentId)

  if (isLoading) {
    return (
      <div className="min-h-screen grid place-items-center bg-[#EEF2F6] text-sm font-black uppercase tracking-widest text-gray-500">
        Cargando...
      </div>
    )
  }

  if (isError || !store) {
    return (
      <div className="min-h-screen grid place-items-center bg-[#EEF2F6] text-sm font-black uppercase tracking-widest text-red-500 font-black">
        Negocio no encontrado
      </div>
    )
  }

  if (paymentId) {
    const payment = paymentStatus.data
    const approved =
      payment?.payment_status === 'approved' && payment.appointment_status === 'confirmed'
    const failed = ['rejected', 'expired', 'refunded'].includes(payment?.payment_status || '')
    return (
      <div className="min-h-screen bg-[#EEF2F6] grid place-items-center px-4">
        <section
          className="w-full max-w-xl rounded-[2.5rem] bg-white p-8 text-center space-y-5"
          style={{ boxShadow: colors2000s.shadows.outer }}
        >
          {approved ? (
            <CheckCircle2 className="w-16 h-16 text-green-500 mx-auto" />
          ) : failed ? (
            <XCircle className="w-16 h-16 text-red-500 mx-auto" />
          ) : (
            <Clock3 className="w-16 h-16 text-amber-500 mx-auto animate-pulse" />
          )}
          <h1 className="text-2xl font-black uppercase tracking-tight">
            {approved
              ? 'Reserva confirmada'
              : failed
                ? 'La seña no fue aprobada'
                : 'Estamos validando tu pago'}
          </h1>
          <p className="text-sm font-bold text-gray-500">
            {approved
              ? 'Mercado Pago acreditó la seña y tu turno quedó reservado.'
              : failed
                ? 'El turno no fue confirmado. Podés volver a intentarlo desde la tienda.'
                : 'No cierres esta pantalla. La confirmación depende del webhook verificado del backend.'}
          </p>
          {paymentStatus.isError && (
            <p role="alert" className="text-sm font-bold text-red-600">
              No pudimos consultar el estado del pago. Actualizá la página en unos instantes.
            </p>
          )}
          <button
            type="button"
            onClick={() => window.location.assign(`/booking/${slug}`)}
            className="w-full py-4 rounded-xl text-white font-black uppercase tracking-widest text-xs"
            style={buttonStyles2000s.selected}
          >
            Volver a la tienda
          </button>
          <LegalFooterLinks className="pt-2" />
        </section>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-[#EEF2F6] py-12 px-4 sm:px-6 lg:px-8">
      {/* Header Info */}
      <div className="max-w-2xl mx-auto mb-8 text-center animate-in fade-in slide-in-from-top-4 duration-700">
        <div
          className="inline-flex items-center justify-center w-16 h-16 rounded-[1.25rem] text-white mb-4 transform -rotate-6 border"
          style={{
            background: `linear-gradient(135deg, ${colors2000s.orange.light} 0%, ${colors2000s.orange.dark} 100%)`,
            borderColor: colors2000s.orange.accent,
            boxShadow: `${colors2000s.shadows.insetLight}, ${colors2000s.shadows.outerOrange}`
          }}
        >
          <Store className="w-8 h-8 group-hover:scale-110 transition-transform duration-300" />
        </div>

        <h1
          className="text-4xl sm:text-5xl font-black tracking-tighter uppercase mb-4"
          style={{ color: colors2000s.orange.accent }}
        >
          Reservar turno
        </h1>

        <div className="flex flex-wrap items-center justify-center gap-4 text-xs font-black uppercase tracking-widest">
          <div
            className="flex items-center gap-2 px-4 py-2.5 rounded-xl border"
            style={{
              background: `linear-gradient(180deg, ${colors2000s.bg.button} 0%, ${colors2000s.bg.buttonBottom} 100%)`,
              borderColor: colors2000s.border.default,
              boxShadow: `${colors2000s.shadows.insetLight}, ${colors2000s.shadows.outer}`,
              color: colors2000s.text.primary
            }}
          >
            <MapPin size={14} className="text-orange-500 stroke-[2.5px]" />
            <span>{store.name}</span>
          </div>

          <div
            className="flex items-center gap-2 px-4 py-2.5 rounded-xl border"
            style={{
              background: `linear-gradient(180deg, ${colors2000s.bg.button} 0%, ${colors2000s.bg.buttonBottom} 100%)`,
              borderColor: colors2000s.border.default,
              boxShadow: `${colors2000s.shadows.insetLight}, ${colors2000s.shadows.outer}`,
              color: colors2000s.text.primary
            }}
          >
            <Phone size={14} className="text-orange-500 stroke-[2.5px]" />
            <span>{store.whatsapp_number || 'Reserva por web disponible'}</span>
          </div>
        </div>
      </div>

      {store.description && (
        <div
          className="max-w-2xl mx-auto mb-6 rounded-3xl p-6 text-center border"
          style={{
            background: `linear-gradient(180deg, ${colors2000s.bg.button} 0%, ${colors2000s.bg.buttonBottom} 100%)`,
            borderColor: colors2000s.border.default,
            boxShadow: `${colors2000s.shadows.insetLight}, ${colors2000s.shadows.outer}`
          }}
        >
          <p
            className="text-sm font-bold leading-relaxed"
            style={{ color: colors2000s.text.primary }}
          >
            {store.description}
          </p>
        </div>
      )}

      {/* The Wizard Component */}
      <BookingWizardContainer store={store} />

      {/* Footer minimalista */}
      <div className="max-w-2xl mx-auto mt-12 text-center space-y-3">
        <LegalFooterLinks depositPolicy={store.deposit_policy} />
        <p className="text-[10px] font-black uppercase tracking-widest text-gray-400">
          POWERED BY <span className="text-orange-500 font-extrabold">SHIFTY</span>
        </p>
      </div>
    </div>
  )
}

export default PublicBooking
