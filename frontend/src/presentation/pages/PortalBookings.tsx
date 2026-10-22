import React from 'react'

import { PortalBookingsContainer } from '@presentation/containers/PortalBookingsContainer'

import { useDocumentTitle } from '../hooks/useDocumentTitle'

const PortalBookingsPage: React.FC = () => {
  useDocumentTitle('Reservas del portal · Shifty')
  return (
    <div className="duration-700">
      <PortalBookingsContainer />
    </div>
  )
}

export default PortalBookingsPage
