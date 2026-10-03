import { render } from '@testing-library/react'

import { createEmptyAdminForm, createEmptyStoreForm, createEmptyUserForm } from './shared'
import { StoreModals } from './StoreModals'
import { UserModals } from './UserModals'

const idle = { isPending: false }

const passwordInput = (): HTMLInputElement => {
  const input = document.querySelector<HTMLInputElement>('input[type="password"]')
  if (!input) throw new Error('el modal no renderizo el campo de contraseña')
  return input
}

/**
 * L1: el superadmin pedia 8 caracteres y el backend exige lo mismo que el resto
 * (`StoreAdminCreate`, `UserGlobalUpdate`); una clave que el backend rechaza
 * pasaba el formulario y volvia como 422.
 *
 * 2026-10-01, D-20261001-01: el piso era 12; ahora es 6, con tope de 64
 * caracteres (el HTML cuenta unidades UTF-16: es solo una guarda, la regla
 * completa la aplica `validateNewPassword`).
 */
describe('contrasenas del superadmin', () => {
  it('crear admin pide el mismo piso de 6 y tope de 64 que el backend', () => {
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

    expect(passwordInput()).toHaveAttribute('minlength', '6')
    expect(passwordInput()).toHaveAttribute('maxlength', '128')
    expect(passwordInput()).toHaveAttribute('autocomplete', 'new-password')
  })

  it('cambiar la clave de un usuario pide el mismo piso de 6 y tope de 64 que el backend', () => {
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

    expect(passwordInput()).toHaveAttribute('minlength', '6')
    expect(passwordInput()).toHaveAttribute('maxlength', '128')
    expect(passwordInput()).toHaveAttribute('autocomplete', 'new-password')
  })
})
