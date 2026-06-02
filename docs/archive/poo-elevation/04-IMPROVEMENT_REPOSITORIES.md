# 🏛️ IMPROVEMENT 4: REPOSITORY PATTERN HIERARCHY

## 🎯 Goal
Create abstract `BaseRepository` class to enforce Liskov Substitution Principle and guarantee contract compliance.

**POO Gain**: +6%  
**Effort**: 2-3 days  
**Priority**: 🔴 CRITICAL (depends on: Improvement 1)

---

## 📊 Current State vs Target

### ❌ CURRENT (Weak Polymorphism)
```typescript
// ❌ Inconsistent implementations
class HttpUserRepository implements IUserRepository {
  async getUsers() { return httpClient.get(...) }
  // Different error handling
  // Different caching
  // Not testable
}

// Can't easily swap for testing
```

### ✅ TARGET (Strong Polymorphism)
```typescript
// ✅ Abstract repository enforces contract
abstract class BaseRepository<T extends Entity> {
  protected abstract mapToDomain(dto: any): T
  protected abstract mapToPersistence(entity: T): any
  
  async findAll(): Promise<T[]> {
    // Consistent error handling
    // Consistent logging
    // Guaranteed contract
  }
}

// HTTP implementation
class HttpUserRepository extends BaseRepository<User> {
  constructor(private httpClient: HttpClient) { super() }
}

// Memory implementation (for testing)
class InMemoryUserRepository extends BaseRepository<User> {
  private storage = new Map<string, User>()
}

// Both are substitutable (Liskov principle)
const userService1 = new UserService(new HttpUserRepository(client))
const userService2 = new UserService(new InMemoryUserRepository())
```

---

## 🏗️ IMPLEMENTATION

### Step 1: Create BaseRepository

**File**: `frontend/src/core/repositories/BaseRepository.ts`

