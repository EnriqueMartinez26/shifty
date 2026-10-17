import React from 'react'

import { Link, useParams } from 'react-router'

import { ClientAppointmentsContainer } from '@presentation/containers/ClientAppointmentsContainer'

import { buttonStyles2000s, colors2000s } from '../../theme/colors'
import LegalFooterLinks from '../components/navigation/LegalFooterLinks'
import { isStoreMissing, StoreLoadError } from '../components/organisms/StoreLoadError'
import { useDocumentTitle } from '../hooks/useDocumentTitle'
import { usePublicStore, usePublicStoreRef } from '../hooks/usePublic'

const ClientAppointmentsPage: React.FC = () => {
  const { slug = '' } = useParams()
  // FF-16: la vitrina (/public/stores/{slug}) da 404 con la tienda suspendida
  // y el cliente se quedaba sin cancelar ni reprogramar, que siguen
  // permitidos. El ref responde tambien entonces, con el mismo 404 neutro si
  // la tienda no existe.
  const refQuery = usePublicStoreRef(slug)
  const { data: ref, isLoading, isError } = refQuery
  const acceptsNewBookings = ref?.accepts_new_bookings === true
  // La politica de sena del pie solo la trae la vitrina: se pide cuando no va
  // a dar 404.
  const { data: vitrina } = usePublicStore(slug, acceptsNewBookings)
  useDocumentTitle(ref ? `Mis turnos · ${ref.name}` : 'Mis turnos · Shifty')

  if (isLoading) {
    return (
      <div
        className="min-h-screen grid place-items-center text-sm font-black uppercase tracking-widest"
        style={{ background: colors2000s.bg.primary, color: colors2000s.text.secondary }}
      >
        Cargando...
      </div>
    )
  }

  // 2026-10-02: sin red o con un 5xx tambien decia "Negocio no encontrado".
  if (!ref && isError && !isStoreMissing(refQuery.error)) {
    return <StoreLoadError onRetry={() => void refQuery.refetch()} retrying={refQuery.isFetching} />
  }

  if (!ref) {
    return (
      <div
        className="min-h-screen grid place-items-center text-sm font-black uppercase tracking-widest"
        style={{ background: colors2000s.bg.primary, color: colors2000s.status.danger.text }}
      >
        Negocio no encontrado
      </div>
    )
  }

  // El slug canonico es minuscula: la URL la tipean humanos y la marca de OTP
  // del wizard se guarda con el slug de la tienda.
  const store = { public_id: ref.store_public_id, name: ref.name, slug: slug.toLowerCase() }

  return (
    <div className="min-h-screen py-8 px-4 sm:py-10" style={{ background: colors2000s.bg.primary }}>
      <header className="max-w-2xl mx-auto mb-6 text-center sm:mb-8">
        <h1
          className="break-words text-3xl font-black tracking-tighter uppercase"
          style={{ color: colors2000s.orange.accent }}
        >
          {store.name}
        </h1>
        {acceptsNewBookings ? (
          <Link
            to={`/b/${store.slug}`}
            className="mx-auto mt-2 inline-flex min-h-11 items-center justify-center rounded-xl border px-4 py-2 text-xs font-black uppercase tracking-widest"
            style={buttonStyles2000s.default}
          >
            Reservar un turno nuevo
          </Link>
        ) : (
          <p className="mt-2 text-xs font-bold" style={{ color: colors2000s.text.secondary }}>
            Este negocio no está tomando reservas nuevas por ahora. Podés ver, cambiar o cancelar
            tus turnos.
          </p>
        )}
      </header>

      <main>
        <ClientAppointmentsContainer store={store} />
      </main>

      <div className="max-w-2xl mx-auto mt-10 text-center">
        <LegalFooterLinks depositPolicy={vitrina?.deposit_policy} />
      </div>
    </div>
  )
}

export default ClientAppointmentsPage
