import { EventBus } from './EventBus'
import { UserCreatedEvent } from '../../domain/events/UserEvents'
import { Email } from '../../domain/value-objects/Email'
import { UserRole } from '../../domain/value-objects/UserRole'
import { EventHandler } from './EventHandler'

class MockHandler implements EventHandler<UserCreatedEvent> {
  public handle = jest.fn().mockResolvedValue(undefined)
}

describe('EventBus', () => {
  let eventBus: EventBus

  beforeEach(() => {
    eventBus = EventBus.getInstance()
    eventBus.reset()
  })

  it('should successfully subscribe a handler and dispatch events to it', async () => {
    const handler = new MockHandler()
    eventBus.subscribe('user.created', handler)

    const event = new UserCreatedEvent(
      'user_123',
      Email.create('event@test.com'),
      UserRole.create('staff')
    )

    await eventBus.publish(event)

    expect(handler.handle).toHaveBeenCalledTimes(1)
    expect(handler.handle).toHaveBeenCalledWith(event)
  })

  it('should maintain an event history for audit logs', async () => {
    const event = new UserCreatedEvent(
      'user_123',
      Email.create('event@test.com'),
      UserRole.create('staff')
    )

    await eventBus.publish(event)

    const history = eventBus.getHistory()
    expect(history.length).toBe(1)
    expect(history[0].aggregateId).toBe('user_123')
    expect(history[0].eventName).toBe('user.created')
  })

  it('should allow unsubscribing from event notifications', async () => {
    const handler = new MockHandler()
    const unsubscribe = eventBus.subscribe('user.created', handler)

    const event = new UserCreatedEvent(
      'user_123',
      Email.create('event@test.com'),
      UserRole.create('staff')
    )

    unsubscribe()
    await eventBus.publish(event)

    expect(handler.handle).not.toHaveBeenCalled()
  })
})
