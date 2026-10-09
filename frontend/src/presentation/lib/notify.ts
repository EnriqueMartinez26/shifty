import { toast } from 'sonner'

import type { ToastKind } from '@infrastructure/setup/SpecificHandlers'

import { getErrorMessage } from '@shared/errors/getErrorMessage'

/**
 * Unico punto que habla con sonner (D-20260928-07). main.tsx lo conecta al
 * puerto de los handlers globales y monta el <Toaster />, que expone la
 * region aria-live.
 */
export const showToast = (message: string, kind: ToastKind): void => {
  toast[kind](message)
}

/** Aviso de una accion que fallo, con el texto neutro de getErrorMessage (regla 20). */
export const notifyError = (error: unknown, fallback: string): void => {
  showToast(getErrorMessage(error, fallback), 'error')
}
