import { renderHook } from '@testing-library/react'

import type { StoreSubscriptionStatus } from '@application/services/StoreSettingsService'

import { ERROR_CODE_MESSAGES } from '@shared/errors/errorCodes'

import { useStoreWriteAccess } from './useStoreWriteAccess'

let mockUser: { is_global_admin?: boolean } | null = null
let mockSubscription: StoreSubscriptionStatus | undefined

jest.mock('../context/AuthContext', () => ({
  useAuth: () => ({ user: mockUser })
}))

jest.mock('./useStores', () => ({
  useStoreSubscription: () => ({ data: mockSubscription })
}))

const plan = (
  status: StoreSubscriptionStatus['status'],
  blocksWrites: boolean
): StoreSubscriptionStatus => ({
  status,
  plan_name: 'Basico',
  current_period_end: null,
  days_left: null,
  grace_until: null,
  warn: status !== 'active',
  blocks_writes: blocksWrites
})

// 2026-10-01: con la tienda suspendida cada accion fallaba con 402 en vez de
// verse deshabilitada (FF-15, D-20260930-10).
describe('useStoreWriteAccess', () => {
  beforeEach(() => {
    mockUser = { is_global_admin: false }
    mockSubscription = undefined
  })

  it('una tienda suspendida queda en solo lectura con el texto de SUBSCRIPTION_SUSPENDED', () => {
    mockSubscription = plan('suspended', true)
    const { result } = renderHook(() => useStoreWriteAccess())
    expect(result.current.readOnly).toBe(true)
    expect(result.current.reason).toBe(ERROR_CODE_MESSAGES.get('SUBSCRIPTION_SUSPENDED'))
  })

  it('past_due no bloquea: el backend solo corta con la suspension', () => {
    mockSubscription = plan('past_due', false)
    const { result } = renderHook(() => useStoreWriteAccess())
    expect(result.current.readOnly).toBe(false)
  })

  it('el superadmin nunca queda en solo lectura', () => {
    mockUser = { is_global_admin: true }
    mockSubscription = plan('suspended', true)
    const { result } = renderHook(() => useStoreWriteAccess())
    expect(result.current.readOnly).toBe(false)
  })

  it('sin datos del plan todavia no bloquea: el 402 sigue de red', () => {
    const { result } = renderHook(() => useStoreWriteAccess())
    expect(result.current.readOnly).toBe(false)
  })
})
