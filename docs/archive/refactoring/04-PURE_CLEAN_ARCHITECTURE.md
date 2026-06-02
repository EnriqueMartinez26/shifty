# 🏗️ PURE CLEAN ARCHITECTURE GUIDE

## What is Clean Architecture?

Clean Architecture is a set of principles that emphasizes **unidirectional dependency flow** and **separation of concerns**. The architecture is organized in concentric circles, where:

- **Inner circles** = Business logic (pure, reusable, independent)
- **Outer circles** = Technical details (frameworks, UI, databases)
- **Dependencies always point inward** (never outward)

---

## The 4-Layer Model

```
┌─────────────────────────────────────────────────────────────────┐
│                  PRESENTATION LAYER                             │
│  React Components, Pages, Hooks, Context                       │
│  ✅ Can import: Application, Domain, Infrastructure, Shared     │
│  ❌ Cannot import: Nothing (outermost layer)                    │
└────────────────────────┬────────────────────────────────────────┘
                        ↓ uses
┌─────────────────────────────────────────────────────────────────┐
│                  APPLICATION LAYER                              │
│  Services, Validators, DTOs, Mappers, Error Handling           │
│  ✅ Can import: Domain, Infrastructure, Shared                  │
│  ❌ Cannot import: Presentation                                 │
└────────────────────────┬────────────────────────────────────────┘
                        ↓ implements
┌─────────────────────────────────────────────────────────────────┐
│                   DOMAIN LAYER                                   │
│  Entities, Value Objects, Use Cases, Repository Interfaces     │
│  ✅ Can import: Only Domain (pure business logic)               │
│  ❌ Cannot import: ANYTHING ELSE (no React, no Axios!)         │
└────────────────────────┬────────────────────────────────────────┘
                        ↓ adapts
┌─────────────────────────────────────────────────────────────────┐
│               INFRASTRUCTURE LAYER                               │
│  HTTP Clients, Repository Implementations, Database Adapters   │
│  ✅ Can import: Domain, Shared                                  │
│  ❌ Cannot import: Application, Presentation                    │
└─────────────────────────────────────────────────────────────────┘

SHARED UTILITIES (Constants, Utils, Types) - Accessible to ALL layers
```

---

## Why This Architecture?

### ✅ Benefits

| Benefit | How |
|---------|-----|
| **Testability** | Domain logic tested without mocks; services tested with mock repos |
| **Reusability** | Domain + Application extractable to npm package or CLI |
| **Maintainability** | Clear boundaries = easy to understand code flow |
| **Scalability** | Add features without affecting other domains |
| **Independence** | Business logic independent of frameworks/UI libraries |
| **Flexibility** | Swap implementations (HTTP ↔ WebSocket, SQL ↔ NoSQL) |

### ❌ Without Clean Architecture

```typescript
// ❌ BAD: Tightly coupled, hard to test, impossible to reuse
function UserList() {
  const [users, setUsers] = useState([])
  
  useEffect(() => {
    // HTTP logic mixed with UI
    fetch('/api/users')
      .then(r => r.json())
      .then(data => setUsers(data))
  }, [])
  
  return <div>{users.map(u => <div>{u.name}</div>)}</div>
}
```

### ✅ With Clean Architecture

```typescript
// ✅ GOOD: Separated concerns, testable, reusable
function UserList() {
  const { data: users } = useUsers()  // Hook handles everything
  return <div>{users?.map(u => <div>{u.name}</div>)}</div>
}

// Hook uses service
export function useUsers() {
  const userService = new UserService(new HttpUserRepository())
  return useQuery({
    queryKey: ['users'],
    queryFn: () => userService.getUsers()
  })
}

// Service orchestrates domain logic
export class UserService {
  async getUsers(): Promise<User[]> {
    return this.repo.getAll()
  }
}

// Repository implements infrastructure
export class HttpUserRepository implements IUserRepository {
  async getAll(): Promise<User[]> {
    const response = await apiClient.get('/users')
    return response.data.map(data => new User(data))
  }
}
```

---

## Layer Responsibilities

### 📌 Domain Layer (src/domain/)

**Purpose**: Pure business logic independent of any framework

**Contains**:
- **Entities**: User, Staff, Appointment, Service (with business rules)
- **Value Objects**: Email, UserRole, Money, Duration, BookingStatus
- **Use Cases**: CreateUserUseCase, CancelAppointmentUseCase (orchestrate entities)
- **Repository Interfaces**: IUserRepository, IStaffRepository (contracts)
- **Exceptions**: DomainException, ValidationError (business errors)

**Characteristics**:
- ✅ NO React, NO axios, NO HTTP, NO database direct queries
- ✅ Pure TypeScript/JavaScript functions
- ✅ Focus on "WHAT" the business does, not "HOW"
- ✅ 100% testable without mocks