```typescript
/**
 * BaseRepository: Abstract base for all repositories
 *
 * Enforces:
 * - Consistent error handling
 * - Mapper pattern (DTO ↔ Domain)
 * - Type safety
 * - Liskov Substitution Principle (LSP)
 *
 * Subclasses must implement:
 * - mapToDomain: DTO → Entity
 * - mapToPersistence: Entity → DTO
 * - Abstract query methods
 */

export interface IRepository<T> {
  findAll(): Promise<T[]>
  findById(id: string): Promise<T | null>
  create(entity: T): Promise<void>
  update(entity: T): Promise<void>
  delete(id: string): Promise<void>
  findBy(criteria: any): Promise<T[]>
}

export abstract class BaseRepository<T> implements IRepository<T> {
  /**
   * Subclasses must provide mappers
   */
  protected abstract mapToDomain(dto: any): T
  protected abstract mapToPersistence(entity: T): any

  /**
   * Abstract query methods (subclass implements actual queries)
   */
  protected abstract performQuery(query: string, params?: any[]): Promise<any[]>
  protected abstract performQueryOne(
    query: string,
    params?: any[]
  ): Promise<any | null>
  protected abstract performMutation(query: string, params?: any[]): Promise<void>

  /**
   * Find all entities
   *
   * Subclasses override performQuery() for actual implementation
   */
  async findAll(): Promise<T[]> {
    try {
      const dtos = await this.performQuery('SELECT *')
      const entities = dtos.map(dto => this.mapToDomain(dto))
      this.logOperation('findAll', `Retrieved ${entities.length} entities`)
      return entities
    } catch (error) {
      this.logError('findAll', error)
      throw this.wrapRepositoryError(error)
    }
  }

  /**
   * Find single entity by ID
   */
  async findById(id: string): Promise<T | null> {
    try {
      this.validateId(id)
      const dto = await this.performQueryOne(
        'SELECT * WHERE id = ?',
        [id]
      )
      if (!dto) return null

      const entity = this.mapToDomain(dto)
      this.logOperation('findById', `Retrieved entity: ${id}`)
      return entity
    } catch (error) {
      this.logError('findById', error)
      throw this.wrapRepositoryError(error)
    }
  }

  /**
   * Create new entity
   */
  async create(entity: T): Promise<void> {
    try {
      const dto = this.mapToPersistence(entity)
      await this.performMutation('INSERT', [dto])
      this.logOperation('create', 'Entity created')
    } catch (error) {
      this.logError('create', error)
      throw this.wrapRepositoryError(error)
    }
  }

  /**
   * Update existing entity
   */
  async update(entity: T): Promise<void> {
    try {
      const dto = this.mapToPersistence(entity)
      await this.performMutation('UPDATE', [dto])
      this.logOperation('update', 'Entity updated')
    } catch (error) {
      this.logError('update', error)
      throw this.wrapRepositoryError(error)
    }
  }

  /**
   * Delete entity
   */
  async delete(id: string): Promise<void> {
    try {
      this.validateId(id)
      await this.performMutation('DELETE', [id])
      this.logOperation('delete', `Entity deleted: ${id}`)
    } catch (error) {
      this.logError('delete', error)
      throw this.wrapRepositoryError(error)
    }
  }

  /**
   * Find by criteria (dynamic queries)
   */
  async findBy(criteria: Record<string, any>): Promise<T[]> {
    try {
      const dtos = await this.performQuery('SELECT * WHERE ...', [criteria])
      const entities = dtos.map(dto => this.mapToDomain(dto))
      this.logOperation('findBy', `Retrieved ${entities.length} entities`)
      return entities
    } catch (error) {
      this.logError('findBy', error)
      throw this.wrapRepositoryError(error)
    }
  }

  // ========================================================================
  // PROTECTED HELPERS
  // ========================================================================

  protected validateId(id: string): void {
    if (!id || id.trim() === '') {
      throw new RepositoryError('ID cannot be empty')
    }
  }

  protected wrapRepositoryError(error: any): RepositoryError {
    if (error instanceof RepositoryError) {
      return error
    }

    if (error instanceof Error) {
      return new RepositoryError(
        `Database error: ${error.message}`,
        error
      )
    }

    return new RepositoryError('Unknown database error')
  }

  protected logOperation(method: string, message: string): void {
    console.log(`✅ [${this.constructor.name}] ${method}: ${message}`)
  }

  protected logError(method: string, error: any): void {
    console.error(`❌ [${this.constructor.name}] ${method}:`, error)
  }
}

export class RepositoryError extends Error {
  readonly isRepositoryError = true

  constructor(message: string, public cause?: any) {
    super(message)
    this.name = 'RepositoryError'
    Object.setPrototypeOf(this, RepositoryError.prototype)
  }
}
```

### Step 2: HTTP Repository Implementation

**File**: `frontend/src/infrastructure/repositories/http-user-repository.ts`

