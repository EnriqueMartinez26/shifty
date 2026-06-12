import { User } from '../../entities/User'
import type { IUserRepository } from '../../repositories/IUserRepository'
import { Email } from '../../value-objects/Email'
import { UserRole } from '../../value-objects/UserRole'

export interface CreateUserInput {
  email: string
  password: string
  firstName?: string
  lastName?: string
  phone?: string
  role: string
}

export class CreateUserUseCase {
  private userRepository: IUserRepository

  constructor(userRepository: IUserRepository) {
    this.userRepository = userRepository
  }

  async execute(input: CreateUserInput): Promise<User> {
    const emailVo = Email.create(input.email)
    const roleVo = UserRole.create(input.role)

    const user = User.create({
      email: emailVo,
      role: roleVo,
      firstName: input.firstName ?? null,
      lastName: input.lastName ?? null,
      phone: input.phone ?? null,
      isActive: true
    })

    return await this.userRepository.create(user, input.password)
  }
}
