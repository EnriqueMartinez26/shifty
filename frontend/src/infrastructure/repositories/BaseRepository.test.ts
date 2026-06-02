import { BaseRepository } from './BaseRepository';
import { QueryOptions } from '../../domain/repositories/IRepository';
import { InternalServerError } from '../../shared/errors/InternalServerError';

class TestRepository extends BaseRepository<any, any, any> {
  public mockFindAll = jest.fn();
  
  protected async findAllImpl(options?: QueryOptions | boolean): Promise<any[]> {
    return this.mockFindAll(options);
  }
  protected async findByIdImpl(_id: string): Promise<any> { return null; }
  protected async createImpl(_data: any, _extra?: any): Promise<any> { return null; }
  protected async updateImpl(_id: string, _data: any): Promise<any> { return null; }
  protected async deleteImpl(_id: string): Promise<void> {}
}

describe('BaseRepository', () => {
  let repository: TestRepository;

  beforeEach(() => {
    repository = new TestRepository();
  });

  it('should delegate execution to implementation hook on success', async () => {
    repository.mockFindAll.mockResolvedValue(['test_1', 'test_2']);
    const result = await repository.findAll();
    expect(result).toEqual(['test_1', 'test_2']);
    expect(repository.mockFindAll).toHaveBeenCalledTimes(1);
  });

  it('should wrap unhandled errors into an InternalServerError', async () => {
    repository.mockFindAll.mockRejectedValue(new Error('Connection timed out'));
    
    await expect(repository.findAll()).rejects.toThrow(InternalServerError);
    await expect(repository.findAll()).rejects.toThrow("Database operation 'findAll' failed: Connection timed out");
  });
});
