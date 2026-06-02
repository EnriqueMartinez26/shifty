# 🔌 IMPROVEMENT 1: DEPENDENCY INJECTION CONTAINER

## 🎯 Goal
Centralize dependency management using a Service Container (DIP - Dependency Inversion Principle).

**POO Gain**: +8%  
**Effort**: 2-3 days  
**Priority**: 🔴 CRITICAL (blocks improvements 2-5)

---

## 📊 Current State vs Target

### ❌ CURRENT (Weak DIP)
```typescript
// ❌ Ad-hoc factory pattern (not DI)
function useUsers() {
  const userService = new UserService(
    new HttpUserRepository(apiClient)  // NEW instance every render!
  )
  return useQuery(['users'], () => userService.getUsers())
}

// Problems:
// 1. New instance on every hook call
// 2. Difficult to swap implementations (testing)
// 3. No centralized dependency graph
// 4. Violates DIP (depends on concrete implementations)
```

### ✅ TARGET (Strong DIP)
```typescript
// ✅ Proper DI container
class ServiceContainer {
  private static instance: ServiceContainer
  private services: Map<string, () => any> = new Map()
  
  static getInstance(): ServiceContainer {
    if (!ServiceContainer.instance) {
      ServiceContainer.instance = new ServiceContainer()
    }
    return ServiceContainer.instance
  }
  
  register(key: string, factory: () => any): void {
    this.services.set(key, factory)
  }
  
  get<T>(key: string): T {
    const factory = this.services.get(key)
    if (!factory) throw new Error(`Service "${key}" not registered`)
    return factory() as T
  }
}

// Usage in hook
function useUsers() {
  const container = ServiceContainer.getInstance()
  const userService = container.get<UserService>('userService')
  return useQuery(['users'], () => userService.getAll())
}
```

---

## 🏗️ IMPLEMENTATION

### Step 1: Create ServiceContainer

**File**: `frontend/src/core/di/ServiceContainer.ts`

```typescript
/**
 * ServiceContainer: Central Dependency Injection Container
 *
 * Principles:
 * - Singleton pattern (single instance across app)
 * - Factory functions (lazy instantiation)
 * - Type-safe service retrieval
 * - Centralized dependency graph
 *
 * DIP: Depend on abstractions (interfaces), not implementations
 */

export class ServiceContainer {
  private static instance: ServiceContainer | null = null
  private services: Map<string, () => any> = new Map()
  private singletons: Map<string, any> = new Map()
  private initialized: boolean = false

  private constructor() {
    // Private constructor enforces singleton
  }

  /**
   * Get or create the singleton instance
   */
  static getInstance(): ServiceContainer {
    if (!ServiceContainer.instance) {
      ServiceContainer.instance = new ServiceContainer()
    }
    return ServiceContainer.instance
  }

  /**
   * Reset for testing purposes
   */
  static reset(): void {
    ServiceContainer.instance = null
  }

  /**
   * Register a service factory
   *
   * @param key - Service identifier
   * @param factory - Function that creates the service
   * @param options - { singleton: true } to cache instance
   *
   * Example:
   * container.register('userService', () => {
   *   return new UserService(container.get('userRepository'))
   * })
   */
  register<T = any>(
    key: string,
    factory: () => T,
    options: { singleton?: boolean } = {}
  ): void {
    if (this.services.has(key)) {
      console.warn(`Service "${key}" already registered, overwriting`)
    }

    this.services.set(key, factory)

    if (options.singleton) {
      // Pre-create singleton
      this.singletons.set(key, factory())
    }
  }

  /**
   * Retrieve a service instance
   *
   * @param key - Service identifier
   * @returns Service instance or throws if not registered
   *
   * Example:
   * const userService = container.get<UserService>('userService')
   */
  get<T = any>(key: string): T {
    // Check singleton cache first
    if (this.singletons.has(key)) {
      return this.singletons.get(key) as T
    }

    const factory = this.services.get(key)
    if (!factory) {
      throw new ServiceNotFoundError(
        `Service "${key}" not registered. Register it in dependencies.ts`
      )
    }

    return factory() as T
  }

  /**
   * Check if service is registered
   */
  has(key: string): boolean {
    return this.services.has(key) || this.singletons.has(key)
  }

  /**
   * Initialize all singleton services
   * Call this after all registrations are complete
   */
  initialize(): void {
    if (this.initialized) return

    const singletonKeys = Array.from(this.services.entries())
      .filter(([_, __]) => this.singletons.has(_))
      .map(([key, _]) => key)

    for (const key of singletonKeys) {
      this.get(key)
    }

    this.initialized = true
  }

  /**
   * Get all registered service keys (for debugging)
   */
  getRegisteredServices(): string[] {
    return Array.from(this.services.keys())
  }

  /**
   * Clear all services (for testing)
   */
  clear(): void {
    this.services.clear()
    this.singletons.clear()
    this.initialized = false
  }
}

/**
 * Custom error for missing services
 */
export class ServiceNotFoundError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'ServiceNotFoundError'
  }
}
```

### Step 2: Create Dependencies Registration

