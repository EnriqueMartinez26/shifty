import React, { useEffect, useId, useRef } from 'react'

interface ConfirmDialogProps {
  /** La pregunta, tal cual la mostraba window.confirm. */
  message: string
  onConfirm: () => void
  onCancel: () => void
}

/**
 * Reemplazo accesible de window.confirm: dialogo modal con la pregunta como
 * nombre, foco inicial en "Cancelar" (la opcion que no destruye nada), Escape
 * cancela, Tab no se escapa del dialogo y al cerrarse el foco vuelve a donde
 * estaba.
 */
export const ConfirmDialog: React.FC<ConfirmDialogProps> = ({ message, onConfirm, onCancel }) => {
  const titleId = useId()
  const cancelRef = useRef<HTMLButtonElement>(null)
  const confirmRef = useRef<HTMLButtonElement>(null)

  // Sincroniza con el DOM: mover el foco al abrir y devolverlo al cerrar.
  useEffect(() => {
    const previous = document.activeElement
    cancelRef.current?.focus()
    return () => {
      if (previous instanceof HTMLElement) previous.focus()
    }
  }, [])

  const handleKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === 'Escape') {
      event.preventDefault()
      onCancel()
      return
    }
    if (event.key !== 'Tab') return
    // Con dos botones el ciclo es cerrado: el siguiente del ultimo es el primero.
    event.preventDefault()
    const next = document.activeElement === cancelRef.current ? confirmRef : cancelRef
    next.current?.focus()
  }

  return (
    <div
      role="alertdialog"
      aria-modal="true"
      aria-labelledby={titleId}
      onKeyDown={handleKeyDown}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
    >
      <div className="w-full max-w-md rounded-3xl bg-white p-6 shadow-2xl space-y-6">
        <p id={titleId} className="text-sm font-bold text-gray-700">
          {message}
        </p>
        <div className="flex justify-end gap-3">
          <button
            ref={cancelRef}
            type="button"
            onClick={onCancel}
            className="rounded-xl border border-gray-200 bg-white px-4 py-2 text-xs font-black uppercase tracking-widest text-gray-600"
          >
            Cancelar
          </button>
          <button
            ref={confirmRef}
            type="button"
            onClick={onConfirm}
            className="rounded-xl bg-orange-600 px-4 py-2 text-xs font-black uppercase tracking-widest text-white"
          >
            Confirmar
          </button>
        </div>
      </div>
    </div>
  )
}
