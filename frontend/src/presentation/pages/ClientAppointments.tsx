import React from 'react'

import { Link, useParams } from 'react-router'

import { ClientAppointmentsContainer } from '@presentation/containers/ClientAppointmentsContainer'

import { colors2000s } from '../../theme/colors'
import LegalFooterLinks from '../components/navigation/LegalFooterLinks'
import { usePublicStore, usePublicStoreRef } from '../hooks/usePublic'

const ClientAppointmentsPage: React.FC = () => {
  const { slug = '' } = useParams()
  // FF-16: la vitrina (/public/stores/{slug}) da 404 con la tienda suspendida
  // y el cliente se quedaba sin cancelar ni reprogramar, que siguen
  // permitidos. El ref responde tambien entonces, con el mismo 404 neutro si
  // la tienda no existe.
  const { data: ref, isLoading, isError } = usePublicStoreRef(slug)
  const acceptsNewBookings = ref?.accepts_new_bookings === true
  // La politica de sena del pie solo la trae la vitrina: se pide cuando no va
  // a dar 404.
  const { data: vitrina } = usePublicStore(slug, acceptsNewBookings)

  if (isLoading) {
    return (
      <div className="min-h-screen grid place-items-center bg-[#EEF2F6] text-sm font-black uppercase tracking-widest text-gray-500">
        Cargando...
      </div>
    )
  }

  if (isError || !ref) {
    return (
      <div className="min-h-screen grid place-items-center bg-[#EEF2F6] text-sm font-black uppercase tracking-widest text-red-500">
        Negocio no encontrado
      </div>
    )
  }

  // El slug canonico es minuscula: la URL la tipean humanos y la marca de OTP
  // del wizard se guarda con el slug de la tienda.
  const store = { public_id: ref.store_public_id, name: ref.name, slug: slug.toLowerCase() }

  return (
    <div className="min-h-screen bg-[#EEF2F6] py-10 px-4">
      <header className="max-w-2xl mx-auto mb-8 text-center">
        <h1
          className="text-3xl font-black tracking-tighter uppercase"
          style={{ color: colors2000s.orange.accent }}
        >
          {store.name}
        </h1>
        {acceptsNewBookings ? (
          <Link
            to={`/b/${store.slug}`}
            className="text-[10px] font-black uppercase tracking-widest"
            style={{ color: colors2000s.text.secondary }}
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

      <ClientAppointmentsContainer store={store} />

      <div className="max-w-2xl mx-auto mt-10 text-center">
        <LegalFooterLinks depositPolicy={vitrina?.deposit_policy} />
      </div>
    </div>
  )
}

export default ClientAppointmentsPage
