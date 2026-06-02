# 📐 IMPORT RULES & DEPENDENCY RULE ENFORCEMENT

## Core Principle: UNIDIRECTIONAL DEPENDENCY FLOW

```
┌────────────────────────────────────────────┐
│   PRESENTATION (React UI)                   │
│   ↓ imports from ↓                         │
├────────────────────────────────────────────┤
│   APPLICATION (Services, Validators)        │
│   ↓ imports from ↓                         │
├────────────────────────────────────────────┤
│   DOMAIN (Entities, Use Cases, Interfaces) │
│   ↓ imports from ↓                         │
├────────────────────────────────────────────┤
│   INFRASTRUCTURE (HTTP, Repositories)      │
│                                            │
│   ✅ Can only import from DOMAIN           │
└────────────────────────────────────────────┘

SHARED (Constants, Utils, Types)
├── Can be imported by ANY layer
└── Cannot import from any layer
```

---

## ✅ ALLOWED IMPORT PATTERNS

### 1️⃣ From PRESENTATION Layer

#### ✅ Import from Application
```typescript
// presentation/pages/users-page.tsx
import { UserService } from '@application/services'
import { CreateUserInput, UpdateUserInput } from '@application/dtos'
import { userValidator } from '@application/validators'
import { UserMapper } from '@application/mappers'
```

#### ✅ Import from Domain
```typescript
// presentation/containers/user-management-container.tsx
import { User } from '@domain/entities'
import { UserRole } from '@domain/value-objects'
import { IUserRepository } from '@domain/repositories'
import type { Appointment } from '@domain/entities'
```

#### ✅ Import from Infrastructure
```typescript
// presentation/api/v1/users/dependencies.ts (injection point)
import { HttpUserRepository } from '@infrastructure/repositories'
import { apiClient } from '@infrastructure/http/client'
```

#### ✅ Import from Shared
```typescript
// presentation/components/atoms/button.tsx
import { cn } from '@shared/utils'
import { COLORS } from '@shared/theme'
import { API_ENDPOINTS } from '@shared/constants'
```

#### ✅ Import from other Presentation
```typescript
// presentation/pages/users-page.tsx
import { UserManagementContainer } from '@presentation/containers'
import { UserCard } from '@presentation/components/molecules'
import { AdminLayout } from '@presentation/layouts'
import { useUsers } from '@presentation/hooks'
import { AuthContext } from '@presentation/context'
```

---

### 2️⃣ From APPLICATION Layer

#### ✅ Import from Domain
```typescript
// application/services/user-service.ts
import { User } from '@domain/entities'
import { IUserRepository } from '@domain/repositories'
import { CreateUserUseCase } from '@domain/use-cases'
import { ValidationError } from '@domain/exceptions'
```

#### ✅ Import from Infrastructure
```typescript
// application/services/user-service.ts (constructor injection)
import { HttpUserRepository } from '@infrastructure/repositories'

export class UserService {
  constructor(private repo: IUserRepository = new HttpUserRepository()) {}
}
```

#### ✅ Import from Shared
```typescript
// application/validators/user-validators.ts
import { VALID_ROLES } from '@shared/constants'
import { isValidEmail } from '@shared/utils'
```

#### ❌ FORBIDDEN: Import from Presentation
```typescript
// ❌ NEVER DO THIS
import { UserManagementContainer } from '@presentation/containers'  // ❌
import { Button } from '@presentation/components/atoms'           // ❌
import { useUsers } from '@presentation/hooks'                    // ❌
```

---

### 3️⃣ From DOMAIN Layer

#### ✅ Only Internal Domain Imports
```typescript
// domain/use-cases/user/create-user-use-case.ts
import { User } from '@domain/entities'
import { UserRole } from '@domain/value-objects'
import { IUserRepository } from '@domain/repositories'
import { ValidationError } from '@domain/exceptions'
```

#### ❌ FORBIDDEN: ANY External Imports
```typescript
// ❌ NEVER DO THIS
import { UserService } from '@application/services'        // ❌
import { HttpUserRepository } from '@infrastructure/...'   // ❌
import { React, useState } from 'react'                    // ❌
import axios from 'axios'                                  // ❌
import { useQuery } from '@tanstack/react-query'          // ❌
```

---

### 4️⃣ From INFRASTRUCTURE Layer

#### ✅ Import from Domain
```typescript
// infrastructure/repositories/http-user-repository.ts
import { User } from '@domain/entities'
import { IUserRepository } from '@domain/repositories'
```

#### ✅ Import from Shared
```typescript
// infrastructure/http/client.ts
import { API_ENDPOINTS } from '@shared/constants'
```

