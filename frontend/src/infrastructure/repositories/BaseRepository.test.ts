import { BaseRepository } from './BaseRepository'
import { QueryOptions } from '../../domain/repositories/IRepository'
import { InternalServerError } from '../../shared/errors/InternalServerError'

class TestRepository extends BaseRepository<unknown, unknown, unknown> {
  public mockFindAll: jest.Mock<Promise<unknown[]>, [QueryOptions | boolean | undefined]> =
    jest.fn()

  protected async findAllImpl(options?: QueryOptions | boolean): Promise<unknown[]> {
    return this.mockFindAll(options)
  }
  protected async findByIdImpl(_id: string): Promise<unknown> {
    return null
  }
  protected async createImpl(_data: unknown, _extra?: unknown): Promise<unknown> {
    return null
  }
  protected async updateImpl(_id: string, _data: unknown): Promise<unknown> {
    return null
  }
  protected async deleteImpl(_id: string): Promise<void> {}
}

describe('BaseRepository', () => {
  let repository: TestRepository

  beforeEach(() => {
    repository = new TestRepository()
  })

  it('should delegate execution to implementation hook on success', async () => {
    repository.mockFindAll.mockResolvedValue(['test_1', 'test_2'])
    const result = await repository.findAll()
    expect(result).toEqual(['test_1', 'test_2'])
    expect(repository.mockFindAll).toHaveBeenCalledTimes(1)
  })

  it('should wrap unhandled errors into an InternalServerError', async () => {
    repository.mockFindAll.mockRejectedValue(new Error('Connection timed out'))

    await expect(repository.findAll()).rejects.toThrow(InternalServerError)
    await expect(repository.findAll()).rejects.toThrow(
      "Database operation 'findAll' failed: Connection timed out"
    )
  })
})
