import { fireEvent, render } from '@testing-library/react'

import type { ServiceResponseDTO } from '@application/dtos/ServiceDTO'
import { ServiceMapper } from '@application/mappers/ServiceMapper'

import { ServiceCard } from './ServiceCard'

/**
 * 2026-09-30 (FF-22): un servicio eliminado o desactivado desaparecia del panel
 * y no se podia reactivar. "Eliminar" es un soft delete, asi que un inactivo
 * ofrece "Reactivar" en su lugar.
 */
const dto: ServiceResponseDTO = {
  public_id: 'svc-1',
  name: 'Corte',
  description: null,
  duration_minutes: 30,
  price: 10000,
  color: '#3b82f6',
  image_url: null,
  youtube_trailer_url: null,
  deposit_mode: 'none',
  deposit_type: 'percent',
  deposit_amount: null,
  is_active: true
}

const renderCard = (isActive: boolean, readOnlyReason: string | null = null) => {
  const handlers = { onEdit: jest.fn(), onDelete: jest.fn(), onReactivate: jest.fn() }
  const view = render(
    <ServiceCard
      service={ServiceMapper.toDomain({ ...dto, is_active: isActive })}
      readOnlyReason={readOnlyReason}
      {...handlers}
    />
  )
  return { ...view, ...handlers }
}

describe('ServiceCard', () => {
  it('un servicio activo ofrece Eliminar y no Reactivar', () => {
    const { getByRole, queryByRole, onDelete } = renderCard(true)

    fireEvent.click(getByRole('button', { name: /eliminar/i }))

    expect(onDelete).toHaveBeenCalledWith('svc-1')
    expect(queryByRole('button', { name: /reactivar/i })).toBeNull()
  })

  it('un servicio inactivo ofrece Reactivar y no Eliminar', () => {
    const { getByRole, queryByRole, onReactivate, onDelete } = renderCard(false)

    fireEvent.click(getByRole('button', { name: /reactivar/i }))

    expect(onReactivate).toHaveBeenCalledWith('svc-1')
    expect(queryByRole('button', { name: /eliminar/i })).toBeNull()
    expect(onDelete).not.toHaveBeenCalled()
  })

  it('un servicio inactivo se ve atenuado', () => {
    const { getByTestId } = renderCard(false)

    expect(getByTestId('service-card').classList.contains('opacity-60')).toBe(true)
  })

  it('un servicio activo no se atenua', () => {
    const { getByTestId } = renderCard(true)

    expect(getByTestId('service-card').classList.contains('opacity-60')).toBe(false)
  })

  // 2026-10-01: con la tienda suspendida cada accion fallaba con 402 en vez de
  // verse deshabilitada (FF-15). PATCH y DELETE /services/{id} no estan en
  // SUSPENSION_ALLOWED_WRITES.
  it.each([
    [true, /editar/i],
    [true, /eliminar/i],
    [false, /reactivar/i]
  ])('con la tienda suspendida (activo=%s) %s queda deshabilitado', (isActive, name) => {
    const { getByRole } = renderCard(isActive, 'Tienda suspendida')

    const button = getByRole('button', { name })
    expect(button).toBeDisabled()
    expect(button).toHaveAttribute('title', 'Tienda suspendida')
  })

  // 2026-10-02 (F4-15): la imagen no tenia tamano ni carga diferida; el panel
  // de servicios bajaba todas las fotos al abrirse y la grilla saltaba al
  // llegar cada una.
  it('la imagen del servicio reserva su caja de 48 px y carga diferida', () => {
    const { getByRole } = render(
      <ServiceCard
        service={ServiceMapper.toDomain({ ...dto, image_url: 'https://cdn.test/corte.png' })}
        readOnlyReason={null}
        onEdit={jest.fn()}
        onDelete={jest.fn()}
        onReactivate={jest.fn()}
      />
    )

    const img = getByRole('img', { name: 'Corte' })
    expect(img).toHaveAttribute('loading', 'lazy')
    expect(img).toHaveAttribute('decoding', 'async')
    expect(img).toHaveAttribute('width', '48')
    expect(img).toHaveAttribute('height', '48')
  })

  it('sin suspension Editar y Eliminar siguen habilitados', () => {
    const { getByRole } = renderCard(true)

    expect(getByRole('button', { name: /editar/i })).not.toBeDisabled()
    expect(getByRole('button', { name: /eliminar/i })).not.toBeDisabled()
  })
})