#### ❌ FORBIDDEN: Import from Application or Presentation
```typescript
// ❌ NEVER DO THIS
import { UserService } from '@application/services'        // ❌
import { Button } from '@presentation/components'         // ❌
```

---

### 5️⃣ From SHARED Layer

#### ✅ Only Internal Shared Imports
```typescript
// shared/utils/cn.ts
import { mergeClasses } from 'clsx'
import { twMerge } from 'tailwind-merge'
```

#### ❌ FORBIDDEN: Import from any Layer
```typescript
// ❌ NEVER DO THIS
import { User } from '@domain/entities'                    // ❌
import { UserService } from '@application/services'        // ❌
```

---

## 📋 IMPORT PATTERNS BY FILE TYPE

### Pages (presentation/pages/*.tsx)

```typescript
// ✅ CORRECT
import { AuthService } from '@application/services'
import { User } from '@domain/entities'
import { AdminLayout } from '@presentation/layouts'
import { useForm } from '@presentation/hooks'
import { cn } from '@shared/utils'

// For API calls:
const authService = new AuthService(
  new HttpUserRepository(apiClient)
)

// ❌ WRONG
import { apiClient } from '@infrastructure/http/client'      // ❌ Direct infra
import { UserManagementContainer } from '@presentation/...'  // ❌ Use page directly
```

### Containers (presentation/containers/*.tsx)

```typescript
// ✅ CORRECT
import { UserService } from '@application/services'
import { HttpUserRepository } from '@infrastructure/repositories'
import { User } from '@domain/entities'
import { UserCard } from '@presentation/components/molecules'
import { useAsync } from '@presentation/hooks'

export function UserManagementContainer() {
  const userService = new UserService(new HttpUserRepository())
  // ...
}

// ❌ WRONG
import { apiClient } from '@infrastructure/http/client'  // ❌ Too low level
```

### Components (presentation/components/**/*.tsx)

```typescript
// ✅ CORRECT
import { User } from '@domain/entities'
import { cn } from '@shared/utils'
import type { Props } from '@shared/types'

interface UserCardProps {
  user: User  // ✅ Domain entity
  onClick: () => void
}

// ❌ WRONG
import { UserService } from '@application/services'     // ❌ Components are dumb
import { apiClient } from '@infrastructure/http/client'  // ❌ No HTTP in components
```

### Hooks (presentation/hooks/*.ts)

```typescript
// ✅ CORRECT
import { UserService } from '@application/services'
import { HttpUserRepository } from '@infrastructure/repositories'
import { useQuery } from '@tanstack/react-query'

export function useUsers() {
  const userService = new UserService(new HttpUserRepository())
  return useQuery({
    queryKey: ['users'],
    queryFn: () => userService.getUsers()
  })
}

// ❌ WRONG
import { apiClient } from '@infrastructure/http/client'  // ❌ Use service instead
```

### Services (application/services/*.ts)

```typescript
// ✅ CORRECT
import { User } from '@domain/entities'
import { IUserRepository } from '@domain/repositories'
import { CreateUserUseCase } from '@domain/use-cases'

export class UserService {
  constructor(private repo: IUserRepository) {}
  
  async createUser(input: CreateUserInput): Promise<User> {
    const useCase = new CreateUserUseCase(this.repo)
    return useCase.execute(input)
  }
}

// ❌ WRONG
import { Button } from '@presentation/components'        // ❌ Service ≠ UI
import { apiClient } from '@infrastructure/http/client'  // ❌ Use repo instead
```

### Repositories (infrastructure/repositories/*.ts)

```typescript
// ✅ CORRECT
import { User } from '@domain/entities'
import { IUserRepository } from '@domain/repositories'
import { apiClient } from '@infrastructure/http/client'

export class HttpUserRepository implements IUserRepository {
  async getUser(id: string): Promise<User> {
    const response = await apiClient.get(`/users/${id}`)
    return new User(response.data)
  }
}

// ❌ WRONG
import { UserService } from '@application/services'      // ❌ Repo is dependency
import { Button } from '@presentation/components'        // ❌ UI in infra
```

### Domain (domain/**/*.ts)

```typescript
// ✅ CORRECT - ONLY domain imports
import { User } from '@domain/entities'
import { UserRole } from '@domain/value-objects'
import { IUserRepository } from '@domain/repositories'
import { DomainException } from '@domain/exceptions'

export class CreateUserUseCase {
  constructor(private repo: IUserRepository) {}
  
  async execute(input: CreateUserInput): Promise<User> {
    if (!input.email) throw new DomainException('Invalid email')
    return this.repo.create(new User(input))
  }
}

// ❌ WRONG - NO external libraries!
import axios from 'axios'                                 // ❌
import { React } from 'react'                            // ❌
import { UserService } from '@application/services'      // ❌
```

