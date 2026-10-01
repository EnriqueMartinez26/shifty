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

const renderCard = (isActive: boolean) => {
  const handlers = { onEdit: jest.fn(), onDelete: jest.fn(), onReactivate: jest.fn() }
  const view = render(
    <ServiceCard service={ServiceMapper.toDomain({ ...dto, is_active: isActive })} {...handlers} />
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
})
