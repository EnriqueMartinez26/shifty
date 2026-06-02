# 📢 IMPROVEMENT 7: EVENT-DRIVEN ARCHITECTURE

## 🎯 Goal
Implement Observer pattern with Event Bus to decouple services and enable reactive flows.

**POO Gain**: +4%  
**Effort**: 2-3 days  
**Priority**: 🟡 MEDIUM (depends on: Improvements 1-2)

---

## 🏗️ IMPLEMENTATION

### Step 1: Domain Events

**File**: `frontend/src/domain/events/DomainEvent.ts`

```typescript
/**
 * DomainEvent: Base class for all domain events
 *
 * Characteristics:
 * - Immutable data
 * - Timestamped
 * - Identifies what happened
 * - Contains only necessary data
 */

export abstract class DomainEvent {
  readonly occurredAt: Date
  abstract readonly eventName: string

  constructor() {
    this.occurredAt = new Date()
  }

  /**
   * Get event type for routing
   */
  getEventName(): string {
    return this.eventName
  }

  /**
   * Serialize for storage/transmission
   */
  abstract toJSON(): Record<string, any>
}

// ============================================================================
// USER DOMAIN EVENTS
// ============================================================================

export class UserCreatedEvent extends DomainEvent {
  readonly eventName = 'user.created'

  constructor(
    public readonly userId: string,
    public readonly email: string,
    public readonly name: string
  ) {
    super()
  }

  toJSON() {
    return {
      eventName: this.eventName,
      userId: this.userId,
      email: this.email,
      name: this.name,
      occurredAt: this.occurredAt.toISOString()
    }
  }
}

export class UserDeletedEvent extends DomainEvent {
  readonly eventName = 'user.deleted'

  constructor(public readonly userId: string) {
    super()
  }

  toJSON() {
    return {
      eventName: this.eventName,
      userId: this.userId,
      occurredAt: this.occurredAt.toISOString()
    }
  }
}

export class UserEmailChangedEvent extends DomainEvent {
  readonly eventName = 'user.email.changed'

  constructor(
    public readonly userId: string,
    public readonly oldEmail: string,
    public readonly newEmail: string
  ) {
    super()
  }

  toJSON() {
    return {
      eventName: this.eventName,
      userId: this.userId,
      oldEmail: this.oldEmail,
      newEmail: this.newEmail,
      occurredAt: this.occurredAt.toISOString()
    }
  }
}

// ============================================================================
// APPOINTMENT DOMAIN EVENTS
// ============================================================================

export class AppointmentCreatedEvent extends DomainEvent {
  readonly eventName = 'appointment.created'

  constructor(
    public readonly appointmentId: string,
    public readonly userId: string,
    public readonly staffId: string,
    public readonly scheduledAt: Date
  ) {
    super()
  }

  toJSON() {
    return {
      eventName: this.eventName,
      appointmentId: this.appointmentId,
      userId: this.userId,
      staffId: this.staffId,
      scheduledAt: this.scheduledAt.toISOString(),
      occurredAt: this.occurredAt.toISOString()
    }
  }
}

export class AppointmentCancelledEvent extends DomainEvent {
  readonly eventName = 'appointment.cancelled'

  constructor(
    public readonly appointmentId: string,
    public readonly reason?: string
  ) {
    super()
  }

  toJSON() {
    return {
      eventName: this.eventName,
      appointmentId: this.appointmentId,
      reason: this.reason,
      occurredAt: this.occurredAt.toISOString()
    }
  }
}

// ============================================================================
// BOOKING DOMAIN EVENTS
// ============================================================================

export class BookingCompletedEvent extends DomainEvent {
  readonly eventName = 'booking.completed'

  constructor(
    public readonly bookingId: string,
    public readonly amount: number,
    public readonly currency: string
  ) {
    super()
  }

  toJSON() {
    return {
      eventName: this.eventName,
      bookingId: this.bookingId,
      amount: this.amount,
      currency: this.currency,
      occurredAt: this.occurredAt.toISOString()
    }
  }
}
```

### Step 2: Event Handlers (Observer Pattern)

**File**: `frontend/src/domain/events/EventHandler.ts`

