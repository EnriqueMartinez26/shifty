import { act, renderHook } from '@testing-library/react'

import { useResendCooldown } from './useResendCooldown'

describe('useResendCooldown', () => {
  // 2026-09-30, F4-11: sin espera para reenviar, cada toque de "enviar"
  // mientras el mail tardaba gastaba uno de los 5 codigos por hora del
  // telefono y el cliente quedaba bloqueado una hora.
  beforeEach(() => jest.useFakeTimers())
  afterEach(() => jest.useRealTimers())

  const PHONE = '5491155550101'

  it('start() espera 60 s y despues libera', () => {
    const { result } = renderHook(() => useResendCooldown(PHONE))
    expect(result.current.secondsLeft).toBe(0)

    act(() => {
      result.current.start()
    })
    expect(result.current.secondsLeft).toBe(60)

    act(() => {
      jest.advanceTimersByTime(59_000)
    })
    expect(result.current.secondsLeft).toBe(1)

    act(() => {
      jest.advanceTimersByTime(1_000)
    })
    expect(result.current.secondsLeft).toBe(0)
  })

  it('start(20) espera lo que pide el servidor', () => {
    // 2026-09-30, F4-11: un 429 con Retry-After se ignoraba y el boton quedaba
    // habilitado para volver a chocar contra el limite.
    const { result } = renderHook(() => useResendCooldown(PHONE))

    act(() => {
      result.current.start(20)
    })
    expect(result.current.secondsLeft).toBe(20)

    act(() => {
      jest.advanceTimersByTime(20_000)
    })
    expect(result.current.secondsLeft).toBe(0)
  })

  it('con otro telefono no hay espera, y volver al pedido la retoma', () => {
    // 2026-09-30, F4-11: la espera es de un telefono; corregir un numero mal
    // tipeado no tiene por que esperar el minuto del anterior.
    const { result, rerender } = renderHook(({ phone }) => useResendCooldown(phone), {
      initialProps: { phone: PHONE }
    })
    act(() => {
      result.current.start()
    })
    expect(result.current.secondsLeft).toBe(60)

    rerender({ phone: '5491155550202' })
    expect(result.current.secondsLeft).toBe(0)

    act(() => {
      jest.advanceTimersByTime(10_000)
    })
    rerender({ phone: PHONE })
    expect(result.current.secondsLeft).toBe(50)
  })

  it('start con una clave explicita espera solo para esa clave', () => {
    const { result } = renderHook(() => useResendCooldown(PHONE))

    act(() => {
      result.current.start(30, '5491155550202')
    })

    expect(result.current.secondsLeft).toBe(0)
  })

  it('al desmontar limpia el intervalo', () => {
    const setIntervalSpy = jest.spyOn(window, 'setInterval')
    const clearIntervalSpy = jest.spyOn(window, 'clearInterval')
    try {
      const { result, unmount } = renderHook(() => useResendCooldown(PHONE))
      act(() => {
        result.current.start()
      })
      expect(setIntervalSpy).toHaveBeenCalledTimes(1)
      const intervalId = setIntervalSpy.mock.results[0]?.value

      unmount()

      expect(clearIntervalSpy).toHaveBeenCalledWith(intervalId)
    } finally {
      setIntervalSpy.mockRestore()
      clearIntervalSpy.mockRestore()
    }
  })
})