**File**: `frontend/src/core/di/dependencies.ts`

```typescript
/**
 * Dependencies: Central registration of all services
 *
 * This file is THE SOURCE OF TRUTH for the dependency graph.
 * All services are registered here, making it easy to:
 * - Understand what services exist
 * - Swap implementations (for testing)
 * - Add new services
 * - Debug dependency issues
 */

import { ServiceContainer } from './ServiceContainer'

// Repositories (Infrastructure)
import { HttpUserRepository } from '@infrastructure/repositories/http-user-repository'
import { HttpStaffRepository } from '@infrastructure/repositories/http-staff-repository'
import { HttpServiceRepository } from '@infrastructure/repositories/http-service-repository'
import { HttpAppointmentRepository } from '@infrastructure/repositories/http-appointment-repository'
import { HttpBookingRepository } from '@infrastructure/repositories/http-booking-repository'

// Services (Application)
import { UserService } from '@application/services/user-service'
import { StaffService } from '@application/services/staff-service'
import { ServiceService } from '@application/services/service-service'
import { AppointmentService } from '@application/services/appointment-service'
import { BookingService } from '@application/services/booking-service'

// HTTP Client (Infrastructure)
import { apiClient } from '@infrastructure/http/client'

export function registerDependencies(): void {
  const container = ServiceContainer.getInstance()

  // ============================================================================
  // LAYER 1: INFRASTRUCTURE (External adapters)
  // ============================================================================

  // HTTP Client (singleton - reuse across app)
  container.register(
    'apiClient',
    () => apiClient,
    { singleton: true }
  )

  // Repositories (singletons - one repository per resource)
  container.register(
    'userRepository',
    () => new HttpUserRepository(container.get('apiClient')),
    { singleton: true }
  )

  container.register(
    'staffRepository',
    () => new HttpStaffRepository(container.get('apiClient')),
    { singleton: true }
  )

  container.register(
    'serviceRepository',
    () => new HttpServiceRepository(container.get('apiClient')),
    { singleton: true }
  )

  container.register(
    'appointmentRepository',
    () => new HttpAppointmentRepository(container.get('apiClient')),
    { singleton: true }
  )

  container.register(
    'bookingRepository',
    () => new HttpBookingRepository(container.get('apiClient')),
    { singleton: true }
  )

  // ============================================================================
  // LAYER 2: APPLICATION (Services)
  // ============================================================================

  // Services (singletons - one service per domain entity)
  container.register(
    'userService',
    () => new UserService(
      container.get('userRepository'),
      container.get('eventBus')  // Will add in improvement 7
    ),
    { singleton: true }
  )

  container.register(
    'staffService',
    () => new StaffService(
      container.get('staffRepository'),
      container.get('eventBus')
    ),
    { singleton: true }
  )

  container.register(
    'serviceService',
    () => new ServiceService(
      container.get('serviceRepository'),
      container.get('eventBus')
    ),
    { singleton: true }
  )

  container.register(
    'appointmentService',
    () => new AppointmentService(
      container.get('appointmentRepository'),
      container.get('eventBus')
    ),
    { singleton: true }
  )

  container.register(
    'bookingService',
    () => new BookingService(
      container.get('bookingRepository'),
      container.get('eventBus')
    ),
    { singleton: true }
  )

  // ============================================================================
  // LAYER 3: PRESENTATION (Utilities)
  // ============================================================================

  // Query client (React Query singleton)
  container.register(
    'queryClient',
    () => {
      const QueryClient = require('@tanstack/react-query').QueryClient
      return new QueryClient({
        defaultOptions: {
          queries: { staleTime: 5 * 60 * 1000 },
          mutations: { retry: 1 }
        }
      })
    },
    { singleton: true }
  )

  // ============================================================================
  // Mark container as initialized
  // ============================================================================

  container.initialize()
}

/**
 * Convenience function to reset dependencies (for testing)
 */
export function resetDependencies(): void {
  ServiceContainer.reset()
}

/**
 * Get container instance
 */
export function getContainer(): ServiceContainer {
  return ServiceContainer.getInstance()
}
```

### Step 3: Initialize Container in App

**File**: `frontend/src/main.tsx`

```typescript
import React from 'react'
import ReactDOM from 'react-dom/client'
import { registerDependencies } from '@core/di/dependencies'
import App from './App'
import './index.css'

// Initialize Dependency Injection Container
// Must be called before any services are used
registerDependencies()

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
)
```

### Step 4: Create DI Hook Factory

**File**: `frontend/src/presentation/hooks/useService.ts`

```typescript
import { ServiceContainer } from '@core/di/ServiceContainer'

/**
 * Hook to access any service from DI container
 *
 * Usage:
 * const userService = useService<UserService>('userService')
 * const userService = useService('userService')  // with type inference
 */
export function useService<T = any>(key: string): T {
  const container = ServiceContainer.getInstance()

  if (!container.has(key)) {
    throw new Error(
      `Service "${key}" not found. Make sure it's registered in dependencies.ts`
    )
  }

  return container.get<T>(key)
}

/**
 * Advanced: Hook with service validation
 */
