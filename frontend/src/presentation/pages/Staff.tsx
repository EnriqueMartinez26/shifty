import React from 'react'

import { StaffManagementContainer } from '@presentation/containers/StaffManagementContainer'

const StaffPage: React.FC = () => {
  return (
    <div className="animate-in fade-in slide-in-from-bottom-4 duration-700">
      <StaffManagementContainer />
    </div>
  )
}

export default StaffPage
