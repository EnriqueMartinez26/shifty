import { render } from '@testing-library/react'

import { createEmptyAdminForm, createEmptyStoreForm, createEmptyUserForm } from './shared'
import { StoreModals } from './StoreModals'
import { UserModals } from './UserModals'

const idle = { isPending: false }

const passwordInput = (): HTMLInputElement => {
  const input = document.querySelector<HTMLInputElement>('input[type="password"]')
  if (!input) throw new Error('el modal no renderizo el campo de contrasena')
  return input
}

/**
 * L1: el superadmin pedia 8 caracteres y el backend exige 12
 * (`StoreAdminCreate`, `UserGlobalUpdate`); una clave de 8 a 11 pasaba el formulario y
 * volvia como 422.
 */
describe('contrasenas del superadmin', () => {
  it('crear admin pide el mismo piso de 12 que el backend', () => {
    render(
      <StoreModals
        modal="create-admin"
        closeModal={jest.fn()}
        modalError={null}
        selectedStore={null}
        storeForm={createEmptyStoreForm()}
        setStoreForm={jest.fn()}
        handleStoreSubmit={jest.fn()}
        createStoreMutation={idle}
        updateStoreMutation={idle}
        adminForm={createEmptyAdminForm()}
        setAdminForm={jest.fn()}
        handleAdminSubmit={jest.fn()}
        createAdminMutation={idle}
      />
    )

    expect(passwordInput()).toHaveAttribute('minlength', '12')
  })

  it('cambiar la clave de un usuario pide el mismo piso de 12 que el backend', () => {
    render(
      <UserModals
        modal="edit-user"
        closeModal={jest.fn()}
        modalError={null}
        userForm={createEmptyUserForm()}
        setUserForm={jest.fn()}
        handleUserSubmit={jest.fn()}
        updateUserMutation={idle}
      />
    )

    expect(passwordInput()).toHaveAttribute('minlength', '12')
  })
})
