import React from 'react'

import { Check, Clock3, X } from 'lucide-react'
import { useNavigate, useParams, useSearchParams } from 'react-router'

import { BookingPriorDesignAfterPayment } from '@presentation/components/organisms/booking/BookingPriorDesign'
import { BookingWizardContainer } from '@presentation/components/organisms/booking/BookingWizardContainer'
import {
  initialStepFor,
  resolveBookingPreselect
} from '@presentation/components/organisms/booking/deepLink'
import { STEP_CONFIRMATION } from '@presentation/components/organisms/booking/stepFlow'
import { StoreHeader } from '@presentation/components/organisms/storefront/StoreHeader'
import { useBookingStepParam } from '@presentation/hooks/useBookingStepParam'
import { brandCssVariables, brandCtaStyle, resolveBrandTheme } from '@presentation/lib/brandTheme'

import { readPriorDesignHandoff } from '@shared/utils/priorDesignHandoff'

import { colors2000s } from '../../theme/colors'
import LegalFooterLinks from '../components/navigation/LegalFooterLinks'
import { NotFoundScreen } from '../components/organisms/NotFoundScreen'
import { isStoreMissing, StoreLoadError } from '../components/organisms/StoreLoadError'
import { useDocumentTitle } from '../hooks/useDocumentTitle'
import {
  usePublicPaymentStatus,
  usePublicServices,
  usePublicStaff,
  usePublicStore
} from '../hooks/usePublic'

const LEGAL_FOOTER_TARGET_CLASSES = '[&_a]:inline-flex [&_a]:min-h-11 [&_a]:items-center [&_a]:px-1'

