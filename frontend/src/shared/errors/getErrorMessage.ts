type ApiErrorLike = {
  message?: unknown
  response?: {
    data?: {
      detail?: unknown
    }
  }
}

export const getErrorMessage = (error: unknown, fallback: string): string => {
  const maybeError = error as ApiErrorLike | undefined
  const detail = maybeError?.response?.data?.detail
  const message = maybeError?.message

  if (typeof detail === 'string' && detail.trim()) return detail
  if (typeof message === 'string' && message.trim()) return message
  return fallback
}
