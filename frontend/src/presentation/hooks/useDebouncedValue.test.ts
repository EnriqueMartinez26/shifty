import { act, renderHook } from '@testing-library/react'

import { useDebouncedValue } from './useDebouncedValue'

describe('useDebouncedValue', () => {
  // 2026-09-30, F4-06: la vista previa de la seña hacia una request por tecla
  // del telefono; el valor tiene que esperar a que se deje de tipear.
  beforeEach(() => jest.useFakeTimers())
  afterEach(() => jest.useRealTimers())

  it('el valor inicial pasa sin espera', () => {
    const { result } = renderHook(() => useDebouncedValue('1155550101', 400))

    expect(result.current).toBe('1155550101')
  })

  it('un cambio aparece recien despues de la espera', () => {
    const { result, rerender } = renderHook(({ value }) => useDebouncedValue(value, 400), {
      initialProps: { value: 'a' }
    })

    rerender({ value: 'b' })
    expect(result.current).toBe('a')

    act(() => {
      jest.advanceTimersByTime(399)
    })
    expect(result.current).toBe('a')

    act(() => {
      jest.advanceTimersByTime(1)
    })
    expect(result.current).toBe('b')
  })

  it('cambios seguidos reinician la espera y solo llega el ultimo', () => {
    const { result, rerender } = renderHook(({ value }) => useDebouncedValue(value, 400), {
      initialProps: { value: '' }
    })

    rerender({ value: '1' })
    act(() => {
      jest.advanceTimersByTime(300)
    })
    rerender({ value: '12' })
    act(() => {
      jest.advanceTimersByTime(300)
    })
    rerender({ value: '123' })
    act(() => {
      jest.advanceTimersByTime(300)
    })
    expect(result.current).toBe('')

    act(() => {
      jest.advanceTimersByTime(100)
    })
    expect(result.current).toBe('123')
  })

  it('al desmontar limpia el temporizador', () => {
    const setTimeoutSpy = jest.spyOn(window, 'setTimeout')
    const clearTimeoutSpy = jest.spyOn(window, 'clearTimeout')
    try {
      const { rerender, unmount } = renderHook(({ value }) => useDebouncedValue(value, 400), {
        initialProps: { value: 'a' }
      })
      rerender({ value: 'b' })
      const callIndex = setTimeoutSpy.mock.calls.findIndex(([, delay]) => delay === 400)
      expect(callIndex).toBeGreaterThanOrEqual(0)
      const timeoutId = setTimeoutSpy.mock.results[callIndex]?.value

      unmount()

      expect(clearTimeoutSpy).toHaveBeenCalledWith(timeoutId)
    } finally {
      setTimeoutSpy.mockRestore()
      clearTimeoutSpy.mockRestore()
    }
  })
})