**Example**:
```typescript
// domain/entities/user.ts
export class User {
  private email: Email
  private role: UserRole
  
  constructor(props: UserProps) {
    this.email = Email.create(props.email) // Validates email
    this.role = UserRole.create(props.role)
  }
  
  isAdmin(): boolean {
    return this.role.equals(UserRole.ADMIN)
  }
  
  canCreateStaff(): boolean {
    return this.isAdmin()
  }
}

// domain/value-objects/email.ts
export class Email {
  static create(value: string): Email {
    if (!isValidEmail(value)) throw new ValidationError('Invalid email')
    return new Email(value)
  }
}

// domain/use-cases/user/create-user-use-case.ts
export class CreateUserUseCase {
  constructor(private repo: IUserRepository) {}
  
  async execute(input: CreateUserInput): Promise<User> {
    const existingUser = await this.repo.findByEmail(input.email)
    if (existingUser) throw new ConflictError('User already exists')
    
    const user = new User(input)
    return this.repo.save(user)
  }
}
```

---

### 🔧 Application Layer (src/application/)

**Purpose**: Orchestration, validation, and transformation between layers

**Contains**:
- **Services**: UserService, AppointmentService (coordinate use cases + repositories)
- **DTOs**: UserDTO, AppointmentDTO (data transfer objects)
- **Validators**: User schemas (Zod validation)
- **Mappers**: Entity ↔ DTO transformations
- **Error Handlers**: Convert domain exceptions to application errors

**Characteristics**:
- ✅ Imports Domain + Infrastructure
- ❌ NO React, NO direct HTTP calls (use repositories)
- ✅ Acts as "orchestrator" between domain and infrastructure
- ✅ Handles validation before passing to domain

**Example**:
```typescript
// application/services/user-service.ts
export class UserService {
  constructor(
    private userRepository: IUserRepository,
    private userMapper: UserMapper
  ) {}
  
  async createUser(input: CreateUserInput): Promise<UserDTO> {
    // 1. Validate input with Zod
    const validated = createUserSchema.parse(input)
    
    // 2. Execute use case (domain logic)
    const useCase = new CreateUserUseCase(this.userRepository)
    const user = await useCase.execute(validated)
    
    // 3. Transform to DTO for presentation
    return this.userMapper.toDTO(user)
  }
}

// application/validators/user-validators.ts
import { z } from 'zod'

export const createUserSchema = z.object({
  email: z.string().email('Invalid email'),
  name: z.string().min(3, 'Name too short'),
  role: z.enum(['admin', 'staff', 'client'])
})

// application/mappers/user-mapper.ts
export class UserMapper {
  toDTO(user: User): UserDTO {
    return {
      id: user.getId(),
      email: user.getEmail(),
      name: user.getName(),
      role: user.getRole()
    }
  }
  
  toDomain(dto: UserDTO): User {
    return new User({
      email: dto.email,
      name: dto.name,
      role: dto.role
    })
  }
}
```

---

### 🌐 Infrastructure Layer (src/infrastructure/)

**Purpose**: Adapt external systems (HTTP, database, cache) to domain interfaces

**Contains**:
- **HTTP Client**: Axios instance with interceptors
- **Repository Implementations**: HttpUserRepository, HttpStaffRepository (implement domain interfaces)
- **Storage Managers**: localStorage, sessionStorage wrappers
- **Cache**: Query result caching
- **Interceptors**: Auth tokens, error handling, retry logic

**Characteristics**:
- ✅ Implements Domain interfaces (IUserRepository, IStaffRepository)
- ✅ Depends on Domain (imports domain entities/interfaces)
- ❌ NO presentation logic, NO React components
- ✅ Technical details: HTTP, database queries, caching

**Example**:
```typescript
// infrastructure/http/client.ts
import axios from 'axios'
import axiosRetry from 'axios-retry'

const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_URL,
  timeout: 10000
})

// Add retry logic
axiosRetry(apiClient, {
  retries: 3,
  retryDelay: (count) => Math.pow(2, count) * 1000
})

// Add auth interceptor
apiClient.interceptors.request.use((config) => {
  const token = localStorage.getItem('shifty_token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

export default apiClient

// infrastructure/repositories/http-user-repository.ts
import { User } from '@domain/entities'
import { IUserRepository } from '@domain/repositories'

export class HttpUserRepository implements IUserRepository {
  constructor(private httpClient = apiClient) {}
  
  async getAll(): Promise<User[]> {
    const response = await this.httpClient.get('/users')
    return response.data.map((data: any) => new User(data))
  }
  
  async findByEmail(email: string): Promise<User | null> {
    try {
      const response = await this.httpClient.get(`/users?email=${email}`)
      return response.data ? new User(response.data) : null
    } catch (error) {
      if ((error as any).response?.status === 404) return null
      throw error
    }
  }
  
  async save(user: User): Promise<User> {
    const response = await this.httpClient.post('/users', user)
    return new User(response.data)
  }
}
```

