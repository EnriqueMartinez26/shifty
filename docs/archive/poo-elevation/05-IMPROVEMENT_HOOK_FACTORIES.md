# 🎣 IMPROVEMENT 5: HOOK FACTORIES & STRATEGY PATTERN

## 🎯 Goal
Create sophisticated hook factories that leverage DI Container and support Strategy pattern for different implementations.

**POO Gain**: +4%  
**Effort**: 2-3 days  
**Priority**: 🟡 HIGH (depends on: Improvements 1-2)

---

## 🏗️ IMPLEMENTATION

### Step 1: Basic Service Hook

**File**: `frontend/src/presentation/hooks/useService.ts`

```typescript
import { ServiceContainer } from '@core/di/ServiceContainer'

/**
 * Generic hook to access any service from DI container
 */
export function useService<T = any>(key: string): T {
  const container = ServiceContainer.getInstance()
  return container.get<T>(key)
}
```

### Step 2: Query Hooks with DI

**File**: `frontend/src/presentation/hooks/use-users.ts`

```typescript
import { useQuery, useMutation } from '@tanstack/react-query'
import { ServiceContainer } from '@core/di/ServiceContainer'
import { UserService } from '@application/services/user-service'
import { CreateUserInput } from '@application/dtos/user-dtos'

/**
 * Hook: Fetch all users
 * Pattern: Query with DI
 */
export function useUsers() {
  const container = ServiceContainer.getInstance()
  const userService = container.get<UserService>('userService')

  return useQuery({
    queryKey: ['users'],
    queryFn: () => userService.getAll(),
    staleTime: 5 * 60 * 1000,
    retry: 2
  })
}

/**
 * Hook: Fetch single user
 * Pattern: Query with parameters
 */
export function useUser(userId: string) {
  const container = ServiceContainer.getInstance()
  const userService = container.get<UserService>('userService')

  return useQuery({
    queryKey: ['users', userId],
    queryFn: () => userService.getById(userId),
    enabled: !!userId
  })
}

/**
 * Hook: Create user
 * Pattern: Mutation with cache invalidation
 */
export function useCreateUser() {
  const container = ServiceContainer.getInstance()
  const userService = container.get<UserService>('userService')
  const queryClient = container.get<QueryClient>('queryClient')

  return useMutation({
    mutationFn: (input: CreateUserInput) => userService.create(input),
    onSuccess: () => {
      // Invalidate cache to refetch
      queryClient.invalidateQueries({ queryKey: ['users'] })
    },
    onError: (error) => {
      console.error('Error creating user:', error)
    }
  })
}

/**
 * Hook: Update user
 * Pattern: Mutation with optimistic update
 */
export function useUpdateUser() {
  const container = ServiceContainer.getInstance()
  const userService = container.get<UserService>('userService')
  const queryClient = container.get<QueryClient>('queryClient')

  return useMutation({
    mutationFn: ({ id, input }: { id: string; input: any }) =>
      userService.update(id, input),
    onMutate: async ({ id, input }) => {
      // Cancel outgoing queries
      await queryClient.cancelQueries({ queryKey: ['users', id] })

      // Optimistic update
      const previous = queryClient.getQueryData(['users', id])
      queryClient.setQueryData(['users', id], { ...previous, ...input })

      return { previous }
    },
    onError: (error, variables, context) => {
      // Revert on error
      if (context?.previous) {
        queryClient.setQueryData(['users', variables.id], context.previous)
      }
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users'] })
    }
  })
}

/**
 * Hook: Delete user
 */
export function useDeleteUser() {
  const container = ServiceContainer.getInstance()
  const userService = container.get<UserService>('userService')
  const queryClient = container.get<QueryClient>('queryClient')

  return useMutation({
    mutationFn: (userId: string) => userService.delete(userId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users'] })
    }
  })
}
```

### Step 3: Strategy Pattern Hooks

**File**: `frontend/src/presentation/hooks/use-auth-flow.ts`

```typescript
import { ServiceContainer } from '@core/di/ServiceContainer'

/**
 * Authentication strategies (Strategy pattern)
 */
export interface IAuthStrategy {
  login(email: string, password: string): Promise<any>
  logout(): Promise<void>
  register(email: string, password: string): Promise<any>
  refreshToken(): Promise<string>
}

/**
 * Hook with strategy selection
 * Pattern: Strategy Pattern + DI Container
 */
export function useAuthFlow(strategy: 'local' | 'oauth' = 'local'): IAuthStrategy {
  const container = ServiceContainer.getInstance()

  const strategies: Record<string, string> = {
    local: 'localAuthStrategy',
    oauth: 'oauthStrategy'
  }

  const strategyKey = strategies[strategy]
  if (!strategyKey) {
    throw new Error(`Unknown auth strategy: ${strategy}`)
  }

  return container.get<IAuthStrategy>(strategyKey)
}

/**
 * Local auth implementation
 */
export class LocalAuthStrategy implements IAuthStrategy {
  constructor(private authService: any) {}

  async login(email: string, password: string): Promise<any> {
    const result = await this.authService.login(email, password)
    localStorage.setItem('token', result.token)
    return result
  }

  async logout(): Promise<void> {
    localStorage.removeItem('token')
    await this.authService.logout()
  }

  async register(email: string, password: string): Promise<any> {
    return this.authService.register(email, password)
  }

  async refreshToken(): Promise<string> {
    const token = await this.authService.refreshToken()
    localStorage.setItem('token', token)
    return token
  }
}

/**
 * OAuth implementation (can be swapped at runtime)
 */
export class OAuthStrategy implements IAuthStrategy {
  constructor(private oauthService: any) {}

  async login(email: string, password: string): Promise<any> {
    return this.oauthService.startFlow()
  }

  async logout(): Promise<void> {
    return this.oauthService.logout()
  }

  async register(email: string, password: string): Promise<any> {
    throw new Error('OAuth does not support direct registration')
  }

  async refreshToken(): Promise<string> {
    return this.oauthService.refreshToken()
  }
}
```

