import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider, QueryCache, MutationCache } from '@tanstack/react-query'
import './index.css'
import App from './App.tsx'
import { registerDependencies } from './infrastructure/di/dependencies'
import { GlobalErrorHandler } from './shared/errors/GlobalErrorHandler'
import {
  ValidationErrorHandler,
  NotFoundErrorHandler,
  UnauthorizedErrorHandler,
  ForbiddenErrorHandler,
  ConflictErrorHandler,
  InternalServerErrorHandler,
  NetworkErrorHandler
} from './shared/errors/handlers/SpecificHandlers'
import { setupEventHandlers } from './infrastructure/setup/setupEventHandlers'

// 1. Initialize Dependency Injection Container
const container = registerDependencies()

// 2. Initialize and Wire Event Handlers
const eventBus = container.resolve<any>('eventBus')
setupEventHandlers(eventBus, {})

// 3. Initialize and Configure Global Error Handler Strategy
const globalErrorHandler = new GlobalErrorHandler()
globalErrorHandler.registerHandler(new ValidationErrorHandler())
globalErrorHandler.registerHandler(new NotFoundErrorHandler())
globalErrorHandler.registerHandler(new UnauthorizedErrorHandler())
globalErrorHandler.registerHandler(new ForbiddenErrorHandler())
globalErrorHandler.registerHandler(new ConflictErrorHandler())
globalErrorHandler.registerHandler(new InternalServerErrorHandler())
globalErrorHandler.registerHandler(new NetworkErrorHandler())

// Listen for global window runtime errors
window.addEventListener('error', (event) => {
  globalErrorHandler.handle(event.error)
})

// Listen for unhandled promise rejections
window.addEventListener('unhandledrejection', (event) => {
  globalErrorHandler.handle(event.reason)
})

// 4. Configure React Query with Global Error Handling
const queryClient = new QueryClient({
  queryCache: new QueryCache({
    onError: (error: unknown) => {
      globalErrorHandler.handle(error)
    }
  }),
  mutationCache: new MutationCache({
    onError: (error: unknown) => {
      globalErrorHandler.handle(error)
    }
  }),
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false
    }
  }
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </StrictMode>
)
