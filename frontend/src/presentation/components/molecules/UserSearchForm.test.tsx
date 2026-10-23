import { fireEvent, render, screen } from '@testing-library/react'

import { UserSearchForm } from './UserSearchForm'

describe('UserSearchForm', () => {
  it('expone un landmark de búsqueda con nombre accesible', () => {
    render(<UserSearchForm onSearch={jest.fn()} />)

    expect(screen.getByRole('search', { name: 'Buscar usuarios' })).toBeInTheDocument()
    expect(screen.getByRole('searchbox', { name: 'Buscar usuario' })).toBeInTheDocument()
  })

  it('muestra foco de teclado visible y mantiene el botón en 44 px como mínimo', () => {
    render(<UserSearchForm onSearch={jest.fn()} />)

    const input = screen.getByRole('searchbox', { name: 'Buscar usuario' })
    const submit = screen.getByRole('button', { name: 'Buscar' })

    for (const control of [input, submit]) {
      expect(control).toHaveClass('focus-visible:outline')
      expect(control).toHaveClass('focus-visible:outline-2')
      expect(control).toHaveClass('focus-visible:outline-offset-2')
      expect(control).toHaveClass('focus-visible:outline-[#c65300]')
    }
    expect(submit).toHaveClass('min-h-11')
  })

  it('envía con Enter el término escrito una sola vez', () => {
    const onSearch = jest.fn()
    render(<UserSearchForm onSearch={onSearch} />)

    const input = screen.getByRole('searchbox', { name: 'Buscar usuario' })
    fireEvent.change(input, { target: { value: '  Ana Gómez  ' } })
    // Enter on a search input triggers the containing form's submit event.
    fireEvent.submit(input.closest('form')!)

    expect(onSearch).toHaveBeenCalledTimes(1)
    expect(onSearch).toHaveBeenCalledWith('  Ana Gómez  ')
  })

  it('envía con el botón el término escrito una sola vez', () => {
    const onSearch = jest.fn()
    render(<UserSearchForm onSearch={onSearch} />)

    fireEvent.change(screen.getByRole('searchbox', { name: 'Buscar usuario' }), {
      target: { value: 'ana@example.com' }
    })
    fireEvent.click(screen.getByRole('button', { name: 'Buscar' }))

    expect(onSearch).toHaveBeenCalledTimes(1)
    expect(onSearch).toHaveBeenCalledWith('ana@example.com')
  })
})
