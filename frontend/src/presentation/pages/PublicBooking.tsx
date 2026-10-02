import React from 'react'

import { CalendarCheck, Check, Clock3, MapPin, Phone, Store, X } from 'lucide-react'
import { useNavigate, useParams, useSearchParams } from 'react-router'

import { BookingWizardContainer } from '@presentation/components/organisms/booking/BookingWizardContainer'
import {
  initialStepFor,
  resolveBookingPreselect
} from '@presentation/components/organisms/booking/deepLink'
import { useBookingStepParam } from '@presentation/hooks/useBookingStepParam'

import { buildWaMeUrl } from '@shared/utils/whatsAppPhone'

import { buttonStyles2000s, colors2000s } from '../../theme/colors'
import LegalFooterLinks from '../components/navigation/LegalFooterLinks'
import { NotFoundScreen } from '../components/organisms/NotFoundScreen'
import { isStoreMissing, StoreLoadError } from '../components/organisms/StoreLoadError'
import {
  usePublicPaymentStatus,
  usePublicServices,
  usePublicStaff,
  usePublicStore
} from '../hooks/usePublic'

/**
 * WhatsApp de la tienda: texto libre que carga el dueno. Si no se puede leer
 * como un numero confiable se muestra tal cual, sin link: un wa.me roto
 * mandaba la consulta a otro pais.
 */
const StoreWhatsAppContact: React.FC<{ phone: string; storeName: string }> = ({
  phone,
  storeName
}) => {
  const href = buildWaMeUrl(phone, `Hola ${storeName}! Quiero consultar por un turno.`)
  if (!href) return <span>{phone}</span>
  return (
    <a href={href} target="_blank" rel="noreferrer">
      {phone}
    </a>
  )
}

