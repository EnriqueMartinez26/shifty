import React from 'react'

import { useParams } from 'react-router'

import { ClientAppointmentsContainer } from '@presentation/containers/ClientAppointmentsContainer'

import { colors2000s } from '../../theme/colors'
import LegalFooterLinks from '../components/navigation/LegalFooterLinks'
import { usePublicStore } from '../hooks/usePublic'

const ClientAppointmentsPage: React.FC = () => {
  const { slug = '' } = useParams()
  const { data: store, isLoading, isError } = usePublicStore(slug)

  if (isLoading) {
    return (
      <div className="min-h-screen grid place-items-center bg-[#EEF2F6] text-sm font-black uppercase tracking-widest text-gray-500">
        Cargando...
      </div>
    )
  }

  if (isError || !store) {
    return (
      <div className="min-h-screen grid place-items-center bg-[#EEF2F6] text-sm font-black uppercase tracking-widest text-red-500">
        Negocio no encontrado
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-[#EEF2F6] py-10 px-4">
      <header className="max-w-2xl mx-auto mb-8 text-center">
        <h1
          className="text-3xl font-black tracking-tighter uppercase"
          style={{ color: colors2000s.orange.accent }}
        >
          {store.name}
        </h1>
        <a
          href={`/b/${store.slug}`}
          className="text-[10px] font-black uppercase tracking-widest"
          style={{ color: colors2000s.text.secondary }}
        >
          Reservar un turno nuevo
        </a>
      </header>

      <ClientAppointmentsContainer store={store} />

      <div className="max-w-2xl mx-auto mt-10 text-center">
        <LegalFooterLinks depositPolicy={store.deposit_policy} />
      </div>
    </div>
  )
}

export default ClientAppointmentsPage
