import React from 'react'

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import { act, renderHook, waitFor } from '@testing-library/react'

import { useManagedStaff, useReplaceStaffSchedules } from './useManagedStaff'

const mockListStaff = jest.fn()
const mockReplaceWeek = jest.fn()

jest.mock('@application/services/StaffService', () => ({
  staffService: { listStaff: () => mockListStaff() }
}))

jest.mock('@application/services/StaffSchedulesService', () => ({
  staffSchedulesService: {
    replaceWeek: (...args: unknown[]) => mockReplaceWeek(...args)
  }
}))

const envoltorio = ({ children }: { children: React.ReactNode }) => {
  const queryClient = new QueryClient({
    defaultOptions: { mutations: { retry: false }, queries: { retry: false } }
  })
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
}

// 2026-10-08: la agenda del panel dibuja el horario de cada profesional con
// las franjas de ['staff']; guardar la semana tiene que refrescar esa lista.
describe('useReplaceStaffSchedules', () => {
  beforeEach(() => {
    mockListStaff.mockReset()
    mockReplaceWeek.mockReset()
  })

  it('guarda la semana del profesional y refresca la lista del personal', async () => {
    mockListStaff.mockResolvedValue([])
    mockReplaceWeek.mockResolvedValue([])
    const semana = [{ dayOfWeek: 2, startTime: '10:00:00', endTime: '14:00:00' }]

    const { result } = renderHook(
      () => ({ lista: useManagedStaff(), guardar: useReplaceStaffSchedules() }),
      { wrapper: envoltorio }
    )
    await waitFor(() => expect(result.current.lista.isSuccess).toBe(true))
    expect(mockListStaff).toHaveBeenCalledTimes(1)

    await act(() => result.current.guardar.mutateAsync({ staffId: 'st-9', schedules: semana }))

    expect(mockReplaceWeek).toHaveBeenCalledWith('st-9', semana)
    await waitFor(() => expect(mockListStaff).toHaveBeenCalledTimes(2))
  })

  it('si el backend rechaza, no refresca y el error llega al que llamo', async () => {
    mockListStaff.mockResolvedValue([])
    const rechazo = new Error('SCHEDULE_OVERLAP')
    mockReplaceWeek.mockRejectedValue(rechazo)

    const { result } = renderHook(
      () => ({ lista: useManagedStaff(), guardar: useReplaceStaffSchedules() }),
      { wrapper: envoltorio }
    )
    await waitFor(() => expect(result.current.lista.isSuccess).toBe(true))

    await act(async () => {
      await expect(
        result.current.guardar.mutateAsync({ staffId: 'st-9', schedules: [] })
      ).rejects.toBe(rechazo)
    })
    expect(mockListStaff).toHaveBeenCalledTimes(1)
  })
})
