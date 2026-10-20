import { fireEvent, render, screen } from '@testing-library/react'
import { format } from 'date-fns'

import { BookingStepDateTime } from './BookingStepDateTime'
import { colors2000s } from '../../../../theme/colors'

const asRgb = (hex: string): string =>
  `rgb(${[1, 3, 5].map((offset) => parseInt(hex.slice(offset, offset + 2), 16)).join(', ')})`

const mockAvailability = jest.fn()
const mockStaff = jest.fn()

jest.mock('@presentation/hooks/usePublic', () => ({
  usePublicAvailability: (...args: unknown[]) => mockAvailability(...args),
  usePublicStaff: (...args: unknown[]) => mockStaff(...args),
  useJoinWaitlist: () => ({ mutateAsync: jest.fn(), isPending: false, isSuccess: false })
}))

describe('BookingStepDateTime', () => {
  beforeEach(() => {
    mockAvailability.mockReset()
    mockStaff.mockReset()
    mockStaff.mockReturnValue({ data: [], isLoading: false })
  })

  it('incluye el texto visible "Hoy" al principio del nombre accesible de la fecha actual', () => {
    mockAvailability.mockReturnValue({ isLoading: false, data: [] })

    render(
      <BookingStepDateTime
        storePublicId="store-1"
        serviceId="svc-1"
        staffId={null}
        selectedDate={null}
        selectedTime={null}
        onSelect={() => undefined}
        onBack={() => undefined}
      />
    )

    const fechaDeHoy = screen.getByRole('button', { name: /^Hoy,/ })
    expect(fechaDeHoy).toHaveTextContent('Hoy')
  })

  it('muestra los slots en hora argentina y entrega el instante UTC al elegir', () => {
    // Regresion 2026-09-10: se mostraba la hora UTC del slot ("00:00" para un
    // turno de 21:00) y al reservar se recomponia fecha local + esa hora, con lo
    // que el turno caia en el dia anterior.
    mockAvailability.mockReturnValue({
      isLoading: false,
      data: [
        {
          staff_id: 'st-1',
          staff_name: 'Pro',
          starts_at: '2026-09-15T12:00:00+00:00',
          ends_at: '2026-09-15T12:30:00+00:00',
          status: 'available',
          reason: null
        },
        {
          staff_id: 'st-1',
          staff_name: 'Pro',
          starts_at: '2026-09-16T00:00:00+00:00',
          ends_at: '2026-09-16T00:30:00+00:00',
          status: 'available',
          reason: null
        }
      ]
    })
    const onSelect = jest.fn()

    render(
      <BookingStepDateTime
        storePublicId="store-1"
        serviceId="svc-1"
        staffId="st-1"
        selectedDate={null}
        selectedTime={null}
        onSelect={onSelect}
        onBack={() => undefined}
      />
    )

    expect(screen.getByText('09:00')).toBeInTheDocument()
    expect(screen.getByText('21:00')).toBeInTheDocument()
    expect(screen.queryByText('00:00')).not.toBeInTheDocument()
    expect(screen.queryByText('12:00')).not.toBeInTheDocument()

    fireEvent.click(screen.getByText('21:00'))

    expect(onSelect).toHaveBeenCalledTimes(1)
    const [, hora, staff, , startsAt] = onSelect.mock.calls[0] as [
      string,
      string,
      string,
      string | null,
      string
    ]
    expect(hora).toBe('21:00')
    expect(staff).toBe('st-1')
    expect(startsAt).toBe('2026-09-16T00:00:00+00:00')
  })

  it('con "cualquier profesional" agrupa por hora argentina y prefiere el slot disponible', () => {
    mockAvailability.mockReturnValue({
      isLoading: false,
      data: [
        {
          staff_id: 'st-1',
          staff_name: 'Ana',
          starts_at: '2026-09-15T12:00:00+00:00',
          ends_at: '2026-09-15T12:30:00+00:00',
          status: 'booked',
          reason: null
        },
        {
          staff_id: 'st-2',
          staff_name: 'Bruno',
          starts_at: '2026-09-15T12:00:00+00:00',
          ends_at: '2026-09-15T12:30:00+00:00',
          status: 'available',
          reason: null
        }
      ]
    })

    render(
      <BookingStepDateTime
        storePublicId="store-1"
        serviceId="svc-1"
        staffId={null}
        selectedDate={null}
        selectedTime={null}
        onSelect={() => undefined}
        onBack={() => undefined}
      />
    )

    expect(screen.getAllByText('09:00')).toHaveLength(1)
    expect(screen.getByText('Bruno')).toBeInTheDocument()
    expect(screen.queryByText('Ana')).not.toBeInTheDocument()
  })

  // 2026-10-16: la confirmacion muestra quien atiende; con "Cualquiera" es el
  // que asigno el horario, y una cancha no se presenta como profesional.
  it('al elegir entrega quien atiende el slot y si es una cancha o sala', () => {
    mockStaff.mockReturnValue({
      isLoading: false,
      data: [
        { public_id: 'st-1', kind: 'person', display_name: 'Ana', service_ids: ['svc-1'] },
        { public_id: 'st-2', kind: 'resource', display_name: 'Cancha 1', service_ids: ['svc-1'] }
      ]
    })
    mockAvailability.mockReturnValue({
      isLoading: false,
      data: [
        {
          staff_id: 'st-2',
          staff_name: 'Cancha 1',
          starts_at: '2026-09-15T12:00:00+00:00',
          ends_at: '2026-09-15T12:30:00+00:00',
          status: 'available',
          reason: null
        }
      ]
    })
    const onSelect = jest.fn()

    render(
      <BookingStepDateTime
        storePublicId="store-1"
        serviceId="svc-1"
        staffId={null}
        selectedDate={null}
        selectedTime={null}
        onSelect={onSelect}
        onBack={() => undefined}
      />
    )
    fireEvent.click(screen.getByText('09:00'))

    expect(onSelect.mock.calls[0]?.[5]).toEqual({ name: 'Cancha 1', isResource: true })
  })

  // 2026-10-14: de noche todo el dia quedaba 'blocked' por el aviso minimo y el
  // cliente veia 18 botones grises. El portal solo ofrece horarios libres.
  const slotDe = (staff_id: string, staff_name: string, status: string) => ({
    staff_id,
    staff_name,
    starts_at: '2026-09-15T12:00:00+00:00',
    ends_at: '2026-09-15T12:30:00+00:00',
    status,
    reason: null
  })
  const montarCon = (staffId: string | null, onEmpty?: () => void) =>
    render(
      <BookingStepDateTime
        storePublicId="store-1"
        serviceId="svc-1"
        staffId={staffId}
        selectedDate={null}
        selectedTime={null}
        onSelect={() => undefined}
        onBack={() => undefined}
        onEmptyAvailability={onEmpty}
      />
    )
  const montarConSelect = (staffId: string | null, onSelect: jest.Mock) =>
    render(
      <BookingStepDateTime
        storePublicId="store-1"
        serviceId="svc-1"
        staffId={staffId}
        selectedDate={null}
        selectedTime={null}
        onSelect={onSelect}
        onBack={() => undefined}
      />
    )

  it.each([
    ['Cualquiera', null],
    ['un profesional elegido', 'st-1']
  ])(
    'con %s los horarios no disponibles no se muestran y aparece la lista de espera',
    (_n, staff) => {
      const onEmpty = jest.fn()
      mockAvailability.mockReturnValue({
        isLoading: false,
        data: [slotDe('st-1', 'Ana', 'blocked'), slotDe('st-2', 'Bruno', 'booked')]
      })

      montarCon(staff, onEmpty)

      expect(screen.queryByText('09:00')).not.toBeInTheDocument()
      expect(screen.queryByText('Bloqueado')).not.toBeInTheDocument()
      expect(screen.queryByText('Ocupado')).not.toBeInTheDocument()
      expect(screen.getByText('No hay turnos disponibles.')).toBeInTheDocument()
      expect(screen.getByRole('button', { name: /Avisame si se libera/ })).toBeInTheDocument()
      expect(onEmpty).toHaveBeenCalledTimes(1)
    }
  )

  it('con "Cualquiera" un horario libre sigue con el nombre del profesional y los tomados no aparecen', () => {
    const onEmpty = jest.fn()
    mockAvailability.mockReturnValue({
      isLoading: false,
      data: [slotDe('st-1', 'Ana', 'blocked'), slotDe('st-2', 'Bruno', 'available')]
    })

    montarCon(null, onEmpty)

    expect(screen.getByRole('button', { name: /09:00/ })).not.toBeDisabled()
    expect(screen.getByText('Bruno')).toBeInTheDocument()
    expect(screen.queryByText('Ana')).not.toBeInTheDocument()
    expect(onEmpty).not.toHaveBeenCalled()
  })

  it('con recursos (cancha, sala) no habla de "profesional"', () => {
    mockAvailability.mockReturnValue({ isLoading: false, data: [] })
    const cancha = (n: number) => ({
      public_id: `cancha-${n}`,
      kind: 'resource',
      first_name: '',
      last_name: '',
      display_name: `Cancha ${n}`,
      service_ids: ['svc-1']
    })
    mockStaff.mockReturnValue({ isLoading: false, data: [cancha(1), cancha(2)] })

    render(
      <BookingStepDateTime
        storePublicId="store-1"
        serviceId="svc-1"
        staffId={null}
        selectedDate={null}
        selectedTime={null}
        onSelect={() => undefined}
        onBack={() => undefined}
      />
    )

    expect(screen.getByText('Cancha / sala')).toBeInTheDocument()
    expect(screen.getByText('Cancha 1')).toBeInTheDocument()
    expect(
      screen.getByText('Te mostramos horarios en cualquier cancha o sala disponible.')
    ).toBeInTheDocument()
    expect(screen.queryByText(/profesional/i)).not.toBeInTheDocument()
  })

  // 2026-10-16 (pedido de Mateo): con un solo profesional para el servicio se
  // ofrecia "Cualquiera" y ese profesional, dos opciones que eran lo mismo.
  describe('con un solo profesional para el servicio', () => {
    const SUBTITULO_UNICO = 'Elegí el día y el horario que te quede mejor.'
    const ana = { public_id: 'st-1', kind: 'person', display_name: 'Ana', service_ids: ['svc-1'] }
    const bruno = {
      public_id: 'st-2',
      kind: 'person',
      display_name: 'Bruno',
      service_ids: ['svc-1']
    }
    const libreDe = (staff_id: string, staff_name: string, starts_at: string) => ({
      staff_id,
      staff_name,
      starts_at,
      ends_at: starts_at,
      status: 'available',
      reason: null
    })

    it('no ofrece "Cualquiera", nombra al profesional y la reserva viaja con el', () => {
      mockStaff.mockReturnValue({ isLoading: false, data: [ana] })
      mockAvailability.mockReturnValue({
        isLoading: false,
        data: [libreDe('st-1', 'Ana', '2026-09-15T12:00:00+00:00')]
      })
      const onSelect = jest.fn()

      montarConSelect(null, onSelect)

      expect(screen.queryByRole('button', { name: /Cualquiera/ })).not.toBeInTheDocument()
      expect(screen.queryByRole('button', { name: /Ana/ })).not.toBeInTheDocument()
      expect(screen.getByText('Profesional')).toBeInTheDocument()
      expect(screen.getByText('Ana')).toBeInTheDocument()
      expect(screen.getByText(SUBTITULO_UNICO)).toBeInTheDocument()
      expect(
        screen.queryByText('Te mostramos horarios con cualquier profesional disponible.')
      ).not.toBeInTheDocument()

      // El horario no repite el nombre: ya esta arriba.
      const horario = screen.getByRole('button', { name: '09:00' })
      fireEvent.click(horario)

      expect(onSelect).toHaveBeenCalledTimes(1)
      const [, hora, asignado, pedido, startsAt, quien] = onSelect.mock.calls[0] as unknown[]
      expect(hora).toBe('09:00')
      expect(asignado).toBe('st-1')
      expect(pedido).toBe('st-1')
      expect(startsAt).toBe('2026-09-15T12:00:00+00:00')
      expect(quien).toEqual({ name: 'Ana', isResource: false })
    })

    it('una sola cancha o sala tampoco ofrece "Cualquiera" ni habla de "profesional"', () => {
      mockStaff.mockReturnValue({
        isLoading: false,
        data: [{ ...ana, public_id: 'cancha-1', kind: 'resource', display_name: 'Cancha 1' }]
      })
      mockAvailability.mockReturnValue({ isLoading: false, data: [] })

      montarConSelect(null, jest.fn())

      expect(screen.queryByRole('button', { name: /Cualquiera/ })).not.toBeInTheDocument()
      expect(screen.getByText('Cancha / sala')).toBeInTheDocument()
      expect(screen.getByText('Cancha 1')).toBeInTheDocument()
      expect(screen.getByText(SUBTITULO_UNICO)).toBeInTheDocument()
      expect(screen.queryByText(/profesional/i)).not.toBeInTheDocument()
    })

    it('con varios profesionales sigue el selector con "Cualquiera" y el pedido va sin profesional', () => {
      mockStaff.mockReturnValue({ isLoading: false, data: [ana, bruno] })
      mockAvailability.mockReturnValue({
        isLoading: false,
        data: [libreDe('st-2', 'Bruno', '2026-09-15T12:00:00+00:00')]
      })
      const onSelect = jest.fn()

      montarConSelect(null, onSelect)

      expect(screen.getByRole('button', { name: /Cualquiera/ })).toBeInTheDocument()
      expect(screen.getByRole('button', { name: 'Ana' })).toBeInTheDocument()
      expect(screen.getByRole('button', { name: 'Bruno' })).toBeInTheDocument()
      expect(
        screen.getByText('Te mostramos horarios con cualquier profesional disponible.')
      ).toBeInTheDocument()
      expect(screen.queryByText(SUBTITULO_UNICO)).not.toBeInTheDocument()

      fireEvent.click(screen.getByRole('button', { name: /09:00/ }))

      const [, , asignado, pedido] = onSelect.mock.calls[0] as unknown[]
      expect(asignado).toBe('st-2')
      expect(pedido).toBeNull()
    })
  })

  // 2026-10-16 (pedido de Mateo): "atras" era un circulo naranja con un chevron
  // y los clientes no lo veian.
  it('"Volver" es un boton con texto visible que vuelve al paso anterior', () => {
    mockAvailability.mockReturnValue({ isLoading: false, data: [] })
    const onBack = jest.fn()

    render(
      <BookingStepDateTime
        storePublicId="store-1"
        serviceId="svc-1"
        staffId={null}
        selectedDate={null}
        selectedTime={null}
        onSelect={() => undefined}
        onBack={onBack}
      />
    )

    const volver = screen.getByRole('button', { name: 'Volver' })
    expect(volver).toHaveTextContent('Volver')
    expect(volver).toHaveAttribute('type', 'button')
    fireEvent.click(volver)
    expect(onBack).toHaveBeenCalledTimes(1)
  })

  it('"Ver todos" es un interruptor alcanzable y operable por teclado', () => {
    // F11a-09 (2026-09-24): era un div con onClick dentro de un label sin
    // control: Tab no llegaba y Enter/Espacio no hacian nada. Un <button> nativo
    // recibe foco y el navegador lo activa con Enter/Espacio (jsdom no simula
    // esa activacion, asi que se verifica el elemento y su efecto).
    mockAvailability.mockReturnValue({ isLoading: false, data: [] })

    render(
      <BookingStepDateTime
        storePublicId="store-1"
        serviceId="svc-1"
        staffId={null}
        selectedDate="2026-09-25"
        selectedTime={null}
        onSelect={() => undefined}
        onBack={() => undefined}
      />
    )

    const interruptor = screen.getByRole('switch', { name: /ver todos/i })
    expect(interruptor.tagName).toBe('BUTTON')
    expect(interruptor).toHaveAttribute('type', 'button')
    expect(interruptor).toHaveAttribute('aria-checked', 'false')

    interruptor.focus()
    expect(interruptor).toHaveFocus()

    fireEvent.click(interruptor)

    expect(interruptor).toHaveAttribute('aria-checked', 'true')
    expect(mockAvailability).toHaveBeenLastCalledWith('store-1', 'svc-1', '2026-09-25', true, [])
  })

  it('indica el desplazamiento de fechas y adapta los horarios a dos columnas angostas', () => {
    mockAvailability.mockReturnValue({
      isLoading: false,
      data: [
        {
          staff_id: 'st-1',
          staff_name: 'Ana',
          starts_at: '2026-09-15T12:00:00+00:00',
          ends_at: '2026-09-15T12:30:00+00:00',
          status: 'available',
          reason: null
        }
      ]
    })

    render(
      <BookingStepDateTime
        storePublicId="store-1"
        serviceId="svc-1"
        staffId="st-1"
        selectedDate={null}
        selectedTime={null}
        onSelect={() => undefined}
        onBack={() => undefined}
      />
    )

    expect(
      screen.getByRole('group', { name: /fechas disponibles.*deslizá horizontalmente/i })
    ).toBeInTheDocument()
    expect(screen.getByText('Deslizá para ver más')).not.toHaveClass('sm:hidden')

    const timeButton = screen.getByRole('button', { name: /09:00/ })
    expect(timeButton).toHaveClass('min-h-11')
    expect(timeButton.parentElement).toHaveClass(
      'grid-cols-2',
      'min-[380px]:grid-cols-3',
      'sm:grid-cols-4'
    )
  })

  it('usa texto secundario AA y objetivos tactiles para el selector de profesional', () => {
    mockAvailability.mockReturnValue({ isLoading: false, data: [] })
    mockStaff.mockReturnValue({
      isLoading: false,
      data: [
        {
          public_id: 'st-1',
          kind: 'person',
          first_name: 'Ana',
          last_name: '',
          display_name: 'Ana',
          service_ids: ['svc-1']
        },
        {
          public_id: 'st-2',
          kind: 'person',
          first_name: 'Sol',
          last_name: '',
          display_name: 'Sol',
          service_ids: ['svc-1']
        }
      ]
    })

    render(
      <BookingStepDateTime
        storePublicId="store-1"
        serviceId="svc-1"
        staffId={null}
        selectedDate={null}
        selectedTime={null}
        onSelect={() => undefined}
        onBack={() => undefined}
      />
    )

    expect(screen.getByText('Profesional').parentElement?.style.color).toBe(
      asRgb(colors2000s.text.secondary)
    )
    expect(screen.getByText('Deslizá para ver más opciones.')).not.toHaveClass('sm:hidden')
    expect(screen.getByText('Deslizá para ver más opciones.').style.color).toBe(
      asRgb(colors2000s.text.secondary)
    )
    for (const name of [/Cualquiera/, /Ana/, /Sol/]) {
      expect(screen.getByRole('button', { name })).toHaveClass('min-h-11', 'min-w-11')
    }
  })

  it('usa texto secundario AA en el estado vacío sobre superficie blanca', () => {
    mockAvailability.mockReturnValue({ isLoading: false, data: [] })
    mockStaff.mockReturnValue({
      isLoading: false,
      data: [
        {
          public_id: 'st-1',
          kind: 'person',
          first_name: 'Ana',
          last_name: '',
          display_name: 'Ana',
          service_ids: ['svc-1']
        },
        {
          public_id: 'st-2',
          kind: 'person',
          first_name: 'Sol',
          last_name: '',
          display_name: 'Sol',
          service_ids: ['svc-1']
        }
      ]
    })

    render(
      <BookingStepDateTime
        storePublicId="store-1"
        serviceId="svc-1"
        staffId={null}
        selectedDate={null}
        selectedTime={null}
        showWaitlist={false}
        onSelect={() => undefined}
        onBack={() => undefined}
      />
    )

    expect(screen.getByText('Este día no hay atención.').style.color).toBe(
      asRgb(colors2000s.text.secondary)
    )
    expect(screen.getByText('Probá con otro día.').style.color).toBe(
      asRgb(colors2000s.text.secondary)
    )
  })

  it('mantiene los horarios en caché ante un error de actualización y permite reintentar', () => {
    const refetch = jest.fn()
    mockAvailability.mockReturnValue({
      isLoading: false,
      isError: true,
      isFetching: false,
      refetch,
      data: [
        {
          staff_id: 'st-1',
          staff_name: 'Ana',
          starts_at: '2026-09-15T12:00:00+00:00',
          ends_at: '2026-09-15T12:30:00+00:00',
          status: 'available',
          reason: null
        }
      ]
    })

    render(
      <BookingStepDateTime
        storePublicId="store-1"
        serviceId="svc-1"
        staffId="st-1"
        selectedDate={null}
        selectedTime={null}
        onSelect={() => undefined}
        onBack={() => undefined}
      />
    )

    expect(screen.getByRole('status')).toHaveTextContent(
      'La información visible puede estar desactualizada.'
    )
    expect(screen.getByRole('button', { name: /09:00/ })).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Reintentar' }))

    expect(refetch).toHaveBeenCalledTimes(1)
  })

  it('una fecha lejana que vino por deep-link aparece en la tira y carga sus horarios', () => {
    // La tira muestra 14 dias: el ?date= de un link de reoferta a 45 dias
    // cargaba sus horarios pero el dia no se veia seleccionado en ningun lado.
    mockAvailability.mockReturnValue({ isLoading: false, data: [] })
    const lejana = new Date()
    lejana.setDate(lejana.getDate() + 45)
    const lejanaStr = format(lejana, 'yyyy-MM-dd')

    render(
      <BookingStepDateTime
        storePublicId="store-1"
        serviceId="svc-1"
        staffId={null}
        selectedDate={lejanaStr}
        selectedTime={null}
        onSelect={() => undefined}
        onBack={() => undefined}
      />
    )

    expect(screen.getByTestId(`date-${lejanaStr}`)).toBeInTheDocument()
    expect(mockAvailability).toHaveBeenCalledWith('store-1', 'svc-1', lejanaStr, false, [])
  })

  describe('reprogramar desde "Mis turnos" (FF-06)', () => {
    // FF-06 (2026-10-01): "Mis turnos" reprogramaba con inputs libres de fecha
    // y hora y recomponia el instante; un horario fuera de la grilla terminaba
    // en 409 o 400. Reusa esta grilla con el profesional del turno fijo
    // (el backend reprograma siempre con el mismo, D-20260930-06).
    const AVISAME = /Avisame si se libera/
    const slots = [
      {
        staff_id: 'st-1',
        staff_name: 'Ana',
        starts_at: '2026-09-15T13:00:00+00:00',
        ends_at: '2026-09-15T13:30:00+00:00',
        status: 'booked',
        reason: null
      },
      {
        staff_id: 'st-2',
        staff_name: 'Bruno',
        starts_at: '2026-09-15T13:00:00+00:00',
        ends_at: '2026-09-15T13:30:00+00:00',
        status: 'available',
        reason: null
      }
    ]

    it('con lockedStaffId no muestra el selector y solo ofrece los horarios de ese profesional', () => {
      mockAvailability.mockReturnValue({ isLoading: false, data: slots })
      mockStaff.mockReturnValue({
        isLoading: false,
        data: [
          { public_id: 'st-1', kind: 'person', display_name: 'Ana', service_ids: ['svc-1'] },
          { public_id: 'st-2', kind: 'person', display_name: 'Bruno', service_ids: ['svc-1'] }
        ]
      })

      render(
        <BookingStepDateTime
          storePublicId="store-1"
          serviceId="svc-1"
          staffId={null}
          lockedStaffId="st-1"
          selectedDate={null}
          selectedTime={null}
          heading="Elegí el nuevo horario"
          onSelect={() => undefined}
          onBack={() => undefined}
        />
      )

      expect(screen.getByRole('heading', { name: 'Elegí el nuevo horario' })).toBeInTheDocument()
      expect(screen.queryByText('Profesional')).not.toBeInTheDocument()
      expect(screen.queryByRole('button', { name: /Cualquiera/ })).not.toBeInTheDocument()
      expect(screen.queryByRole('button', { name: /Bruno/ })).not.toBeInTheDocument()
      // El horario de Ana esta tomado y no se muestra; el de Bruno, libre, tampoco se ofrece.
      expect(screen.queryByRole('button', { name: /10:00/ })).not.toBeInTheDocument()
      expect(screen.getByText('No hay turnos disponibles.')).toBeInTheDocument()
      expect(screen.queryByText('booked')).not.toBeInTheDocument()
    })

    it('sin showWaitlist la lista de espera sigue apareciendo con el dia lleno', () => {
      mockAvailability.mockReturnValue({
        isLoading: false,
        data: [{ ...slots[0], staff_id: 'st-1' }]
      })

      render(
        <BookingStepDateTime
          storePublicId="store-1"
          serviceId="svc-1"
          staffId={null}
          selectedDate={null}
          selectedTime={null}
          onSelect={() => undefined}
          onBack={() => undefined}
        />
      )

      expect(screen.getByRole('button', { name: AVISAME })).toBeInTheDocument()
      expect(screen.getByRole('heading', { name: 'Elegí fecha y hora' })).toBeInTheDocument()
    })

    // 2026-10-14: un domingo sin horario ofrecia "Avisame si se libera un turno".
    it('un dia sin ningun horario es un dia sin atencion y no ofrece lista de espera', () => {
      mockAvailability.mockReturnValue({ isLoading: false, data: [] })

      render(
        <BookingStepDateTime
          storePublicId="store-1"
          serviceId="svc-1"
          staffId={null}
          selectedDate={null}
          selectedTime={null}
          onSelect={() => undefined}
          onBack={() => undefined}
        />
      )

      expect(screen.getByText('Este día no hay atención.')).toBeInTheDocument()
      expect(screen.getByText('Probá con otro día.')).toBeInTheDocument()
      expect(screen.queryByText('No hay turnos disponibles.')).not.toBeInTheDocument()
      expect(screen.queryByRole('button', { name: AVISAME })).not.toBeInTheDocument()
    })

    it('sin franjas de atencion no ofrece lista de espera aunque haya profesionales asignados', () => {
      mockAvailability.mockReturnValue({ isLoading: false, data: [] })
      mockStaff.mockReturnValue({
        isLoading: false,
        data: [
          { public_id: 'st-1', kind: 'person', display_name: 'Ana', service_ids: ['svc-1'] },
          { public_id: 'st-2', kind: 'person', display_name: 'Bruno', service_ids: ['svc-1'] }
        ]
      })

      montarCon(null)

      expect(screen.getByText('Este día no hay atención.')).toBeInTheDocument()
      expect(screen.queryByText('No hay turnos disponibles.')).not.toBeInTheDocument()
      expect(screen.queryByRole('button', { name: AVISAME })).not.toBeInTheDocument()
    })

    it('mantiene la carga mientras se resuelve la lista de profesionales', () => {
      mockAvailability.mockReturnValue({ isLoading: false, data: [] })
      mockStaff.mockReturnValue({ isLoading: true, data: undefined })

      montarCon(null)

      expect(screen.getByRole('status', { name: 'Cargando horarios' })).toBeInTheDocument()
      expect(screen.queryByText('Este día no hay atención.')).not.toBeInTheDocument()
      expect(screen.queryByText('No hay turnos disponibles.')).not.toBeInTheDocument()
      expect(screen.queryByRole('button', { name: AVISAME })).not.toBeInTheDocument()
    })

    it('si el profesional elegido no trabaja ese dia no hay atencion aunque otro tenga horarios', () => {
      mockAvailability.mockReturnValue({ isLoading: false, data: [slots[1]] })

      render(
        <BookingStepDateTime
          storePublicId="store-1"
          serviceId="svc-1"
          staffId={null}
          lockedStaffId="st-9"
          selectedDate={null}
          selectedTime={null}
          onSelect={() => undefined}
          onBack={() => undefined}
        />
      )

      expect(screen.getByText('Este día no hay atención.')).toBeInTheDocument()
      expect(screen.queryByRole('button', { name: AVISAME })).not.toBeInTheDocument()
    })

    it('con showWaitlist={false} no monta la lista de espera con el dia lleno', () => {
      mockAvailability.mockReturnValue({ isLoading: false, data: [slots[0]] })

      render(
        <BookingStepDateTime
          storePublicId="store-1"
          serviceId="svc-1"
          staffId={null}
          lockedStaffId="st-1"
          showWaitlist={false}
          selectedDate={null}
          selectedTime={null}
          onSelect={() => undefined}
          onBack={() => undefined}
        />
      )

      expect(screen.getByText('No hay turnos disponibles.')).toBeInTheDocument()
      expect(screen.queryByRole('button', { name: AVISAME })).not.toBeInTheDocument()
    })

    it('con showWaitlist={false} tampoco la monta con todos los horarios tomados', () => {
      mockAvailability.mockReturnValue({ isLoading: false, data: [slots[0]] })

      render(
        <BookingStepDateTime
          storePublicId="store-1"
          serviceId="svc-1"
          staffId={null}
          lockedStaffId="st-1"
          showWaitlist={false}
          selectedDate={null}
          selectedTime={null}
          onSelect={() => undefined}
          onBack={() => undefined}
        />
      )

      expect(screen.queryByRole('button', { name: /10:00/ })).not.toBeInTheDocument()
      expect(screen.getByText('No hay turnos disponibles.')).toBeInTheDocument()
      expect(screen.queryByRole('button', { name: AVISAME })).not.toBeInTheDocument()
    })
  })
})
