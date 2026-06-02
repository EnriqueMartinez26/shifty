# 💎 IMPROVEMENT 3: VALUE OBJECT ENFORCEMENT

## 🎯 Goal
Enforce encapsulation in domain entities and value objects using proper classes with private fields.

**POO Gain**: +8%  
**Effort**: 3-4 days  
**Priority**: 🔴 CRITICAL (depends on: Improvement 2)

---

## 📊 Current State vs Target

### ❌ CURRENT (Weak Encapsulation)
```typescript
// ❌ User as plain interface (no validation)
interface User {
  id: string
  email: string
  role: 'admin' | 'staff' | 'client'
}

// Anyone can create invalid users
const badUser = {
  id: '',
  email: 'not-an-email',
  role: 'superadmin' as any  // Doesn't exist!
}

// No behavior, just data containers
```

### ✅ TARGET (Strong Encapsulation)
```typescript
// ✅ User as encapsulated class
class User {
  private id: string
  private email: Email  // Value Object
  private role: UserRole  // Value Object
  
  private constructor(props: { id: string; email: Email; role: UserRole }) {
    this.id = props.id
    this.email = props.email
    this.role = props.role
  }
  
  static create(props: { email: string; role: string }): User {
    // Validation + construction
    const email = Email.create(props.email)
    const role = UserRole.create(props.role)
    return new User({ id: generateId(), email, role })
  }
  
  // Getters enforce encapsulation
  getId(): string { return this.id }
  getEmail(): Email { return this.email }
  getRole(): UserRole { return this.role }
  
  // Behavior (domain logic)
  canAccessAdminPanel(): boolean {
    return this.role.isAdmin()
  }
}

// Email as Value Object
class Email {
  private value: string
  
  private constructor(value: string) {
    this.validate(value)
    this.value = value.toLowerCase()
  }
  
  static create(value: string): Email {
    return new Email(value)
  }
  
  private validate(value: string): void {
    const regex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
    if (!regex.test(value)) {
      throw new ValidationError(`Invalid email: ${value}`)
    }
  }
  
  getValue(): string { return this.value }
  
  equals(other: Email): boolean {
    return this.value === other.getValue()
  }
}
```

---

## 🏗️ IMPLEMENTATION

### Step 1: Create Email Value Object

**File**: `frontend/src/domain/value-objects/Email.ts`

```typescript
/**
 * Email: Value Object for email addresses
 *
 * Characteristics of value objects:
 * - Immutable (value never changes)
 * - Interchangeable (two emails with same value are equal)
 * - No identity (not compared by ID)
 * - Validates on construction (fail fast)
 */

export class Email {
  private readonly value: string

  private constructor(value: string) {
    this.validate(value)
    this.value = value.toLowerCase().trim()
  }

  /**
   * Factory method for creating Email
   * Throws ValidationError if email invalid
   */
  static create(value: string): Email {
    return new Email(value)
  }

  /**
   * Restore from persistence
   */
  static fromString(value: string): Email {
    // Skip validation on restore (already validated)
    const email = Object.create(Email.prototype)
    email.value = value
    return email
  }

  /**
   * Validate email format
   */
  private validate(value: string): void {
    if (!value || value.trim() === '') {
      throw new EmailValidationError('Email cannot be empty')
    }

    // RFC 5322 simplified regex
    const regex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
    if (!regex.test(value)) {
      throw new EmailValidationError(`Invalid email format: ${value}`)
    }

    // Additional checks
    if (value.length > 254) {
      throw new EmailValidationError('Email is too long (max 254 characters)')
    }
  }

  /**
   * Get email string value
   */
  getValue(): string {
    return this.value
  }

  /**
   * Value object equality (by value, not by reference)
   */
  equals(other: Email): boolean {
    if (!(other instanceof Email)) return false
    return this.value === other.value
  }

  /**
   * Check if email is from specific domain
   */
  isDomain(domain: string): boolean {
    return this.value.endsWith(`@${domain}`)
  }

  /**
   * Get domain from email
   */
  getDomain(): string {
    return this.value.split('@')[1]
  }

  /**
   * Get local part (before @)
   */
  getLocalPart(): string {
    return this.value.split('@')[0]
  }

  /**
   * Serialize for JSON
   */
  toJSON(): string {
    return this.value
  }

  /**
   * String representation
   */
  toString(): string {
    return this.value
  }
}

export class EmailValidationError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'EmailValidationError'
    Object.setPrototypeOf(this, EmailValidationError.prototype)
  }
}
```

### Step 2: Create UserRole Value Object

