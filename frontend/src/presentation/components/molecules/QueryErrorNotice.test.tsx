import { render, screen } from '@testing-library/react'

import { ForbiddenError } from '@shared/errors'

import { QueryErrorNotice } from './QueryErrorNotice'

describe('QueryErrorNotice', () => {
  it('sin error no muestra nada', () => {
    const { container } = render(<QueryErrorNotice error={null} message="No se pudo cargar" />)

    expect(container.innerHTML).toBe('')
  })

  it('con un error muestra el mensaje neutro, no el del servidor', () => {
    render(
      <QueryErrorNotice error={new Error('relation "x" does not exist')} message="No se pudo" />
    )

    expect(screen.getByRole('alert')).toHaveTextContent('No se pudo')
    expect(screen.queryByText(/relation/)).not.toBeInTheDocument()
  })

  it.each([
    ['directo', new ForbiddenError('Prohibido', { errorCode: 'FEATURE_DISABLED' })],
    [
      'envuelto por BaseService',
      Object.assign(new Error('Prohibido'), {
        originalError: new ForbiddenError('Prohibido', { errorCode: 'FEATURE_DISABLED' })
      })
    ]
  ])('un 403 FEATURE_DISABLED (%s) dice que la funcion no esta habilitada', (_, error) => {
    render(<QueryErrorNotice error={error} message="No se pudo" />)

    expect(screen.getByRole('alert')).toHaveTextContent(
      'Esta función no está habilitada para tu negocio.'
    )
  })
})
