import { DomainEvent } from './DomainEvent'

export class ShiftCreatedEvent extends DomainEvent {
  public readonly eventName = 'shift.created'
  public readonly aggregateId: string
  public readonly staffId: string
  public readonly startTime: Date
  public readonly endTime: Date

  constructor(aggregateId: string, staffId: string, startTime: Date, endTime: Date) {
    super()
    this.aggregateId = aggregateId
    this.staffId = staffId
    this.startTime = startTime
    this.endTime = endTime
  }

  public getPayload(): Record<string, unknown> {
    return {
      staffId: this.staffId,
      startTime: this.startTime.toISOString(),
      endTime: this.endTime.toISOString()
    }
  }
}

export class ShiftUpdatedEvent extends DomainEvent {
  public readonly eventName = 'shift.updated'
  public readonly aggregateId: string
  public readonly isAvailable: boolean

  constructor(aggregateId: string, isAvailable: boolean) {
    super()
    this.aggregateId = aggregateId
    this.isAvailable = isAvailable
  }

  public getPayload(): Record<string, unknown> {
    return {
      isAvailable: this.isAvailable
    }
  }
}

export class ShiftDeletedEvent extends DomainEvent {
  public readonly eventName = 'shift.deleted'
  public readonly aggregateId: string

  constructor(aggregateId: string) {
    super()
    this.aggregateId = aggregateId
  }

  public getPayload(): Record<string, unknown> {
    return {}
  }
}