export function useServiceWithFallback<T>(
  key: string,
  fallback: T
): T {
  const container = ServiceContainer.getInstance()

  if (!container.has(key)) {
    console.warn(`Service "${key}" not found, using fallback`)
    return fallback
  }

  return container.get<T>(key)
}
```

### Step 5: Update Hooks to Use DI

**File**: `frontend/src/presentation/hooks/use-users.ts` (Example)

```typescript
// BEFORE: ❌ New service on every hook call
// function useUsers() {
//   const userService = new UserService(
//     new HttpUserRepository(apiClient)
//   )
//   return useQuery(['users'], () => userService.getUsers())
// }

// AFTER: ✅ Using DI container
import { useQuery } from '@tanstack/react-query'
import { useService } from './useService'
import { UserService } from '@application/services/user-service'

export function useUsers() {
  // Get service from DI container (same instance)
  const userService = useService<UserService>('userService')

  return useQuery({
    queryKey: ['users'],
    queryFn: () => userService.getAll(),
    staleTime: 5 * 60 * 1000
  })
}

export function useCreateUser() {
  const userService = useService<UserService>('userService')

  return useMutation({
    mutationFn: (input: CreateUserInput) => userService.create(input),
    onSuccess: (user) => {
      queryClient.invalidateQueries({ queryKey: ['users'] })
    }
  })
}
```

---

## 🧪 Testing DI Container

**File**: `frontend/src/__tests__/core/di/ServiceContainer.test.ts`

```typescript
import { ServiceContainer } from '@core/di/ServiceContainer'

describe('ServiceContainer - DI Container', () => {
  let container: ServiceContainer

  beforeEach(() => {
    ServiceContainer.reset()
    container = ServiceContainer.getInstance()
  })

  afterEach(() => {
    container.clear()
  })

  describe('Singleton Pattern', () => {
    it('should return same instance', () => {
      const instance1 = ServiceContainer.getInstance()
      const instance2 = ServiceContainer.getInstance()

      expect(instance1).toBe(instance2)
    })
  })

  describe('Service Registration', () => {
    it('should register and retrieve service', () => {
      const mockService = { name: 'test' }
      container.register('test', () => mockService)

      expect(container.get('test')).toBe(mockService)
    })

    it('should throw error if service not registered', () => {
      expect(() => container.get('nonexistent')).toThrow()
    })

    it('should check if service exists', () => {
      container.register('exists', () => ({}))

      expect(container.has('exists')).toBe(true)
      expect(container.has('notexists')).toBe(false)
    })
  })

  describe('Singleton Services', () => {
    it('should return same instance for singleton', () => {
      let callCount = 0
      container.register(
        'singleton',
        () => {
          callCount++
          return { id: callCount }
        },
        { singleton: true }
      )

      const first = container.get('singleton')
      const second = container.get('singleton')

      expect(first).toBe(second)
      expect(callCount).toBe(1)
    })

    it('should create new instance for non-singleton', () => {
      let callCount = 0
      container.register('factory', () => {
        callCount++
        return { id: callCount }
      })

      const first = container.get('factory')
      const second = container.get('factory')

      expect(first.id).toBe(1)
      expect(second.id).toBe(2)
      expect(callCount).toBe(2)
    })
  })

  describe('Dependency Graph', () => {
    it('should resolve complex dependency graph', () => {
      // Mock repositories
      container.register('userRepository', () => ({ name: 'userRepo' }))

      // Mock service depending on repository
      container.register(
        'userService',
        () => {
          const userRepo = container.get('userRepository')
          return { repository: userRepo, name: 'userService' }
        },
        { singleton: true }
      )

      const service = container.get('userService')

      expect(service.name).toBe('userService')
      expect(service.repository.name).toBe('userRepo')
    })
  })

  describe('Type Safety', () => {
    interface UserService {
      getUsers(): Promise<any[]>
    }

    it('should maintain type safety', () => {
      const mockService: UserService = {
        getUsers: async () => []
      }

      container.register('userService', () => mockService)

      const service = container.get<UserService>('userService')
      expect(typeof service.getUsers).toBe('function')
    })
  })
})
```

---

## ✅ Checklist

- [ ] Create `ServiceContainer.ts`
- [ ] Create `dependencies.ts`
- [ ] Update `main.tsx` to call `registerDependencies()`
- [ ] Create `useService.ts` hook
- [ ] Update all hooks to use `useService()`
- [ ] Create unit tests
- [ ] Test in browser (no console errors)
- [ ] Document in team wiki

---

## 🎯 Success Criteria

✅ All services registered in one place  
✅ No `new ServiceName()` in components  
✅ All hooks use `useService()`  
✅ Tests can easily swap implementations  
✅ Build passes with zero errors  
✅ Team understands DI pattern  

---

## 📚 Learning Resources

- **SOLID**: https://en.wikipedia.org/wiki/SOLID
- **DIP**: https://en.wikipedia.org/wiki/Dependency_inversion_principle
- **Service Locator Pattern**: https://martinfowler.com/articles/service-locator.html
- **TypeScript DI**: https://inversify.io/

