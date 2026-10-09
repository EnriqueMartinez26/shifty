import React from 'react'

import { WaitlistContainer } from '@presentation/containers/WaitlistContainer'

import { useDocumentTitle } from '../hooks/useDocumentTitle'

const WaitlistPage: React.FC = () => {
  useDocumentTitle('Lista de espera · Shifty')
  return (
    <div className="duration-700">
      <WaitlistContainer />
    </div>
  )
}

export default WaitlistPage