**File**: `frontend/src/domain/value-objects/UserRole.ts`

```typescript
/**
 * UserRole: Value Object for user roles
 *
 * Ensures type safety and prevents invalid roles.
 */

export type RoleType = 'admin' | 'staff' | 'client'

export class UserRole {
  private readonly value: RoleType

  private constructor(value: RoleType) {
    this.value = value
  }

  /**
   * Factory method
   */
  static create(value: string): UserRole {
    const normalized = value.toLowerCase() as RoleType

    const validRoles: RoleType[] = ['admin', 'staff', 'client']
    if (!validRoles.includes(normalized)) {
      throw new RoleValidationError(
        `Invalid role: ${value}. Must be one of: ${validRoles.join(', ')}`
      )
    }

    return new UserRole(normalized)
  }

  /**
   * Predefined roles
   */
  static admin(): UserRole {
    return new UserRole('admin')
  }

  static staff(): UserRole {
    return new UserRole('staff')
  }

  static client(): UserRole {
    return new UserRole('client')
  }

  /**
   * Get role value
   */
  getValue(): RoleType {
    return this.value
  }

  /**
   * Permission checks
   */
  isAdmin(): boolean {
    return this.value === 'admin'
  }

  isStaff(): boolean {
    return this.value === 'staff'
  }

  isClient(): boolean {
    return this.value === 'client'
  }

  /**
   * Check if role has permission
   */
  hasPermission(permission: string): boolean {
    const permissions: Record<RoleType, Set<string>> = {
      admin: new Set([
        'view_users',
        'edit_users',
        'delete_users',
        'view_reports',
        'manage_staff'
      ]),
      staff: new Set(['view_appointments', 'manage_services']),
      client: new Set(['view_appointments', 'book_appointment'])
    }

    return permissions[this.value].has(permission)
  }

  /**
   * Value object equality
   */
  equals(other: UserRole): boolean {
    if (!(other instanceof UserRole)) return false
    return this.value === other.value
  }

  /**
   * Serialize
   */
  toJSON(): string {
    return this.value
  }

  toString(): string {
    return this.value
  }
}

export class RoleValidationError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'RoleValidationError'
    Object.setPrototypeOf(this, RoleValidationError.prototype)
  }
}
```

### Step 3: Create User Aggregate

**File**: `frontend/src/domain/entities/User.ts`

```typescript
/**
 * User: Domain Entity (Aggregate Root)
 *
 * Domain-driven design aggregate:
 * - Encapsulates user data
 * - Uses value objects (Email, UserRole)
 * - Contains business logic
 * - No getters/setters for fields (only through methods)
 */

import { Email } from '@domain/value-objects/Email'
import { UserRole } from '@domain/value-objects/UserRole'
import { generateId } from '@shared/utils/id-generator'

export interface UserProps {
  id: string
  email: Email
  role: UserRole
  name: string
  emailVerified: boolean
  createdAt: Date
  updatedAt: Date
}

export class User {
  private id: string
  private email: Email
  private role: UserRole
  private name: string
  private emailVerified: boolean
  private createdAt: Date
  private updatedAt: Date

  /**
   * Private constructor enforces factory pattern
   */
  private constructor(props: UserProps) {
    this.id = props.id
    this.email = props.email
    this.role = props.role
    this.name = props.name
    this.emailVerified = props.emailVerified
    this.createdAt = props.createdAt
    this.updatedAt = props.updatedAt
  }

  /**
   * Factory method: Create new user
   */
  static create(input: {
    email: string
    name: string
    role: string
  }): User {
    return new User({
      id: generateId(),
      email: Email.create(input.email),
      role: UserRole.create(input.role),
      name: input.name,
      emailVerified: false,
      createdAt: new Date(),
      updatedAt: new Date()
    })
  }

  /**
   * Factory method: Restore from persistence
   */
  static hydrate(dto: any): User {
    return new User({
      id: dto.id,
      email: Email.create(dto.email),
      role: UserRole.create(dto.role),
      name: dto.name,
      emailVerified: dto.emailVerified,
      createdAt: new Date(dto.createdAt),
      updatedAt: new Date(dto.updatedAt)
    })
  }

  // ========================================================================
  // GETTERS (Encapsulation)
  // ========================================================================

  getId(): string {
    return this.id
  }

  getEmail(): Email {
    return this.email
  }

  getRole(): UserRole {
    return this.role
  }

  getName(): string {
    return this.name
  }

  isEmailVerified(): boolean {
    return this.emailVerified
  }

  getCreatedAt(): Date {
    return this.createdAt
  }

  getUpdatedAt(): Date {
    return this.updatedAt
  }

  // ========================================================================
  // BUSINESS LOGIC (Domain methods)
  // ========================================================================

  /**
   * Change email (business logic)
   */
  changeEmail(newEmail: string): void {
    const email = Email.create(newEmail)

    if (email.equals(this.email)) {
      throw new Error('New email cannot be the same as current email')
    }

    this.email = email
    this.emailVerified = false  // Must verify new email
    this.updatedAt = new Date()
  }

  /**
   * Promote to admin
   */
  promoteToAdmin(): void {
    if (this.role.isAdmin()) {
      throw new Error('User is already an admin')
    }

    this.role = UserRole.admin()
    this.updatedAt = new Date()
  }

  /**
   * Demote from admin
   */
  demoteFromAdmin(): void {
    if (!this.role.isAdmin()) {
      throw new Error('User is not an admin')
    }

    this.role = UserRole.client()
    this.updatedAt = new Date()
  }

  /**
   * Check if user can access admin panel
   */
  canAccessAdminPanel(): boolean {
    return this.role.isAdmin()
  }

  /**
   * Verify email
   */
  verifyEmail(): void {
    this.emailVerified = true
    this.updatedAt = new Date()
  }

  /**
   * Mark email as unverified (when changed)
   */
  unverifyEmail(): void {
    this.emailVerified = false
    this.updatedAt = new Date()
  }

  // ========================================================================
  // VALUE OBJECT METHODS
  // ========================================================================

  /**
   * Entity equality (by ID)
   */
  equals(other: User): boolean {
    if (!(other instanceof User)) return false
    return this.id === other.id
  }

  /**
   * Serialize for API/storage
   */
  toDTO(): {
    id: string
    email: string
    role: string
    name: string
    emailVerified: boolean
    createdAt: string
    updatedAt: string
  } {
    return {
      id: this.id,
      email: this.email.getValue(),
      role: this.role.getValue(),
      name: this.name,
      emailVerified: this.emailVerified,
      createdAt: this.createdAt.toISOString(),
      updatedAt: this.updatedAt.toISOString()
    }
  }
}
```

