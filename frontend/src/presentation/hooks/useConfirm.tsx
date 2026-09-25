import React, { useState } from 'react'

import { ConfirmDialog } from '../components/organisms/ConfirmDialog'

interface PendingConfirm {
  message: string
  resolve: (confirmed: boolean) => void
}

/**
 * `await confirm(pregunta)` como window.confirm, pero con un dialogo propio.
 * Estado local, sin provider: la pantalla que lo usa renderiza `confirmDialog`.
 */
export const useConfirm = () => {
  const [pending, setPending] = useState<PendingConfirm | null>(null)

  const confirm = (message: string) =>
    new Promise<boolean>((resolve) => {
      setPending({ message, resolve })
    })

  const settle = (confirmed: boolean) => {
    pending?.resolve(confirmed)
    setPending(null)
  }

  const confirmDialog: React.ReactNode = pending ? (
    <ConfirmDialog
      message={pending.message}
      onConfirm={() => settle(true)}
      onCancel={() => settle(false)}
    />
  ) : null

  return { confirm, confirmDialog }
}
