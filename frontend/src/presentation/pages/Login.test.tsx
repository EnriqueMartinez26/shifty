import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router'

import LoginPage from './Login'

/**
 * 2026-09-28 (FF-36, D-20260928-06). Sintoma: al vencer la sesion el login
 * mandaba siempre a la ruta por defecto del rol y se perdia donde estaba.
 */

const mockMutateAsync = jest.fn()

jest.mock('../hooks/useLogin', () => ({
  useLogin: () => ({ mutateAsync: mockMutateAsync, isPending: false })
}))

const entrarDesde = (from: string) => {
  mockMutateAsync.mockResolvedValue({
    access_token: 't',
    user: { email: 'a@x.com', role: 'store_admin', store_id: 's1', public_id: 'usr-a' }
  })
  render(
    <MemoryRouter initialEntries={[{ pathname: '/login', state: { from } }]}>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/dashboard" element={<p>inicio</p>} />
        <Route path="/dashboard/calendar" element={<p>agenda</p>} />
      </Routes>
    </MemoryRouter>
  )
  fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'a@x.com' } })
  fireEvent.change(screen.getByLabelText('Contraseña'), { target: { value: 'clave' } })
  fireEvent.click(screen.getByRole('button', { name: /Entrar al Panel/ }))
}

describe('LoginPage', () => {
  it('vuelve a la ruta interna donde estaba', async () => {
    entrarDesde('/dashboard/calendar')

    expect(await screen.findByText('agenda')).toBeInTheDocument()
  })

  it('ignora un destino externo y va a la ruta del rol', async () => {
    entrarDesde('//evil.com/dashboard')

    expect(await screen.findByText('inicio')).toBeInTheDocument()
  })
})