```typescript
/**
 * EventHandler: Observer Pattern Implementation
 *
 * Each event can have multiple handlers.
 * Handlers don't know about each other (loose coupling).
 */

import { DomainEvent } from './DomainEvent'

export interface EventHandler<T extends DomainEvent = DomainEvent> {
  handle(event: T): Promise<void>
}

// ============================================================================
// USER EVENT HANDLERS
// ============================================================================

/**
 * Send welcome email when user is created
 */
export class SendWelcomeEmailHandler implements EventHandler<UserCreatedEvent> {
  constructor(private emailService: any) {}

  async handle(event: UserCreatedEvent): Promise<void> {
    console.log(`📧 Sending welcome email to ${event.email}`)
    // await this.emailService.sendWelcomeEmail(event.email, event.name)
  }
}

/**
 * Notify admins when user is created
 */
export class NotifyAdminsHandler implements EventHandler<UserCreatedEvent> {
  constructor(private notificationService: any) {}

  async handle(event: UserCreatedEvent): Promise<void> {
    console.log(`🔔 Notifying admins about new user: ${event.name}`)
    // await this.notificationService.notifyAdmins(...)
  }
}

/**
 * Update user index when email changes
 */
export class UpdateUserIndexHandler implements EventHandler<UserEmailChangedEvent> {
  constructor(private searchService: any) {}

  async handle(event: UserEmailChangedEvent): Promise<void> {
    console.log(`🔍 Updating search index for user ${event.userId}`)
    // await this.searchService.updateUser(event.userId, { email: event.newEmail })
  }
}

// ============================================================================
// APPOINTMENT EVENT HANDLERS
// ============================================================================

/**
 * Send appointment confirmation email
 */
export class SendAppointmentConfirmationHandler
  implements EventHandler<AppointmentCreatedEvent>
{
  constructor(private emailService: any) {}

  async handle(event: AppointmentCreatedEvent): Promise<void> {
    console.log(`📧 Sending appointment confirmation for ${event.appointmentId}`)
    // await this.emailService.sendAppointmentConfirmation(...)
  }
}

/**
 * Add to calendar when appointment created
 */
export class AddToCalendarHandler implements EventHandler<AppointmentCreatedEvent> {
  constructor(private calendarService: any) {}

  async handle(event: AppointmentCreatedEvent): Promise<void> {
    console.log(`📅 Adding appointment ${event.appointmentId} to calendar`)
    // await this.calendarService.addEvent(...)
  }
}

/**
 * Send cancellation notification
 */
export class SendCancellationNotificationHandler
  implements EventHandler<AppointmentCancelledEvent>
{
  constructor(private notificationService: any) {}

  async handle(event: AppointmentCancelledEvent): Promise<void> {
    console.log(
      `🚫 Sending cancellation notice for appointment ${event.appointmentId}`
    )
    // await this.notificationService.notifyAppointmentCancelled(...)
  }
}

// ============================================================================
// BOOKING EVENT HANDLERS
// ============================================================================

/**
 * Send receipt when booking completed
 */
export class SendReceiptHandler implements EventHandler<BookingCompletedEvent> {
  constructor(private emailService: any) {}

  async handle(event: BookingCompletedEvent): Promise<void> {
    console.log(`🧾 Sending receipt for booking ${event.bookingId}`)
    // await this.emailService.sendReceipt(...)
  }
}

/**
 * Update analytics when booking completed
 */
export class UpdateAnalyticsHandler implements EventHandler<BookingCompletedEvent> {
  constructor(private analyticsService: any) {}

  async handle(event: BookingCompletedEvent): Promise<void> {
    console.log(`📊 Recording booking amount: ${event.amount} ${event.currency}`)
    // await this.analyticsService.recordBooking(event.amount)
  }
}
```

### Step 3: Event Bus (Coordinator)

**File**: `frontend/src/core/events/EventBus.ts`