const PublicBooking: React.FC = () => {
  const { slug = '' } = useParams()
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const paymentId = searchParams.get('payment_id') || undefined
  const storeQuery = usePublicStore(slug)
  const { data: store, isLoading, isError } = storeQuery
  const paymentStatus = usePublicPaymentStatus(store?.public_id, paymentId)
  // Deep-link "reserva de nuevo" (?service=&staff=): se validan los ids contra
  // las listas publicas antes de montar el wizard. Sin parametros no se
  // consulta nada extra.
  const wanted = {
    service: searchParams.get('service'),
    staff: searchParams.get('staff'),
    date: searchParams.get('date')
  }
  const servicesQuery = usePublicServices(wanted.service ? store?.public_id : undefined)
  const staffQuery = usePublicStaff(
    wanted.service && wanted.staff ? store?.public_id : undefined,
    wanted.service || undefined
  )
  const resolvingDeepLink =
    Boolean(wanted.service) &&
    (servicesQuery.isLoading || (Boolean(wanted.staff) && staffQuery.isLoading))
  const preselect = resolveBookingPreselect(wanted, servicesQuery.data, staffQuery.data)
  // El paso del wizard vive en ?step= (F4-15); sin el, se arranca en el
  // horario si el deep-link trae un servicio valido. payment_id, service,
  // staff y date no se tocan al escribirlo.
  const bookingStep = useBookingStepParam(initialStepFor(preselect))

  if (isLoading || resolvingDeepLink) {
    return (
      <div
        className="min-h-screen grid place-items-center text-sm font-black uppercase tracking-widest"
        style={{ background: colors2000s.bg.primary, color: colors2000s.text.secondary }}
      >
        Cargando...
      </div>
    )
  }

  // 2026-10-02: cualquier falla decia "Negocio no encontrado", tambien sin red
  // o con un 5xx. Solo el 404 es una tienda que no existe. Con la tienda ya
  // cargada, un refetch fallido no tapa la pagina.
  if (!store && isError && !isStoreMissing(storeQuery.error)) {
    return (
      <StoreLoadError onRetry={() => void storeQuery.refetch()} retrying={storeQuery.isFetching} />
    )
  }

  if (!store) {
    return (
      <NotFoundScreen
        title="Negocio no encontrado"
        subtitle="No encontramos una tienda en esta dirección. Revisá el link que te compartieron."
      />
    )
  }

  if (paymentId) {
    const payment = paymentStatus.data
    const approved =
      payment?.payment_status === 'approved' && payment.appointment_status === 'confirmed'
    const failed = ['rejected', 'expired', 'refunded'].includes(payment?.payment_status || '')
    return (
      <div
        className="min-h-screen grid place-items-center px-4"
        style={{ background: colors2000s.bg.primary }}
      >
        <section
          className="w-full max-w-xl rounded-lg bg-white p-8 text-center space-y-5"
          style={{ boxShadow: colors2000s.shadows.outer }}
        >
          {approved ? (
            <Check className="w-16 h-16 mx-auto" color={colors2000s.status.success.light} />
          ) : failed ? (
            <X className="w-16 h-16 mx-auto" color={colors2000s.status.danger.light} />
          ) : (
            <Clock3
              className="w-16 h-16 mx-auto animate-pulse"
              color={colors2000s.status.warning.light}
            />
          )}
          <h1 className="text-2xl font-black uppercase tracking-tight">
            {approved
              ? 'Reserva confirmada'
              : failed
                ? 'La seña no fue aprobada'
                : 'Estamos validando tu pago'}
          </h1>
          <p className="text-sm font-bold" style={{ color: colors2000s.text.secondary }}>
            {approved
              ? 'Mercado Pago acreditó la seña y tu turno quedó reservado.'
              : failed
                ? 'El turno no fue confirmado. Podés volver a intentarlo desde la tienda.'
                : paymentStatus.pollingStopped
                  ? 'Todavía no recibimos la confirmación del pago. Si ya pagaste, tu turno se confirma cuando Mercado Pago avise; podés volver a consultar o hablar con la tienda.'
                  : 'No cierres esta pantalla. El turno se confirma cuando Mercado Pago nos avisa del pago.'}
          </p>
          {paymentStatus.pollingStopped && (
            // Pasados 30 min el sondeo corta (F4-05); consultar de nuevo es a
            // pedido. Solo relee el estado: confirmar es del webhook (regla 7).
            <button
              type="button"
              onClick={() => void paymentStatus.refetch()}
              disabled={paymentStatus.isFetching}
              className="w-full py-4 rounded-xl font-black uppercase tracking-widest text-xs border disabled:opacity-60"
              style={{
                borderColor: colors2000s.border.default,
                color: colors2000s.text.primary
              }}
            >
              Volver a consultar
            </button>
          )}
          {paymentStatus.isError && (
            <p
              role="alert"
              className="text-sm font-bold"
              style={{ color: colors2000s.status.danger.dark }}
            >
              No pudimos consultar el estado del pago. Actualizá la página en unos instantes.
            </p>
          )}
          <button
            type="button"
            // Sin payment_id en la URL se monta un wizard nuevo (estado y clave de
            // idempotencia nuevos) sin recargar la SPA (F11b-20).
            onClick={() => void navigate(`/booking/${slug}`)}
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
    <div
      className="min-h-screen py-12 px-4 sm:px-6 lg:px-8"
      style={{ background: colors2000s.bg.primary }}
    >
      {/* Header Info */}
      <div className="max-w-2xl mx-auto mb-8 text-center duration-700">
        <div
          className="inline-flex items-center justify-center w-16 h-16 rounded-md text-white mb-4 transform -rotate-6 border"
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
            className="flex items-center gap-2 px-4 py-2.5 rounded-md border"
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
            className="flex items-center gap-2 px-4 py-2.5 rounded-md border"
            style={{
              background: `linear-gradient(180deg, ${colors2000s.bg.button} 0%, ${colors2000s.bg.buttonBottom} 100%)`,
              borderColor: colors2000s.border.default,
              boxShadow: `${colors2000s.shadows.insetLight}, ${colors2000s.shadows.outer}`,
              color: colors2000s.text.primary
            }}
          >
            <Phone size={14} className="text-orange-500 stroke-[2.5px]" />
            {store.whatsapp_number ? (
              <StoreWhatsAppContact phone={store.whatsapp_number} storeName={store.name} />
            ) : (
              <span>Reserva por web disponible</span>
            )}
          </div>

          <a
            href={`/b/${store.slug}/mis-turnos`}
            className="flex items-center gap-2 px-4 py-2.5 rounded-xl border"
            style={{
              background: `linear-gradient(180deg, ${colors2000s.bg.button} 0%, ${colors2000s.bg.buttonBottom} 100%)`,
              borderColor: colors2000s.border.default,
              boxShadow: `${colors2000s.shadows.insetLight}, ${colors2000s.shadows.outer}`,
              color: colors2000s.text.primary
            }}
          >
            <CalendarCheck size={14} className="text-orange-500 stroke-[2.5px]" />
            <span>Mis turnos</span>
          </a>
        </div>
      </div>

      {store.description && (
        <div
          className="max-w-2xl mx-auto mb-6 rounded-lg p-6 text-center border"
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
      <BookingWizardContainer
        store={store}
        preselect={preselect}
        step={bookingStep.step}
        onStepChange={bookingStep.changeStep}
      />

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
