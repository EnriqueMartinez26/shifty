import { render } from '@testing-library/react'

import { BookingStepDateTime } from './BookingStepDateTime'

const mockAvailability = jest.fn()
jest.mock('@presentation/hooks/usePublic', () => ({
  usePublicStaff: () => ({ data: [], isLoading: false }),
  usePublicAvailability: () => mockAvailability()
}))
jest.mock('./WaitlistJoinForm', () => ({ WaitlistJoinForm: () => null }))

const props = {
  storePublicId: 'store',
  serviceId: 'service',
  staffId: null,
  selectedDate: null,
  selectedTime: null,
  onSelect: jest.fn(),
  onBack: jest.fn()
}

it('un resultado vacio se mide una vez aunque cambie el callback al renderizar', () => {
  mockAvailability.mockReturnValue({
    data: [],
    isLoading: false,
    isFetching: false,
    isError: false
  })
  const first = jest.fn()
  const view = render(<BookingStepDateTime {...props} onEmptyAvailability={first} />)
  expect(first).toHaveBeenCalledTimes(1)
  const next = jest.fn()
  view.rerender(<BookingStepDateTime {...props} onEmptyAvailability={next} />)
  expect(next).not.toHaveBeenCalled()
})

it.each([
  { data: undefined, isLoading: false },
  { data: [], isLoading: true },
  { data: [], isFetching: true },
  { data: [], isError: true },
  { data: [{ staff_id: 'staff', starts_at: '2026-10-08T12:00:00Z', status: 'available' }] }
])('no confunde carga, error o cupos disponibles con agenda vacia: %j', (state) => {
  mockAvailability.mockReturnValue(state)
  const onEmpty = jest.fn()
  render(<BookingStepDateTime {...props} onEmptyAvailability={onEmpty} />)
  expect(onEmpty).not.toHaveBeenCalled()
})