```typescript
/**
 * HttpUserRepository: HTTP implementation of User repository
 *
 * Extends BaseRepository to inherit consistent behavior.
 * Only implements storage-specific logic (HTTP calls).
 */

import { BaseRepository } from '@core/repositories/BaseRepository'
import { User } from '@domain/entities/User'
import { IUserRepository } from '@domain/repositories/IUserRepository'
import { HttpClient } from '@infrastructure/http/client'

export class HttpUserRepository
  extends BaseRepository<User>
  implements IUserRepository
{
  private endpoint = '/api/users'

  constructor(private httpClient: HttpClient) {
    super()
  }

  /**
   * Convert API response to domain entity
   */
  protected mapToDomain(dto: any): User {
    return User.hydrate({
      id: dto.id,
      email: dto.email,
      role: dto.role,
      name: dto.name,
      emailVerified: dto.email_verified,
      createdAt: dto.created_at,
      updatedAt: dto.updated_at
    })
  }

  /**
   * Convert domain entity to API request body
   */
  protected mapToPersistence(entity: User): any {
    const dto = entity.toDTO()
    return {
      id: dto.id,
      email: dto.email,
      role: dto.role,
      name: dto.name,
      email_verified: dto.emailVerified,
      created_at: dto.createdAt,
      updated_at: dto.updatedAt
    }
  }

  /**
   * HTTP GET (SELECT)
   */
  protected async performQuery(query: string, params?: any[]): Promise<any[]> {
    try {
      const response = await this.httpClient.get(this.endpoint)
      return response.data
    } catch (error) {
      throw this.handleHttpError(error)
    }
  }

  /**
   * HTTP GET by ID (SELECT WHERE ID = ?)
   */
  protected async performQueryOne(
    query: string,
    params?: any[]
  ): Promise<any | null> {
    try {
      const [id] = params || []
      const response = await this.httpClient.get(`${this.endpoint}/${id}`)
      return response.data
    } catch (error) {
      if (error.response?.status === 404) return null
      throw this.handleHttpError(error)
    }
  }

  /**
   * HTTP POST/PUT/DELETE (INSERT/UPDATE/DELETE)
   */
  protected async performMutation(query: string, params?: any[]): Promise<void> {
    try {
      const [data] = params || []

      if (query === 'INSERT') {
        await this.httpClient.post(this.endpoint, data)
      } else if (query === 'UPDATE') {
        await this.httpClient.put(`${this.endpoint}/${data.id}`, data)
      } else if (query === 'DELETE') {
        const [id] = params || []
        await this.httpClient.delete(`${this.endpoint}/${id}`)
      }
    } catch (error) {
      throw this.handleHttpError(error)
    }
  }

  /**
   * HTTP-specific error handling
   */
  private handleHttpError(error: any): Error {
    if (error.response?.status === 400) {
      return new ValidationError(error.response.data?.message || 'Validation failed')
    }

    if (error.response?.status === 404) {
      return new NotFoundError('Resource not found')
    }

    if (error.response?.status === 409) {
      return new ConflictError(error.response.data?.message || 'Conflict')
    }

    return new RepositoryError(error.message, error)
  }
}

class ValidationError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'ValidationError'
  }
}

class NotFoundError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'NotFoundError'
  }
}

class ConflictError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'ConflictError'
  }
}
```

### Step 3: In-Memory Repository (for Testing)

**File**: `frontend/src/infrastructure/repositories/in-memory-user-repository.ts`

```typescript
/**
 * InMemoryUserRepository: In-memory implementation for testing
 *
 * Key benefit: Can swap HttpUserRepository with InMemoryUserRepository
 * in tests without changing service code (Liskov Substitution Principle).
 */

import { BaseRepository } from '@core/repositories/BaseRepository'
import { User } from '@domain/entities/User'

export class InMemoryUserRepository extends BaseRepository<User> {
  private storage: Map<string, User> = new Map()

  /**
   * Mappers (no-op for in-memory)
   */
  protected mapToDomain(dto: any): User {
    return dto
  }

  protected mapToPersistence(entity: User): any {
    return entity
  }

  /**
   * In-memory query implementations
   */
  protected async performQuery(query: string, params?: any[]): Promise<any[]> {
    return Array.from(this.storage.values())
  }

  protected async performQueryOne(
    query: string,
    params?: any[]
  ): Promise<any | null> {
    const [id] = params || []
    return this.storage.get(id) || null
  }

  protected async performMutation(query: string, params?: any[]): Promise<void> {
    const [data] = params || []

    if (query === 'INSERT') {
      this.storage.set(data.id, data)
    } else if (query === 'UPDATE') {
      if (!this.storage.has(data.id)) throw new Error('Not found')
      this.storage.set(data.id, data)
    } else if (query === 'DELETE') {
      const [id] = params || []
      this.storage.delete(id)
    }
  }

  /**
   * Helper for testing
   */
  clear(): void {
    this.storage.clear()
  }

  seed(users: User[]): void {
    users.forEach(user => {
      this.storage.set(user.getId(), user)
    })
  }
}
```