```typescript
/**
 * EventBus: Central event coordinator
 *
 * Implements Observer pattern:
 * - Services publish events
 * - Multiple handlers subscribe to events
 * - Loose coupling between components
 */

import { DomainEvent } from '@domain/events/DomainEvent'
import { EventHandler } from '@domain/events/EventHandler'

export class EventBus {
  private static instance: EventBus
  private handlers: Map<string, EventHandler<any>[]> = new Map()
  private eventHistory: DomainEvent[] = []

  private constructor() {}

  static getInstance(): EventBus {
    if (!EventBus.instance) {
      EventBus.instance = new EventBus()
    }
    return EventBus.instance
  }

  /**
   * Subscribe handler to event
   *
   * @param eventName - Event identifier
   * @param handler - Handler to execute on event
   *
   * Example:
   * eventBus.subscribe('user.created', new SendWelcomeEmailHandler(emailService))
   */
  subscribe<T extends DomainEvent>(
    eventName: string,
    handler: EventHandler<T>
  ): void {
    if (!this.handlers.has(eventName)) {
      this.handlers.set(eventName, [])
    }

    this.handlers.get(eventName)!.push(handler)
    console.log(
      `✅ Subscribed ${handler.constructor.name} to ${eventName}`
    )
  }

  /**
   * Subscribe multiple handlers
   */
  subscribeMultiple<T extends DomainEvent>(
    eventName: string,
    ...handlers: EventHandler<T>[]
  ): void {
    handlers.forEach(h => this.subscribe(eventName, h))
  }

  /**
   * Publish event to all subscribers
   *
   * @param event - Domain event to publish
   * @throws If any handler throws
   *
   * Example:
   * await eventBus.publish(new UserCreatedEvent(userId, email, name))
   */
  async publish<T extends DomainEvent>(event: T): Promise<void> {
    const eventName = event.getEventName()
    const handlers = this.handlers.get(eventName) || []

    console.log(
      `📢 Publishing event: ${eventName} (${handlers.length} subscribers)`
    )

    // Store event in history
    this.eventHistory.push(event)

    // Execute all handlers sequentially
    for (const handler of handlers) {
      try {
        await handler.handle(event)
      } catch (error) {
        console.error(
          `❌ Error in ${handler.constructor.name}: ${error}`
        )
        // Continue with other handlers (don't break on error)
      }
    }
  }

  /**
   * Publish event asynchronously (fire and forget)
   * Handlers execute in background, errors don't propagate
   */
  publishAsync<T extends DomainEvent>(event: T): void {
    setImmediate(() => {
      this.publish(event).catch(error => {
        console.error('Async event error:', error)
      })
    })
  }

  /**
   * Get event history (for debugging)
   */
  getEventHistory(): DomainEvent[] {
    return [...this.eventHistory]
  }

  /**
   * Clear subscriptions and history (for testing)
   */
  reset(): void {
    this.handlers.clear()
    this.eventHistory = []
  }

  /**
   * Get subscriber count for event (for debugging)
   */
  getSubscriberCount(eventName: string): number {
    return this.handlers.get(eventName)?.length || 0
  }
}
```

### Step 4: Integration in DI Container

**File**: `frontend/src/core/di/dependencies.ts` (Update)

```typescript
import { EventBus } from '@core/events/EventBus'
import {
  SendWelcomeEmailHandler,
  NotifyAdminsHandler,
  UpdateUserIndexHandler,
  SendAppointmentConfirmationHandler
} from '@domain/events/EventHandler'

export function registerDependencies(): void {
  const container = ServiceContainer.getInstance()

  // ... existing registrations ...

  // ========================================================================
  // EVENT BUS & HANDLERS
  // ========================================================================

  // Create singleton event bus
  const eventBus = EventBus.getInstance()

  // Register event handlers
  eventBus.subscribeMultiple(
    'user.created',
    new SendWelcomeEmailHandler(container.get('emailService')),
    new NotifyAdminsHandler(container.get('notificationService'))
  )

  eventBus.subscribe(
    'user.email.changed',
    new UpdateUserIndexHandler(container.get('searchService'))
  )

  eventBus.subscribeMultiple(
    'appointment.created',
    new SendAppointmentConfirmationHandler(container.get('emailService')),
    new AddToCalendarHandler(container.get('calendarService'))
  )

  container.register('eventBus', () => eventBus, { singleton: true })
}
```

### Step 5: Services Publish Events

**File**: `frontend/src/application/services/user-service.ts` (Update)

