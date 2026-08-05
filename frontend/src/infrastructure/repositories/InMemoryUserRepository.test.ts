import { InMemoryUserRepository } from './InMemoryUserRepository'
import { User } from '../../domain/entities/User'
import { Email } from '../../domain/value-objects/Email'
import { UserRole } from '../../domain/value-objects/UserRole'
import { NotFoundError } from '../../shared/errors/NotFoundError'

describe('InMemoryUserRepository', () => {
  let repository: InMemoryUserRepository

  const createMockUser = (id: string, emailStr = 'test@shifty.com') => {
    return User.fromPrimitives({
      id,
      email: emailStr,
      firstName: 'John',
      lastName: 'Doe',
      phone: '123456',
      role: 'admin',
      isActive: true,
      createdAt: new Date().toISOString()
    })
  }

  beforeEach(() => {
    repository = new InMemoryUserRepository()
  })

  it('should store and find users by ID', async () => {
    const user = createMockUser('user_1')
    await repository.create(user)

    const found = await repository.findById('user_1')
    expect(found).toBeDefined()
    expect(found?.id).toBe('user_1')
    expect(found?.toPrimitives().email).toBe('test@shifty.com')
  })

  it('should find user by Email Value Object', async () => {
    const user = createMockUser('user_1', 'unique@shifty.com')
    await repository.create(user)

    const emailVO = Email.create('unique@shifty.com')
    const found = await repository.findByEmail(emailVO)

    expect(found).not.toBeNull()
    expect(found?.id).toBe('user_1')
  })

  it('should find users by UserRole Value Object', async () => {
    const user1 = createMockUser('user_1')
    await repository.create(user1)

    const roleVO = UserRole.create('admin')
    const foundUsers = await repository.findByRole(roleVO)

    expect(foundUsers.length).toBe(1)
    expect(foundUsers[0]?.id).toBe('user_1')
  })

  it('should throw NotFoundError when updating non-existent user', async () => {
    const nonExistentId = 'ghost_user'
    await expect(repository.update(nonExistentId, { firstName: 'Jane' })).rejects.toThrow(
      NotFoundError
    )
  })

  it('should delete users successfully', async () => {
    const user = createMockUser('user_1')
    await repository.create(user)

    await repository.delete('user_1')
    const found = await repository.findById('user_1')
    expect(found).toBeNull()
  })
})