### Step 4: Testing Repository Pattern

**File**: `frontend/src/__tests__/infrastructure/repositories/repository.test.ts`

```typescript
import { User } from '@domain/entities/User'
import { HttpUserRepository } from '@infrastructure/repositories/http-user-repository'
import { InMemoryUserRepository } from '@infrastructure/repositories/in-memory-user-repository'

/**
 * Abstract repository tests that work for ANY implementation
 *
 * This demonstrates Liskov Substitution Principle:
 * Same tests pass for both HTTP and In-Memory implementations.
 */
class RepositoryTestSuite {
  protected repository: any

  async testFindAll() {
    // Create test users
    const user1 = User.create({ email: 'user1@test.com', name: 'User 1', role: 'client' })
    const user2 = User.create({ email: 'user2@test.com', name: 'User 2', role: 'staff' })

    await this.repository.create(user1)
    await this.repository.create(user2)

    // Test findAll
    const users = await this.repository.findAll()
    expect(users).toHaveLength(2)
  }

  async testFindById() {
    const user = User.create({ email: 'test@test.com', name: 'Test', role: 'client' })
    await this.repository.create(user)

    const found = await this.repository.findById(user.getId())
    expect(found).toBeDefined()
    expect(found?.getId()).toBe(user.getId())
  }

  async testCreate() {
    const user = User.create({ email: 'new@test.com', name: 'New User', role: 'client' })
    await this.repository.create(user)

    const found = await this.repository.findById(user.getId())
    expect(found).toBeDefined()
  }

  async testUpdate() {
    const user = User.create({ email: 'test@test.com', name: 'Test', role: 'client' })
    await this.repository.create(user)

    user.promoteToAdmin()
    await this.repository.update(user)

    const found = await this.repository.findById(user.getId())
    expect(found?.getRole().isAdmin()).toBe(true)
  }

  async testDelete() {
    const user = User.create({ email: 'test@test.com', name: 'Test', role: 'client' })
    await this.repository.create(user)

    await this.repository.delete(user.getId())

    const found = await this.repository.findById(user.getId())
    expect(found).toBeNull()
  }
}

// Test In-Memory implementation
describe('InMemoryUserRepository', () => {
  const suite = new RepositoryTestSuite()

  beforeEach(() => {
    suite.repository = new InMemoryUserRepository()
  })

  it('should findAll', async () => suite.testFindAll())
  it('should findById', async () => suite.testFindById())
  it('should create', async () => suite.testCreate())
  it('should update', async () => suite.testUpdate())
  it('should delete', async () => suite.testDelete())
})

// Same tests for HTTP implementation
describe('HttpUserRepository', () => {
  const suite = new RepositoryTestSuite()
  const mockHttpClient = { /* mock */ }

  beforeEach(() => {
    suite.repository = new HttpUserRepository(mockHttpClient)
  })

  it('should findAll', async () => suite.testFindAll())
  it('should findById', async () => suite.testFindById())
  it('should create', async () => suite.testCreate())
  it('should update', async () => suite.testUpdate())
  it('should delete', async () => suite.testDelete())
})
```

---

## ✅ Checklist

- [ ] Create `BaseRepository.ts`
- [ ] Refactor `HttpUserRepository` to extend `BaseRepository`
- [ ] Refactor other HTTP repositories
- [ ] Create `InMemoryUserRepository` for testing
- [ ] Create shared repository tests
- [ ] Verify all repositories pass tests
- [ ] Test service substitution in tests

---

## 🎯 Success Criteria

✅ All repositories extend `BaseRepository`  
✅ Same tests pass for HTTP and In-Memory  
✅ Services use repositories through interfaces  
✅ Easy to swap for testing  
✅ Error handling consistent  
✅ Liskov Substitution Principle verified  