---

## 🚫 ANTI-PATTERNS TO AVOID

### ❌ Anti-Pattern 1: Direct Infrastructure in Components
```typescript
// ❌ WRONG
function UserList() {
  const [users, setUsers] = useState([])
  
  useEffect(() => {
    apiClient.get('/users').then(res => setUsers(res.data))
  }, [])
  
  return <div>{users.map(u => <UserCard user={u} />)}</div>
}

// ✅ CORRECT
function UserList() {
  const { data: users } = useUsers()  // Hook handles HTTP
  return <div>{users?.map(u => <UserCard user={u} />)}</div>
}
```

### ❌ Anti-Pattern 2: Logic in Pages
```typescript
// ❌ WRONG
export function UsersPage() {
  const [users, setUsers] = useState([])
  const [loading, setLoading] = useState(false)
  
  const fetchUsers = async () => {
    setLoading(true)
    try {
      const res = await apiClient.get('/users')
      setUsers(res.data)
    } catch (error) {
      console.error(error)
    } finally {
      setLoading(false)
    }
  }
  
  useEffect(() => { fetchUsers() }, [])
  return <UserList users={users} loading={loading} />
}

// ✅ CORRECT
export function UsersPage() {
  return (
    <AdminLayout>
      <UserManagementContainer />
    </AdminLayout>
  )
}
```

### ❌ Anti-Pattern 3: Multiple Responsibility
```typescript
// ❌ WRONG - Container imports directly from infra
function UserManagementContainer() {
  const userService = new UserService()  // Depends on default constructor
  const staffService = new StaffService()
  const serviceService = new ServiceService()
  
  // Hard to test, hard to mock
}

// ✅ CORRECT - Dependencies injected
function UserManagementContainer() {
  const userService = new UserService(
    new HttpUserRepository(apiClient)
  )
  // Explicit dependencies, easy to test
}
```

### ❌ Anti-Pattern 4: Circular Dependencies
```typescript
// ❌ WRONG
// user-service.ts
import { Staff } from '@domain/entities'
import { StaffService } from '@application/services'

// staff-service.ts
import { User } from '@domain/entities'
import { UserService } from '@application/services'  // CIRCULAR!

// ✅ CORRECT
// Both import from domain only
import { User } from '@domain/entities'
import { Staff } from '@domain/entities'
```

---

## 📏 IMPORT ORGANIZATION BEST PRACTICES

### Sort imports by layer (external to internal)

```typescript
// 1. External libraries
import { useState, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import clsx from 'clsx'

// 2. Domain layer
import { User } from '@domain/entities'
import { IUserRepository } from '@domain/repositories'

// 3. Application layer
import { UserService } from '@application/services'
import { userValidator } from '@application/validators'

// 4. Infrastructure layer
import { HttpUserRepository } from '@infrastructure/repositories'

// 5. Presentation layer
import { useUsers } from '@presentation/hooks'
import { AdminLayout } from '@presentation/layouts'
import { UserCard } from '@presentation/components/molecules'

// 6. Shared
import { cn } from '@shared/utils'
import { COLORS } from '@shared/theme'

// 7. Type imports (if using TypeScript)
import type { UserDTO } from '@application/dtos'
```

---

## 🔍 VIOLATION DETECTION

### Find violations with grep:

```bash
# Find infrastructure imports in presentation
grep -r "from '@infrastructure" frontend/src/presentation/

# Find presentation imports in domain
grep -r "from '@presentation" frontend/src/domain/

# Find external libs in domain
grep -r "import.*from.*react" frontend/src/domain/
grep -r "import.*from.*axios" frontend/src/domain/
```

---

## ✅ VERIFICATION CHECKLIST

For each file, verify:

- [ ] **Domain files**: Only import from domain/ (no external libs)
- [ ] **Infrastructure files**: Only import from domain/ and shared/
- [ ] **Application files**: Only import from domain/, infrastructure/, and shared/
- [ ] **Presentation files**: Only import from application/, domain/, infrastructure/, presentation/, shared/
- [ ] **No circular imports**: A cannot import B if B imports A
- [ ] **No React in domain**: Zero React, axios, or external dependencies
- [ ] **Hooks in presentation/hooks**: Not in features/
- [ ] **Context in presentation/context**: Not in features/
- [ ] **Pages in presentation/pages**: Not in features/
- [ ] **Components in presentation/components**: Organized by atomic design

