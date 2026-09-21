import { fireEvent, render, screen, waitFor } from '@testing-library/react'

import { Service } from '@domain/entities/Service'

import { ServiceFormModal } from './ServiceFormModal'

/**
 * El riesgo de F10-03 no es "falta un campo": es que el formulario de edicion
 * arranque en los defaults y guardar APAGUE una seña ya configurada, dejando
 * de cobrarle a la tienda. Toda la proteccion vive en el `useEffect` que carga
 * los valores reales, asi que es lo que se prueba aca: montando el componente,
 * no armando a mano el payload que el mapper despues copia.
 */
const servicioConSena = () =>
  Service.fromPrimitives({
    id: 'svc_1',
    name: 'Corte premium',
    description: 'Con lavado',
    duration_minutes: 45,
    price: 12000,
    color: '#3b82f6',
    image_url: null,
    youtube_trailer_url: null,
    is_active: true,
    deposit_mode: 'required',
    deposit_type: 'percent',
    deposit_amount: 50
  })

const montoDeSena = () => screen.getByLabelText<HTMLInputElement>(/Porcentaje \(%\)|Monto fijo/)

describe('ServiceFormModal — politica de sena', () => {
  it('al editar, los controles arrancan con la sena REAL del servicio', () => {
    render(
      <ServiceFormModal
        isOpen
        onClose={jest.fn()}
        onSubmit={jest.fn()}
        editingService={servicioConSena()}
      />
    )

    expect(screen.getByDisplayValue('Corte premium')).toBeInTheDocument()
    // Si esto diera 'none'/'percent'/vacio, guardar apagaria la sena.
    expect(screen.getByLabelText<HTMLSelectElement>(/Modo/i).value).toBe('required')
    expect(screen.getByLabelText<HTMLSelectElement>(/Tipo/i).value).toBe('percent')
    expect(montoDeSena().value).toBe('50')
  })

  it('cambiar solo el nombre manda la sena intacta', async () => {
    // El escenario exacto que la auditoria marca como riesgo: el dueño entra a
    // corregir el nombre y no toca la sena.
    const onSubmit = jest.fn().mockResolvedValue(undefined)
    render(
      <ServiceFormModal
        isOpen
        onClose={jest.fn()}
        onSubmit={onSubmit}
        editingService={servicioConSena()}
      />
    )

    fireEvent.change(screen.getByDisplayValue('Corte premium'), {
      target: { value: 'Corte premium plus' }
    })
    fireEvent.click(screen.getByRole('button', { name: /Guardar/i }))

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1))
    expect(onSubmit.mock.calls[0]?.[0]).toMatchObject({
      name: 'Corte premium plus',
      depositMode: 'required',
      depositType: 'percent',
      depositAmount: 50
    })
  })

  it('un servicio nuevo arranca sin sena', () => {
    render(<ServiceFormModal isOpen onClose={jest.fn()} onSubmit={jest.fn()} />)

    expect(screen.getByLabelText<HTMLSelectElement>(/Modo/i).value).toBe('none')
    // Con la sena apagada no se pide ni tipo ni monto.
    expect(screen.queryByLabelText(/Porcentaje \(%\)|Monto fijo/)).not.toBeInTheDocument()
  })

  it('un porcentaje mayor a 100 no traba la edicion', async () => {
    // El formulario no puede ser mas estricto que el backend, que acepta hasta
    // 10.000.000 para cualquier tipo. Con `max=100` en el input, un servicio
    // cargado con 500% quedaba imposible de editar: la validacion nativa
    // bloqueaba el submit en un campo que el dueño ni habia tocado.
    const onSubmit = jest.fn().mockResolvedValue(undefined)
    const legado = Service.fromPrimitives({
      ...servicioConSena().toPrimitives(),
      deposit_amount: 500
    })

    render(
      <ServiceFormModal isOpen onClose={jest.fn()} onSubmit={onSubmit} editingService={legado} />
    )

    expect(montoDeSena().value).toBe('500')
    expect(montoDeSena()).not.toHaveAttribute('max')

    fireEvent.change(screen.getByDisplayValue('Corte premium'), {
      target: { value: 'Renombrado' }
    })
    fireEvent.click(screen.getByRole('button', { name: /Guardar/i }))

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1))
    expect(onSubmit.mock.calls[0]?.[0]).toMatchObject({ depositAmount: 500 })
  })
})
