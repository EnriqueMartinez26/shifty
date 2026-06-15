import { UserCreatedEvent } from '../../domain/events/UserEvents'
import { EventHandler } from '../../shared/events/EventHandler'

export interface EmailService {
  sendWelcomeEmail(email: string): Promise<void>
}

export class SendWelcomeEmailOnUserCreated implements EventHandler<UserCreatedEvent> {
  private readonly emailService: EmailService

  constructor(emailService: EmailService) {
    this.emailService = emailService
  }

  public async handle(event: UserCreatedEvent): Promise<void> {
    const payload = event.getPayload()
    await this.emailService.sendWelcomeEmail(payload.email as string)
  }
}
export default SendWelcomeEmailOnUserCreated
