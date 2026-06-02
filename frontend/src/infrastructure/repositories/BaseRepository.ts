import { IRepository, QueryOptions } from '../../domain/repositories/IRepository';
import { ApplicationError } from '../../shared/errors/ApplicationError';
import { InternalServerError } from '../../shared/errors/InternalServerError';

/**
 * Clase base abstracta para repositorios que implementa el Template Method Pattern.
 * Centraliza el control y la traducción de excepciones de persistencia.
 */
export abstract class BaseRepository<T, CreateDTO = T, UpdateDTO = Partial<T>> 
  implements IRepository<T, CreateDTO, UpdateDTO> 
{
  public async findAll(options?: QueryOptions | boolean): Promise<T[]> {
    try {
      return await this.findAllImpl(options);
    } catch (error) {
      this.handleRepositoryError('findAll', error);
    }
  }

  public async findById(id: string): Promise<T | null> {
    try {
      return await this.findByIdImpl(id);
    } catch (error) {
      this.handleRepositoryError('findById', error);
    }
  }

  public async create(data: CreateDTO, extra?: any): Promise<T> {
    try {
      return await this.createImpl(data, extra);
    } catch (error) {
      this.handleRepositoryError('create', error);
    }
  }

  public async update(id: string, data: UpdateDTO): Promise<T> {
    try {
      return await this.updateImpl(id, data);
    } catch (error) {
      this.handleRepositoryError('update', error);
    }
  }

  public async delete(id: string): Promise<void> {
    try {
      await this.deleteImpl(id);
    } catch (error) {
      this.handleRepositoryError('delete', error);
    }
  }

  // --- Abstract hooks implementados por subclases concretas ---
  protected abstract findAllImpl(options?: QueryOptions | boolean): Promise<T[]>;
  protected abstract findByIdImpl(id: string): Promise<T | null>;
  protected abstract createImpl(data: CreateDTO, extra?: any): Promise<T>;
  protected abstract updateImpl(id: string, data: UpdateDTO): Promise<T>;
  protected abstract deleteImpl(id: string): Promise<void>;

  /**
   * Estandariza errores imprevistos a nivel de base de datos a InternalServerError.
   */
  protected handleRepositoryError(operation: string, error: unknown): never {
    if (error instanceof ApplicationError) {
      throw error;
    }
    const msg = error instanceof Error ? error.message : 'Unknown repository error';
    throw new InternalServerError(`Database operation '${operation}' failed: ${msg}`);
  }
}
export default BaseRepository;