---

### 🎨 Presentation Layer (src/presentation/)

**Purpose**: React UI - pages, components, hooks connecting domain/application to users

**Contains**:
- **Pages**: Full-screen components (Dashboard, Users, Settings, etc.)
- **Containers**: Smart components that orchestrate services + components
- **Components**: Dumb UI components (Atoms, Molecules, Organisms)
- **Hooks**: React hooks using services (useUsers, useAppointments, etc.)
- **Context**: React Context for global state (AuthContext, ThemeContext)
- **Layouts**: Page wrappers (AdminLayout, AuthLayout, PublicLayout)
- **API Routers**: Express-like route definitions

**Characteristics**:
- ✅ Only layer that imports Application services
- ✅ Uses hooks to abstract service calls
- ✅ Components receive data via props (no direct service calls)
- ❌ NO direct HTTP calls (use hooks/containers)
- ✅ Focused on user experience and interactions

**Example**:
```typescript
// presentation/hooks/use-users.ts
import { useQuery } from '@tanstack/react-query'
import { UserService } from '@application/services'
import { HttpUserRepository } from '@infrastructure/repositories'

export function useUsers() {
  const userService = new UserService(
    new HttpUserRepository()
  )
  
  return useQuery({
    queryKey: ['users'],
    queryFn: () => userService.getUsers()
  })
}

// presentation/containers/user-management-container.tsx
import { useUsers } from '@presentation/hooks'
import { UserGrid } from '@presentation/components/organisms'

export function UserManagementContainer() {
  const { data: users, isLoading, error } = useUsers()
  
  if (isLoading) return <LoadingSpinner />
  if (error) return <ErrorMessage error={error} />
  
  return <UserGrid users={users || []} />
}

// presentation/pages/users-page.tsx
import { AdminLayout } from '@presentation/layouts'
import { UserManagementContainer } from '@presentation/containers'

export function UsersPage() {
  return (
    <AdminLayout>
      <UserManagementContainer />
    </AdminLayout>
  )
}

// presentation/components/molecules/user-card.tsx
import { User } from '@domain/entities'
import { Button } from './button'

interface UserCardProps {
  user: User
  onEdit: (id: string) => void
  onDelete: (id: string) => void
}

export function UserCard({ user, onEdit, onDelete }: UserCardProps) {
  return (
    <div className="card">
      <h3>{user.getName()}</h3>
      <p>{user.getEmail()}</p>
      <Button onClick={() => onEdit(user.getId())}>Edit</Button>
      <Button onClick={() => onDelete(user.getId())}>Delete</Button>
    </div>
  )
}
```

---

### 🔗 Shared Layer (src/shared/)

**Purpose**: Utilities, constants, types available to all layers

**Contains**:
- **Utils**: cn.ts (className merging), date-utils, currency formatting, validation helpers
- **Constants**: API endpoints, valid roles, HTTP status codes
- **Types**: Global TypeScript interfaces, API response shapes
- **Theme**: Color system, spacing, typography values

**Characteristics**:
- ✅ Can be imported by ANY layer
- ❌ Cannot import from any layer (100% independent)
- ✅ Pure functions, no side effects
- ✅ Zero framework dependencies

**Example**:
```typescript
// shared/utils/cn.ts
import clsx from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...classes: (string | undefined)[]): string {
  return twMerge(clsx(classes))
}

// shared/constants/roles.ts
export const VALID_ROLES = ['admin', 'staff', 'client'] as const
export const ROLE_DISPLAY = {
  admin: 'Administrator',
  staff: 'Staff Member',
  client: 'Client'
}

// shared/utils/validation.ts
export function isValidEmail(email: string): boolean {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)
}
```

---

## Dependency Rule Visualization

### ✅ CORRECT Flow

```
Component → Hook → Service → Repository → Domain Entity
   ↓         ↓        ↓          ↓           ↓
Presentation → Application → Infrastructure → Domain
```

Each layer only imports from layers closer to center.

### ❌ WRONG Flow (Violates Rule)

```
Domain Entity ← Repository ← Service ← Component
   ⬆️           ⬆️           ⬆️        ⬆️
Violates!   Violates!   Violates!  OK
```

Domain should NEVER import from outer layers.

---

## Adding a New Feature

Follow this checklist:

### 1. Define Domain Model
- [ ] Create Entity in `domain/entities/feature-entity.ts`
- [ ] Create Value Objects if needed
- [ ] Write tests for business rules

### 2. Define Repository Interface
- [ ] Create `domain/repositories/i-feature-repository.ts`
- [ ] Define contract that infrastructure will implement

### 3. Create Use Cases
- [ ] Create `domain/use-cases/feature/create-feature-use-case.ts`
- [ ] Create other use cases (update, delete, query)
- [ ] Pure business logic only

