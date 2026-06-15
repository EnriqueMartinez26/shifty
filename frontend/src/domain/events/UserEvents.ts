import { DomainEvent } from './DomainEvent'
import { Email } from '../value-objects/Email'
import { UserRole } from '../value-objects/UserRole'

export class UserCreatedEvent extends DomainEvent {
  public readonly eventName = 'user.created'
  public readonly aggregateId: string
  public readonly email: Email
  public readonly role: UserRole

  constructor(aggregateId: string, email: Email, role: UserRole) {
    super()
    this.aggregateId = aggregateId
    this.email = email
    this.role = role
  }

  public getPayload(): Record<string, unknown> {
    return {
      email: this.email.getValue(),
      role: this.role.getValue()
    }
  }
}

export class UserUpdatedEvent extends DomainEvent {
  public readonly eventName = 'user.updated'
  public readonly aggregateId: string
  public readonly role?: UserRole

  constructor(aggregateId: string, role?: UserRole) {
    super()
    this.aggregateId = aggregateId
    this.role = role
  }

  public getPayload(): Record<string, unknown> {
    return {
      role: this.role?.getValue()
    }
  }
}

export class UserDeletedEvent extends DomainEvent {
  public readonly eventName = 'user.deleted'
  public readonly aggregateId: string

  constructor(aggregateId: string) {
    super()
    this.aggregateId = aggregateId
  }

  public getPayload(): Record<string, unknown> {
    return {}
  }
}