const PublicBooking: React.FC = () => {
  const { slug = '' } = useParams()
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const paymentId = searchParams.get('payment_id') || undefined
  const storeQuery = usePublicStore(slug)
  const { data: store, isLoading, isError } = storeQuery
  useDocumentTitle(store ? `${store.name} · Reservá tu turno` : null)
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
      <main
        className="min-h-screen grid place-items-center text-sm font-black uppercase tracking-widest"
        style={{ background: colors2000s.bg.primary, color: colors2000s.text.secondary }}
      >
        Cargando...
      </main>
    )
  }

  // 2026-10-02: cualquier falla decia "Negocio no encontrado", tambien sin red
  // o con un 5xx. Solo el 404 es una tienda que no existe. Con la tienda ya
  // cargada, un refetch fallido no tapa la pagina.
  if (!store && isError && !isStoreMissing(storeQuery.error)) {
    return (
      <main>
        <StoreLoadError
          onRetry={() => void storeQuery.refetch()}
          retrying={storeQuery.isFetching}
        />
      </main>
    )
  }

  if (!store) {
    return (
      <main>
        <NotFoundScreen
          title="Negocio no encontrado"
          subtitle="No encontramos una tienda en esta dirección. Revisá el link que te compartieron."
        />
      </main>
    )
  }

  const brand = resolveBrandTheme(store.primary_color)
  const header = (
    <StoreHeader
      name={store.name}
      logoUrl={store.logo_url}
      coverUrl={store.cover_url}
      coverPosition={store.cover_position}
      whatsappNumber={store.whatsapp_number}
      misTurnosHref={`/b/${store.slug}/mis-turnos`}
      brand={brand}
    />
  )

  if (paymentId) {
    const payment = paymentStatus.data
    const approved =
      payment?.payment_status === 'approved' && payment.appointment_status === 'confirmed'
    const failed = ['rejected', 'expired', 'refunded'].includes(payment?.payment_status || '')
    // Diseño previo (S7): el resumen que guardo el paso de confirmacion antes
    // de ir a MP, solo para este turno y mientras el pago no fallo.
    const priorDesign =
      payment && !failed
        ? readPriorDesignHandoff(store.public_id, payment.appointment_public_id)
        : null
    return (
      // La vuelta de Mercado Pago lleva la tienda y su color (S3) con la misma
      // vidriera que la reserva (S9): el nombre sigue siendo el h1 y el estado
      // del pago va debajo. Sin margen lateral en el celular: la portada va de
      // borde a borde y el contenido pone el suyo.
      <main
        className="min-h-screen pb-8 sm:px-6 sm:pb-12"
        style={{ ...brandCssVariables(brand), background: colors2000s.bg.primary }}
      >
        {header}
        <div className="px-4 sm:px-0">
          <section
            className="mx-auto mt-6 w-full max-w-2xl rounded-lg bg-white p-4 sm:p-8 text-center space-y-5"
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
            <h2 className="text-2xl font-black uppercase tracking-tight">
              {approved
                ? 'Reserva confirmada'
                : failed
                  ? 'La seña no fue aprobada'
                  : 'Estamos validando tu pago'}
            </h2>
            <p className="text-sm font-bold" style={{ color: colors2000s.text.secondary }}>
              {approved
                ? 'Mercado Pago acreditó la seña y tu turno quedó reservado.'
                : failed
                  ? 'El turno no fue confirmado. Podés volver a intentarlo desde la tienda.'
                  : paymentStatus.pollingStopped
                    ? 'Todavía no recibimos la confirmación del pago. Si ya pagaste, tu turno se confirma cuando Mercado Pago avise; podés volver a consultar o hablar con la tienda.'
                    : 'No cierres esta pantalla. El turno se confirma cuando Mercado Pago nos avisa del pago.'}
            </p>
            {priorDesign && (
              <BookingPriorDesignAfterPayment
                handoff={priorDesign}
                storeName={store.name}
                whatsappNumber={store.whatsapp_number}
              />
            )}
            {paymentStatus.pollingStopped && (
              // Pasados 30 min el sondeo corta (F4-05); consultar de nuevo es a
              // pedido. Solo relee el estado: confirmar es del webhook (regla 7).
              <button
                type="button"
                onClick={() => void paymentStatus.refetch()}
                disabled={paymentStatus.isFetching}
                className="w-full min-h-11 py-4 rounded-xl font-black uppercase tracking-widest text-xs border disabled:opacity-60"
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
              className="w-full min-h-11 py-4 rounded-xl border font-black uppercase tracking-widest text-xs"
              style={brandCtaStyle}
            >
              Volver a la tienda
            </button>
            <LegalFooterLinks className={`pt-2 ${LEGAL_FOOTER_TARGET_CLASSES}`} />
          </section>
        </div>
      </main>
    )
  }

  // En la confirmacion el boton de pago queda fijo al pie en el celular
  // (BookingConfirmationCard): la pagina reserva su alto, gesto de inicio
  // incluido, para que no tape los links del pie al final. Arriba no hay
  // margen: la portada toca el borde (S9).
  const bottomPadding =
    bookingStep.step === STEP_CONFIRMATION
      ? 'pb-[calc(8rem+env(safe-area-inset-bottom))] sm:pb-12'
      : 'pb-8 sm:pb-12'

  return (
    // Sin margen lateral en el celular: la portada va de borde a borde y el
    // contenido de abajo pone el suyo.
    <main
      className={`min-h-screen sm:px-6 lg:px-8 ${bottomPadding}`}
      style={{ background: colors2000s.bg.primary }}
    >
      {header}
      <div className="mt-6 px-4 sm:mt-8 sm:px-0">
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

        {/* Footer minimalista. En el paso de confirmacion la politica de seña
          se muestra completa junto a la seña, antes de aceptar y reservar:
          repetir aca que existe era ruido. Terminos y privacidad quedan en
          todos los pasos. */}
        <div className="max-w-2xl mx-auto mt-12 text-center space-y-3">
          <LegalFooterLinks
            depositPolicy={bookingStep.step === STEP_CONFIRMATION ? null : store.deposit_policy}
            className={LEGAL_FOOTER_TARGET_CLASSES}
          />
          <p
            className="text-[10px] font-black uppercase tracking-widest"
            style={{ color: colors2000s.text.secondary }}
          >
            POWERED BY <span className="text-brand-accent font-extrabold">SHIFTY</span>
          </p>
        </div>
      </div>
    </main>
  )
}

export default PublicBooking