### 4. Implement Application Service
- [ ] Create `application/services/feature-service.ts`
- [ ] Use use cases internally
- [ ] Return DTOs to presentation

### 5. Create Validators
- [ ] Create `application/validators/feature-validators.ts`
- [ ] Zod schemas for input validation

### 6. Implement Repository
- [ ] Create `infrastructure/repositories/http-feature-repository.ts`
- [ ] Implement domain interface
- [ ] Map HTTP responses to domain entities

### 7. Create Presentation Layer
- [ ] Create hook: `presentation/hooks/use-feature.ts`
- [ ] Create container: `presentation/containers/feature-container.tsx`
- [ ] Create components: `presentation/components/{atoms|molecules|organisms}/`
- [ ] Create page: `presentation/pages/feature-page.tsx`
- [ ] Create router: `presentation/api/v1/feature/router.tsx`

### 8. Wire Everything Together
- [ ] Add router to main app router
- [ ] Add route to navigation
- [ ] Add tests

---

## Testing Strategy

### Domain Tests (No Mocks)
```typescript
describe('User Entity', () => {
  it('should validate email', () => {
    const user = new User({
      email: 'test@example.com',
      name: 'Test',
      role: 'client'
    })
    
    expect(user.getEmail()).toBe('test@example.com')
  })
  
  it('should throw on invalid email', () => {
    expect(() => {
      new User({ email: 'invalid', name: 'Test', role: 'client' })
    }).toThrow(ValidationError)
  })
})
```

### Application Tests (Mock Repository)
```typescript
describe('UserService', () => {
  it('should create user', async () => {
    const mockRepo: IUserRepository = {
      findByEmail: jest.fn().mockResolvedValue(null),
      save: jest.fn().mockResolvedValue(new User({ /* ... */ }))
    }
    
    const service = new UserService(mockRepo)
    const result = await service.createUser({
      email: 'new@example.com',
      name: 'New User',
      role: 'client'
    })
    
    expect(mockRepo.save).toHaveBeenCalled()
    expect(result.email).toBe('new@example.com')
  })
})
```

### Presentation Tests (Component + Hook Testing)
```typescript
describe('UserManagementContainer', () => {
  it('should render users from hook', () => {
    jest.mock('@presentation/hooks', () => ({
      useUsers: () => ({
        data: [{ id: '1', name: 'User 1' }],
        isLoading: false
      })
    }))
    
    const { getByText } = render(<UserManagementContainer />)
    expect(getByText('User 1')).toBeInTheDocument()
  })
})
```

---

## Common Mistakes to Avoid

### ❌ Mistake 1: Domain Importing External Libraries
```typescript
// ❌ WRONG
import axios from 'axios'
import { useState } from 'react'

export class User {
  // ...
}
```

**✅ Fix**: Domain stays pure, only infrastructure imports axios

### ❌ Mistake 2: Presentation Importing Infrastructure
```typescript
// ❌ WRONG in presentation/pages/users-page.tsx
import { apiClient } from '@infrastructure/http/client'

export function UsersPage() {
  const [users, setUsers] = useState([])
  useEffect(() => {
    apiClient.get('/users').then(r => setUsers(r.data))
  }, [])
}
```

**✅ Fix**: Use hook that abstracts service:
```typescript
import { useUsers } from '@presentation/hooks'

export function UsersPage() {
  const { data: users } = useUsers()
}
```

### ❌ Mistake 3: Application Importing Presentation
```typescript
// ❌ WRONG
import { Button } from '@presentation/components'

export class UserService {
  render() {
    return <Button />  // Service shouldn't return JSX!
  }
}
```

**✅ Fix**: Application returns data/DTOs, presentation renders

### ❌ Mistake 4: Circular Dependencies
```typescript
// ❌ WRONG
// service-a.ts
import { ServiceB } from './service-b'

// service-b.ts
import { ServiceA } from './service-a'  // CIRCULAR!
```

**✅ Fix**: Refactor to use dependency injection or separate concerns

---

## Verification Checklist

Before committing code:

- [ ] Domain layer imports ONLY from domain/
- [ ] Application layer imports from domain/ + infrastructure/ + shared/
- [ ] Infrastructure layer imports from domain/ + shared/ only
- [ ] Presentation layer imports from domain/ + application/ + presentation/ + shared/
- [ ] No React in domain/
- [ ] No Axios in domain/
- [ ] No circular imports
- [ ] All services receive dependencies via constructor
- [ ] All components receive data via props (not direct service calls)
- [ ] All HTTP calls abstracted to repositories
- [ ] All validation in application/ layer
- [ ] Tests for domain entities (no mocks needed)
- [ ] Tests for services (mock repositories)
- [ ] Tests for components (mock hooks)