```typescript
import { UserCreatedEvent } from '@domain/events/DomainEvent'
import { EventBus } from '@core/events/EventBus'

class UserService extends BaseService<User, CreateUserInput, UpdateUserInput> {
  constructor(
    protected repository: IUserRepository,
    private eventBus: EventBus
  ) {
    super()
  }

  async create(input: CreateUserInput): Promise<User> {
    // Step 1: Create entity
    const user = User.create(input)

    // Step 2: Validate
    await this.validateEntity(user)

    // Step 3: Persist
    await this.repository.create(user)

    // Step 4: Publish event (decouple from consequences)
    await this.eventBus.publish(
      new UserCreatedEvent(
        user.getId(),
        user.getEmail().getValue(),
        user.getName()
      )
    )

    return user
  }

  async changeEmail(userId: string, newEmail: string): Promise<User> {
    const user = await this.repository.findById(userId)
    if (!user) throw new NotFoundError('User not found')

    const oldEmail = user.getEmail().getValue()
    user.changeEmail(newEmail)

    await this.repository.update(user)

    // Publish event
    await this.eventBus.publish(
      new UserEmailChangedEvent(userId, oldEmail, newEmail)
    )

    return user
  }
}

export { UserService }
```

### Step 6: Testing Event Bus

**File**: `frontend/src/__tests__/core/events/EventBus.test.ts`

```typescript
import { EventBus } from '@core/events/EventBus'
import { UserCreatedEvent } from '@domain/events/DomainEvent'
import { EventHandler } from '@domain/events/EventHandler'

describe('EventBus - Observer Pattern', () => {
  let eventBus: EventBus

  beforeEach(() => {
    EventBus.getInstance().reset()
    eventBus = EventBus.getInstance()
  })

  it('should subscribe and publish to handlers', async () => {
    const mockHandler: EventHandler = {
      handle: jest.fn()
    }

    eventBus.subscribe('user.created', mockHandler)

    const event = new UserCreatedEvent('1', 'test@example.com', 'Test')
    await eventBus.publish(event)

    expect(mockHandler.handle).toHaveBeenCalledWith(event)
  })

  it('should execute multiple handlers', async () => {
    const handler1: EventHandler = { handle: jest.fn() }
    const handler2: EventHandler = { handle: jest.fn() }

    eventBus.subscribe('user.created', handler1)
    eventBus.subscribe('user.created', handler2)

    const event = new UserCreatedEvent('1', 'test@example.com', 'Test')
    await eventBus.publish(event)

    expect(handler1.handle).toHaveBeenCalled()
    expect(handler2.handle).toHaveBeenCalled()
  })

  it('should not break if handler errors', async () => {
    const errorHandler: EventHandler = {
      handle: jest.fn().mockRejectedValue(new Error('Handler error'))
    }

    const okHandler: EventHandler = {
      handle: jest.fn()
    }

    eventBus.subscribe('user.created', errorHandler)
    eventBus.subscribe('user.created', okHandler)

    const event = new UserCreatedEvent('1', 'test@example.com', 'Test')

    // Should not throw
    await expect(eventBus.publish(event)).resolves.toBeUndefined()

    // Second handler should still be called
    expect(okHandler.handle).toHaveBeenCalled()
  })

  it('should maintain event history', async () => {
    const event = new UserCreatedEvent('1', 'test@example.com', 'Test')
    await eventBus.publish(event)

    const history = eventBus.getEventHistory()
    expect(history).toHaveLength(1)
    expect(history[0]).toBe(event)
  })
})
```

---

## 📊 Event Flow Example

```typescript
// User creates account
const user = await userService.create({ email: 'user@example.com', ... })

// Service publishes event
eventBus.publish(new UserCreatedEvent(userId, email, name))

// Multiple handlers execute:
// 1. SendWelcomeEmailHandler → sends email
// 2. NotifyAdminsHandler → notifies admins
// 3. UpdateSearchIndexHandler → updates search

// All completely decoupled from UserService
```

---

## ✅ Checklist

- [ ] Create domain event classes
- [ ] Create event handler interfaces
- [ ] Create event handlers for each event
- [ ] Create EventBus coordinator
- [ ] Register event bus in DI container
- [ ] Register event handlers
- [ ] Update services to publish events
- [ ] Create comprehensive event tests
- [ ] Add event monitoring/logging

---

## 🎯 Success Criteria

✅ Services publish domain events  
✅ Multiple handlers can subscribe to same event  
✅ No direct coupling between services  
✅ Handlers can be added without modifying services  
✅ Event history available for debugging  
✅ Error in one handler doesn't break others  

