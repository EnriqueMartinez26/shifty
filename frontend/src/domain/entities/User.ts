import { createUuid } from '../../shared/utils/uuid'
import { Email } from '../value-objects/Email'
import { UserId } from '../value-objects/UserId'
import { UserRole } from '../value-objects/UserRole'

/**
 * Forma de escritura del PATCH de usuarios. Todo campo es opcional y solo los
 * PRESENTES se mandan; `password` vacio tampoco viaja (editar sin tocar la
 * clave no la cambia). Mismo criterio que `ServiceWriteInput`.
 */
export interface UserWriteInput {
  firstName?: string
  lastName?: string
  phone?: string
  role?: string
  isActive?: boolean
  password?: string
}

interface UserProps {
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
      id: UserId.create(props.id),
      email: Email.create(props.email),
      firstName: props.firstName,
      lastName: props.lastName,
      phone: props.phone,
      role: UserRole.create(props.role),
      isActive: props.isActive,
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
      id: this.props.id.getValue(),
      email: this.props.email.getValue(),
      firstName: this.props.firstName,
      lastName: this.props.lastName,
      phone: this.props.phone,
      role: this.props.role.getValue(),
      isActive: this.props.isActive,
      createdAt: this.props.createdAt.toISOString()
    }
  }
}
