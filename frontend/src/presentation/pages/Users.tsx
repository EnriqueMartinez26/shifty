import React from 'react'

import { UserManagementContainer } from '@presentation/containers/UserManagementContainer'

import { useDocumentTitle } from '../hooks/useDocumentTitle'

const UsersPage: React.FC = () => {
  useDocumentTitle('Usuarios · Shifty')
  return (
    <div className="duration-700">
      <UserManagementContainer />
    </div>
  )
}

export default UsersPage
