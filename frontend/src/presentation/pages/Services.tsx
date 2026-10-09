import React from 'react'

import { ServiceManagementContainer } from '@presentation/containers/ServiceManagementContainer'

import { useDocumentTitle } from '../hooks/useDocumentTitle'

const ServicesPage: React.FC = () => {
  useDocumentTitle('Servicios · Shifty')
  return (
    <div className="duration-700">
      <ServiceManagementContainer />
    </div>
  )
}

export default ServicesPage
