import React from 'react'

import { StaffManagementContainer } from '@presentation/containers/StaffManagementContainer'

import { useDocumentTitle } from '../hooks/useDocumentTitle'

const StaffPage: React.FC = () => {
  useDocumentTitle('Personal · Shifty')
  return (
    <div className="duration-700">
      <StaffManagementContainer />
    </div>
  )
}

export default StaffPage
