import React, { useEffect, useId, useRef } from 'react'

import { Loader2, X } from 'lucide-react'

import { buttonStyles2000s, colors2000s } from '../../../theme/colors'
import { create2000sModalSurfaceStyle } from '../../lib/surfaceStyles'
import { superAdminPrimaryControlStyle } from '../../pages/superadmin/palette'
import { FormErrorAlert } from '../molecules/FormErrorAlert'

interface SuperAdminFormModalProps {
  isOpen: boolean
  onClose: () => void
  onSubmit: (event: React.FormEvent<HTMLFormElement>) => void | Promise<void>
  title: string
  subtitle: string
  submitLabel: string
  cancelLabel?: string
  error?: string | null
  loading?: boolean
  submitDisabled?: boolean
  children: React.ReactNode
}

const FOCUSABLE_SELECTOR =
  'a[href], button:not([disabled]), input:not([type="hidden"]):not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"]), [contenteditable="true"]'

const getFocusableElements = (dialog: HTMLElement): HTMLElement[] =>
  Array.from(dialog.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR)).filter(
    (element) =>
      element.tabIndex >= 0 &&
      !element.matches(':disabled') &&
      !element.closest('[hidden], [aria-hidden="true"], [inert]')
  )

export const SuperAdminFormModal: React.FC<SuperAdminFormModalProps> = ({
  isOpen,
  onClose,
  onSubmit,
  title,
  subtitle,
  submitLabel,
  cancelLabel = 'Cancelar',
  error,
  loading = false,
  submitDisabled = false,
  children
}) => {
  const titleId = useId()
  const subtitleId = useId()
  const dialogRef = useRef<HTMLDivElement>(null)
  const onCloseRef = useRef(onClose)

  useEffect(() => {
    onCloseRef.current = onClose
  }, [onClose])

  useEffect(() => {
    if (!isOpen) return

    const previouslyFocusedElement =
      document.activeElement instanceof HTMLElement ? document.activeElement : null
    const dialog = dialogRef.current

    if (dialog) {
      const focusableElements = getFocusableElements(dialog)
      const form = dialog.querySelector('form')
      const firstFormControl = focusableElements.find(
        (element) => form?.contains(element) && !element.matches('button[type="submit"]')
      )
      ;(firstFormControl ?? focusableElements[0] ?? dialog).focus()
    }

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault()
        onCloseRef.current()
        return
      }

      if (event.key !== 'Tab' || !dialog) return

      const focusableElements = getFocusableElements(dialog)
      if (!focusableElements.length) {
        event.preventDefault()
        dialog.focus()
        return
      }

      const first = focusableElements[0]
      const last = focusableElements[focusableElements.length - 1]
      if (!first || !last) {
        event.preventDefault()
        dialog.focus()
        return
      }
      const activeElement = document.activeElement

      if (
        event.shiftKey &&
        (activeElement === first || activeElement === dialog || !dialog.contains(activeElement))
      ) {
        event.preventDefault()
        last.focus()
      } else if (
        !event.shiftKey &&
        (activeElement === last || activeElement === dialog || !dialog.contains(activeElement))
      ) {
        event.preventDefault()
        first.focus()
      }
    }

    document.addEventListener('keydown', handleKeyDown)
    return () => {
      document.removeEventListener('keydown', handleKeyDown)
      if (previouslyFocusedElement?.isConnected) previouslyFocusedElement.focus()
    }
  }, [isOpen])

  if (!isOpen) return null

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center p-4">
      <div
        aria-hidden="true"
        className="absolute inset-0 bg-black/50 backdrop-blur-sm"
        onClick={onClose}
      />

      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={subtitleId}
        tabIndex={-1}
        className="relative w-full max-w-3xl overflow-y-auto rounded-[2.5rem] border p-8 max-h-[92dvh]"
        style={create2000sModalSurfaceStyle()}
      >
        <div className="mb-8 flex items-start justify-between gap-4">
          <div>
            <h3
              id={titleId}
              className="text-2xl font-black uppercase tracking-tight"
              style={{ color: colors2000s.text.primary }}
            >
              {title}
            </h3>
            <p
              id={subtitleId}
              className="mt-1 text-xs font-bold"
              style={{ color: colors2000s.text.secondary }}
            >
              {subtitle}
            </p>
          </div>

          <button
            type="button"
            aria-label="Cerrar ventana"
            onClick={onClose}
            className="flex h-11 w-11 items-center justify-center"
            style={buttonStyles2000s.default}
          >
            <X size={18} />
          </button>
        </div>

        <form
          onSubmit={(event) => {
            void onSubmit(event)
          }}
          className="space-y-6"
        >
          <FormErrorAlert message={error} />

          {children}

          <div className="flex flex-col gap-3 pt-2 sm:flex-row">
            <button
              type="button"
              onClick={onClose}
              className="px-6 py-4 text-xs font-black uppercase tracking-widest"
              style={buttonStyles2000s.default}
            >
              {cancelLabel}
            </button>

            <button
              type="submit"
              disabled={loading || submitDisabled}
              className="flex-1 rounded-2xl px-6 py-4 text-xs font-black uppercase tracking-widest disabled:opacity-50"
              style={superAdminPrimaryControlStyle}
            >
              {loading ? <Loader2 className="mx-auto h-5 w-5 animate-spin" /> : submitLabel}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
