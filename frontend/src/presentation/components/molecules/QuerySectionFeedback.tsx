import React from 'react'

import { Loader2 } from 'lucide-react'

import { colors2000s } from '../../../theme/colors'

interface QuerySectionFeedbackProps {
  loading: boolean
  loadingMessage: string
  error: unknown
  errorMessage: string
  isFetching: boolean
  onRetry: () => unknown
  errorRole?: 'alert' | 'status'
  retryLabel?: string
}

/** Mensajes locales para que una falla de consulta no parezca un resultado vacío. */
export const QuerySectionFeedback: React.FC<QuerySectionFeedbackProps> = ({
  loading,
  loadingMessage,
  error,
  errorMessage,
  isFetching,
  onRetry,
  errorRole = 'alert',
  retryLabel = 'Reintentar'
}) => {
  if (error) {
    return (
      <div
        role={errorRole}
        aria-live={errorRole === 'alert' ? 'assertive' : 'polite'}
        aria-atomic="true"
        className="flex flex-wrap items-center justify-between gap-3 rounded-2xl p-4 text-sm font-bold"
        style={{
          background: colors2000s.status.danger.bg,
          border: `1px solid ${colors2000s.status.danger.border}`,
          color: colors2000s.status.danger.text,
          boxShadow: colors2000s.shadows.insetDark
        }}
      >
        <span>{errorMessage}</span>
        <button
          type="button"
          onClick={() => void onRetry()}
          disabled={isFetching}
          className="min-h-11 rounded-xl px-4 py-3 text-[10px] font-black uppercase tracking-widest focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 disabled:cursor-not-allowed disabled:opacity-60"
          style={{
            background: colors2000s.bg.button,
            border: `1px solid ${colors2000s.status.danger.border}`,
            color: colors2000s.status.danger.text
          }}
        >
          {isFetching ? 'Reintentando...' : retryLabel}
        </button>
      </div>
    )
  }

  if (!loading) return null

  return (
    <div
      role="status"
      aria-live="polite"
      aria-busy="true"
      className="flex items-center justify-center gap-3 rounded-2xl p-6 text-sm font-bold"
      style={{ color: colors2000s.text.secondary }}
    >
      <Loader2 className="h-5 w-5 animate-spin" aria-hidden="true" />
      <span>{loadingMessage}</span>
    </div>
  )
}
