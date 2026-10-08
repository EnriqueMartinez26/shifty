import type { ComponentProps } from 'react'

import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'

import type { StaffSchedule } from '@domain/entities/Staff'

import { ValidationError } from '@shared/errors'

import { StaffScheduleModal } from './StaffScheduleModal'

/**
 * 2026-10-08: el manual le pide al admin "A cada persona cargale sus días y
 * horas de trabajo" y no habia donde. "Lucas solo trabaja martes a sabado"
 * no se podia cargar: todos heredaban el horario de la tienda.
 */

const STORE_HOURS = {
  mon: [{ open: '09:00', close: '18:00' }],
  tue: [{ open: '09:00', close: '18:00' }],
  wed: [],
  thu: [],
  fri: [],
  sat: [],
  sun: []
}

const renderModal = (
  props: Partial<ComponentProps<typeof StaffScheduleModal>> & {
    schedules?: readonly StaffSchedule[]
  } = {}
) => {
  const onSave = (props.onSave as jest.Mock | undefined) ?? jest.fn().mockResolvedValue(undefined)
  const onClose = props.onClose ?? jest.fn()
  render(
    <StaffScheduleModal
      staffName="Lucas"
      schedules={props.schedules ?? []}
      storeBusinessHours={'storeBusinessHours' in props ? props.storeBusinessHours : STORE_HOURS}
      readOnlyReason={props.readOnlyReason ?? null}
      onSave={onSave}
      onClose={onClose}
    />
  )
  return { onSave, onClose }
}

const day = (label: string) => screen.getByRole('region', { name: label })
const save = () => screen.getByRole('button', { name: /guardar horario/i })

describe('StaffScheduleModal', () => {
  it('sin franjas arranca en "usa el horario de la tienda" y muestra ese horario', () => {
    renderModal()

    expect(screen.getByRole('radio', { name: /usa el horario de la tienda/i })).toHaveAttribute(
      'aria-checked',
      'true'
    )
    const lista = screen.getByRole('list', { name: /horario de la tienda/i })
    expect(within(lista).getByText('Lunes').parentElement).toHaveTextContent('09:00 a 18:00')
    expect(within(lista).getByText('Domingo').parentElement).toHaveTextContent('Cerrado')
  })

  it('guardar en modo tienda manda la semana vacia', async () => {
    const { onSave, onClose } = renderModal({
      schedules: [{ dayOfWeek: 1, startTime: '10:00:00', endTime: '14:00:00' }]
    })

    fireEvent.click(screen.getByRole('radio', { name: /usa el horario de la tienda/i }))
    fireEvent.click(save())

    await waitFor(() => expect(onSave).toHaveBeenCalledWith([]))
    expect(onClose).toHaveBeenCalled()
  })

  it('"Lucas solo trabaja martes a sabado": cierra lunes y domingo y guarda el resto', async () => {
    const { onSave } = renderModal()

    fireEvent.click(screen.getByRole('radio', { name: /horario propio/i }))
    // Parte del horario de la tienda: lunes y martes abiertos.
    fireEvent.click(within(day('Martes')).getByRole('button', { name: /copiar a todos/i }))
    fireEvent.click(within(day('Lunes')).getByRole('button', { name: /lunes: atiende/i }))
    fireEvent.click(within(day('Domingo')).getByRole('button', { name: /domingo: atiende/i }))
    fireEvent.click(save())

    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1))
    const guardado = onSave.mock.calls[0][0] as StaffSchedule[]
    expect(guardado.map((franja) => franja.dayOfWeek)).toEqual([1, 2, 3, 4, 5])
    expect(guardado.every((f) => f.startTime === '09:00:00' && f.endTime === '18:00:00')).toBe(true)
  })

  it('un horario partido: dos franjas el mismo dia', async () => {
    const { onSave } = renderModal({
      schedules: [{ dayOfWeek: 0, startTime: '09:00:00', endTime: '13:00:00' }]
    })

    fireEvent.click(within(day('Lunes')).getByRole('button', { name: /agregar franja/i }))
    const hasta = within(day('Lunes')).getByLabelText('Lunes, franja 2: hasta')
    fireEvent.change(hasta, { target: { value: '19:00' } })
    fireEvent.click(save())

    await waitFor(() =>
      expect(onSave).toHaveBeenCalledWith([
        { dayOfWeek: 0, startTime: '09:00:00', endTime: '13:00:00' },
        { dayOfWeek: 0, startTime: '13:00:00', endTime: '19:00:00' }
      ])
    )
  })

  it('franjas superpuestas: avisa en el dia y no deja guardar', () => {
    const { onSave } = renderModal({
      schedules: [
        { dayOfWeek: 2, startTime: '09:00:00', endTime: '13:00:00' },
        { dayOfWeek: 2, startTime: '14:00:00', endTime: '18:00:00' }
      ]
    })

    fireEvent.change(within(day('Miércoles')).getByLabelText('Miércoles, franja 2: desde'), {
      target: { value: '12:00' }
    })

    expect(within(day('Miércoles')).getByText(/se superponen/)).toBeInTheDocument()
    expect(save()).toBeDisabled()
    fireEvent.click(save())
    expect(onSave).not.toHaveBeenCalled()
  })

  it('un horario propio sin ningun dia avisa en vez de volver en silencio a la tienda', () => {
    renderModal({ schedules: [{ dayOfWeek: 3, startTime: '09:00:00', endTime: '13:00:00' }] })

    fireEvent.click(within(day('Jueves')).getByRole('button', { name: /quitar franja 1/i }))

    expect(screen.getByRole('alert')).toHaveTextContent(/al menos un día/)
    expect(save()).toBeDisabled()
  })

  it('el error del backend se ve en el pie, junto al boton, nombrando el dia', async () => {
    const onSave = jest.fn().mockRejectedValue(
      new ValidationError('x', {
        errorCode: 'SCHEDULE_OVERLAP',
        statusCode: 422,
        detail: { day_of_week: 4 }
      })
    )
    const { onClose } = renderModal({
      onSave,
      schedules: [{ dayOfWeek: 4, startTime: '09:00:00', endTime: '13:00:00' }]
    })

    fireEvent.click(save())

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'El Viernes tiene franjas que se superponen.'
    )
    expect(onClose).not.toHaveBeenCalled()
  })

  it('con la tienda suspendida se ve la semana pero no se edita ni se guarda', () => {
    renderModal({
      readOnlyReason: 'Tienda suspendida',
      schedules: [{ dayOfWeek: 0, startTime: '09:00:00', endTime: '13:00:00' }]
    })

    expect(screen.getByText('Tienda suspendida')).toBeInTheDocument()
    expect(within(day('Lunes')).getByLabelText('Lunes, franja 1: desde')).toBeDisabled()
    expect(screen.getByRole('radio', { name: /horario propio/i })).toBeDisabled()
    expect(save()).toBeDisabled()
    expect(save()).toHaveAttribute('title', 'Tienda suspendida')
  })

  it('sin el horario de la tienda cargado, el horario propio arranca cerrado', () => {
    renderModal({ storeBusinessHours: undefined })

    expect(screen.getByText(/cargando el horario de la tienda/i)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('radio', { name: /horario propio/i }))

    expect(
      within(day('Lunes')).getByRole('button', { name: /lunes: no atiende/i })
    ).toBeInTheDocument()
    expect(save()).toBeDisabled()
  })
})
