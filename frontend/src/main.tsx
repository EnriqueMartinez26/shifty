import { StrictMode } from 'react'

import { QueryClient, QueryClientProvider, QueryCache, MutationCache } from '@tanstack/react-query'

import { createRoot } from 'react-dom/client'
import { Toaster } from 'sonner'

import './index.css'
import App from './App.tsx'
import { initSentry, Sentry } from './infrastructure/observability/sentry'
import {
  ValidationErrorHandler,
  NotFoundErrorHandler,
  UnauthorizedErrorHandler,
  ForbiddenErrorHandler,
  ConflictErrorHandler,
  InternalServerErrorHandler,
  NetworkErrorHandler,
  setToastSink,
  TransientErrorHandler
} from './infrastructure/setup/SpecificHandlers'
import { ErrorBoundaryFallback } from './presentation/components/error-boundary'
import { showToast } from './presentation/lib/notify'
import {
  queryRetryDelay,
  refreshSubscriptionOnSuspension,
  shouldNotifyQueryError,
  shouldRetryQuery
} from './presentation/lib/queryClientPolicies'
import { setUnreadableInstantReporter } from './presentation/lib/reportUnreadableInstant'
import { GlobalErrorHandler } from './shared/errors/GlobalErrorHandler'

initSentry()

// Una fecha ilegible degrada a texto de respaldo en vez de tumbar la pantalla;
// esto evita que ademas se pierda la senal de que llego un dato corrupto.
setUnreadableInstantReporter((message) => Sentry.captureMessage(message, 'warning'))

// Los handlers globales avisan por sonner (FF-17, D-20260928-07).
setToastSink(showToast)

// 1. Initialize and Configure Global Error Handler Strategy
const globalErrorHandler = new GlobalErrorHandler()
globalErrorHandler.registerHandler(new ValidationErrorHandler())
globalErrorHandler.registerHandler(new NotFoundErrorHandler())
globalErrorHandler.registerHandler(new UnauthorizedErrorHandler())
globalErrorHandler.registerHandler(new ForbiddenErrorHandler())
globalErrorHandler.registerHandler(new ConflictErrorHandler())
globalErrorHandler.registerHandler(new InternalServerErrorHandler())
globalErrorHandler.registerHandler(new NetworkErrorHandler())
globalErrorHandler.registerHandler(new TransientErrorHandler())

// Listen for global window runtime errors
window.addEventListener('error', (event) => {
  void globalErrorHandler.handle(event.error)
})

// Listen for unhandled promise rejections
window.addEventListener('unhandledrejection', (event) => {
  void globalErrorHandler.handle(event.reason)
})

// 2. Configure React Query with Global Error Handling
const queryClient = new QueryClient({
  queryCache: new QueryCache({
    onError: (error: unknown, query) => {
      if (shouldNotifyQueryError(query)) void globalErrorHandler.handle(error)
    }
  }),
  // Una mutacion fallida NO avisa desde aca: casi todas usan `mutateAsync`
  // con su propio catch y mensaje en pantalla, y el aviso global lo
  // duplicaria (en el login, un 401 diria "sesion expirada"). La que nadie
  // atrapa termina en `unhandledrejection`, que si avisa (FF-17).
  mutationCache: new MutationCache({
    onError: (error: unknown) => {
      refreshSubscriptionOnSuspension(error, queryClient)
    }
  }),
  defaultOptions: {
    queries: {
      // Un reintento, y solo ante red o 5xx: un 4xx no cambia por repetirlo.
      retry: shouldRetryQuery,
      // Respeta el Retry-After de un 503 (F4-04).
      retryDelay: queryRetryDelay,
      refetchOnWindowFocus: false,
      // Sin esto (default 0) cada navegacion re-dispara TODAS las queries de la
      // pantalla. 30s de frescura corta el refetch redundante sin mostrar datos
      // viejos; las mutaciones ya invalidan lo que corresponde.
      staleTime: 30_000
    }
  }
})

const rootElement = document.getElementById('root')
if (!rootElement) {
  throw new Error('No se encontró el elemento #root en el documento')
}

createRoot(rootElement).render(
  <StrictMode>
    <Toaster position="top-right" richColors closeButton />
    <Sentry.ErrorBoundary fallback={<ErrorBoundaryFallback />}>
      <QueryClientProvider client={queryClient}>
        <App />
      </QueryClientProvider>
    </Sentry.ErrorBoundary>
  </StrictMode>
)