---

## 🧪 Testing Value Objects

**File**: `frontend/src/__tests__/domain/value-objects/Email.test.ts`

```typescript
import { Email, EmailValidationError } from '@domain/value-objects/Email'

describe('Email - Value Object', () => {
  describe('Creation', () => {
    it('should create valid email', () => {
      const email = Email.create('test@example.com')
      expect(email.getValue()).toBe('test@example.com')
    })

    it('should lowercase email', () => {
      const email = Email.create('Test@EXAMPLE.COM')
      expect(email.getValue()).toBe('test@example.com')
    })

    it('should reject invalid email', () => {
      expect(() => Email.create('invalid')).toThrow(EmailValidationError)
      expect(() => Email.create('test@')).toThrow(EmailValidationError)
      expect(() => Email.create('@example.com')).toThrow(EmailValidationError)
    })

    it('should reject empty email', () => {
      expect(() => Email.create('')).toThrow(EmailValidationError)
    })
  })

  describe('Equality', () => {
    it('should be equal by value', () => {
      const email1 = Email.create('test@example.com')
      const email2 = Email.create('test@example.com')

      expect(email1.equals(email2)).toBe(true)
    })

    it('should not be equal by reference', () => {
      const email1 = Email.create('test@example.com')
      const email2 = Email.create('other@example.com')

      expect(email1.equals(email2)).toBe(false)
    })
  })

  describe('Domain extraction', () => {
    it('should get domain', () => {
      const email = Email.create('user@example.com')
      expect(email.getDomain()).toBe('example.com')
    })

    it('should get local part', () => {
      const email = Email.create('user@example.com')
      expect(email.getLocalPart()).toBe('user')
    })
  })
})
```

---

## ✅ Checklist

- [ ] Create Email value object
- [ ] Create UserRole value object
- [ ] Create Money value object
- [ ] Create Duration value object
- [ ] Refactor User entity to use value objects
- [ ] Refactor Staff entity to use value objects
- [ ] Refactor Service entity to use value objects
- [ ] Refactor Appointment entity to use value objects
- [ ] Create comprehensive value object tests
- [ ] Update DTOs to work with value objects

---

## 🎯 Success Criteria

✅ All entities use value objects  
✅ No direct field access (only through getters/methods)  
✅ Value objects enforce validation  
✅ Immutability enforced (readonly fields)  
✅ 100% of domain logic testable  
✅ Invalid states impossible to create  

