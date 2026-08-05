import { createUuid } from '../../shared/utils/uuid'
import { Email } from '../value-objects/Email'
import { UserId } from '../value-objects/UserId'
import { UserRole } from '../value-objects/UserRole'

export interface UserProps {
  id: UserId
  email: Email
  firstName: string | null
  lastName: string | null
  phone: string | null
  role: UserRole
  isActive: boolean
  createdAt: Date
}

export class User {
  private props: UserProps

  private constructor(props: UserProps) {
    this.props = props
  }

  static create(props: Omit<UserProps, 'id' | 'createdAt'>): User {
    return new User({
      ...props,
      id: UserId.create(createUuid()),
      createdAt: new Date()
    })
  }

  static fromPrimitives(props: {
    id: string
    email: string
    firstName: string | null
    lastName: string | null
    phone: string | null
    role: string
    isActive: boolean
    createdAt: string
  }): User {
    return new User({
      ...props,
      id: UserId.create(props.id),
      email: Email.create(props.email),
      role: UserRole.create(props.role),
      createdAt: new Date(props.createdAt)
    })
  }

  // Getters
  get id() {
    return this.props.id.getValue()
  }
  get email() {
    return this.props.email
  }
  get firstName() {
    return this.props.firstName
  }
  get lastName() {
    return this.props.lastName
  }
  get phone() {
    return this.props.phone
  }
  get role() {
    return this.props.role
  }
  get isActive() {
    return this.props.isActive
  }
  get fullName(): string {
    return [this.props.firstName, this.props.lastName].filter(Boolean).join(' ') || 'Sin Nombre'
  }

  // Business Logic
  deactivate(): void {
    this.props.isActive = false
  }

  activate(): void {
    this.props.isActive = true
  }

  toPrimitives() {
    return {
      ...this.props,
      id: this.props.id.getValue(),
      email: this.props.email.getValue(),
      role: this.props.role.getValue(),
      createdAt: this.props.createdAt.toISOString()
    }
  }
}