### Step 4: Batch Operations Hooks

**File**: `frontend/src/presentation/hooks/use-batch-users.ts`

```typescript
import { useQueries } from '@tanstack/react-query'
import { ServiceContainer } from '@core/di/ServiceContainer'

/**
 * Hook: Batch fetch multiple users (optimization)
 * Pattern: Parallel queries via useQueries
 */
export function useBatchUsers(userIds: string[]) {
  const container = ServiceContainer.getInstance()
  const userService = container.get<UserService>('userService')

  return useQueries({
    queries: userIds.map(id => ({
      queryKey: ['users', id],
      queryFn: () => userService.getById(id),
      staleTime: 5 * 60 * 1000
    }))
  })
}

/**
 * Hook: Batch operations (concurrent mutations)
 */
export function useBatchCreateUsers() {
  const container = ServiceContainer.getInstance()
  const userService = container.get<UserService>('userService')

  return async (inputs: CreateUserInput[]) => {
    return Promise.all(
      inputs.map(input => userService.create(input))
    )
  }
}
```

### Step 5: Composable Hooks

**File**: `frontend/src/presentation/hooks/use-paginated-users.ts`

```typescript
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { ServiceContainer } from '@core/di/ServiceContainer'

/**
 * Hook: Paginated data fetching (composition)
 * Pattern: Hooks composition + DI
 */
export function usePaginatedUsers(pageSize: number = 10) {
  const [page, setPage] = useState(1)
  const container = ServiceContainer.getInstance()
  const userService = container.get<UserService>('userService')

  const { data, isLoading, error } = useQuery({
    queryKey: ['users', 'paginated', page],
    queryFn: async () => {
      const allUsers = await userService.getAll()
      const start = (page - 1) * pageSize
      const end = start + pageSize
      return {
        items: allUsers.slice(start, end),
        total: allUsers.length,
        page,
        pageSize,
        totalPages: Math.ceil(allUsers.length / pageSize)
      }
    }
  })

  return {
    data: data?.items || [],
    pagination: {
      page,
      pageSize,
      total: data?.total || 0,
      totalPages: data?.totalPages || 0
    },
    isLoading,
    error,
    goToPage: (p: number) => setPage(p),
    nextPage: () => setPage(p => p + 1),
    prevPage: () => setPage(p => Math.max(1, p - 1))
  }
}
```

### Step 6: Testing Hooks with DI

**File**: `frontend/src/__tests__/presentation/hooks/use-users.test.ts`

```typescript
import { renderHook, waitFor } from '@testing-library/react'
import { useUsers } from '@presentation/hooks/use-users'
import { ServiceContainer } from '@core/di/ServiceContainer'
import { InMemoryUserRepository } from '@infrastructure/repositories/in-memory-user-repository'
import { User } from '@domain/entities/User'

describe('useUsers Hook - DI Integration', () => {
  beforeEach(() => {
    // Reset DI container
    ServiceContainer.reset()

    // Register test implementations
    const container = ServiceContainer.getInstance()
    const repository = new InMemoryUserRepository()

    // Seed test data
    const user1 = User.create({ email: 'test1@example.com', name: 'Test 1', role: 'client' })
    const user2 = User.create({ email: 'test2@example.com', name: 'Test 2', role: 'staff' })
    repository.seed([user1, user2])

    container.register('userRepository', () => repository, { singleton: true })
    container.register('userService', () => {
      return new UserService(container.get('userRepository'))
    }, { singleton: true })

    container.initialize()
  })

  it('should fetch users from DI service', async () => {
    const { result } = renderHook(() => useUsers())

    await waitFor(() => {
      expect(result.current.isSuccess).toBe(true)
    })

    expect(result.current.data).toHaveLength(2)
    expect(result.current.data[0].getName()).toBe('Test 1')
  })

  it('should use same service instance', async () => {
    const container = ServiceContainer.getInstance()
    const service1 = container.get('userService')
    const service2 = container.get('userService')

    expect(service1).toBe(service2)  // Same singleton
  })
})
```

---

## ✅ Checklist

- [ ] Create generic `useService` hook
- [ ] Create domain-specific hooks for each service
- [ ] Implement Strategy pattern hooks
- [ ] Create batch operation hooks
- [ ] Create composable hooks (pagination, etc.)
- [ ] Create comprehensive hook tests
- [ ] Verify hooks work with DI container
- [ ] Update components to use new hooks

---

## 🎯 Success Criteria

✅ All hooks use DI container  
✅ Strategy pattern hooks switchable at runtime  
✅ No service instantiation in components  
✅ Hooks fully testable with in-memory repositories  
✅ Error handling consistent  
✅ React Query best practices followed  

