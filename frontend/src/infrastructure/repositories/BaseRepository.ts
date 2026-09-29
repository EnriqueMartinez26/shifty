import { DomainError } from '../../domain/errors/DomainError'
import { IRepository, QueryOptions } from '../../domain/repositories/IRepository'
import { ApplicationError } from '../../shared/errors/ApplicationError'
import { InternalServerError } from '../../shared/errors/InternalServerError'
import { ValidationError } from '../../shared/errors/ValidationError'

/**
 * Clase base abstracta para repositorios que implementa el Template Method Pattern.
 * Centraliza el control y la traducción de excepciones de persistencia.
 */
export abstract class BaseRepository<
  T,
  CreateDTO = T,
  UpdateDTO = Partial<T>,
  CreateExtra = never
> implements IRepository<T, CreateDTO, UpdateDTO, CreateExtra> {
  public async findAll(options?: QueryOptions | boolean): Promise<T[]> {
    try {
      return await this.findAllImpl(options)
    } catch (error) {
      this.handleRepositoryError('findAll', error)
    }
  }

  public async findById(id: string): Promise<T | null> {
    try {
      return await this.findByIdImpl(id)
    } catch (error) {
      this.handleRepositoryError('findById', error)
    }
  }

  public async create(data: CreateDTO, extra?: CreateExtra): Promise<T> {
    try {
      return await this.createImpl(data, extra)
    } catch (error) {
      this.handleRepositoryError('create', error)
    }
  }

  public async update(id: string, data: UpdateDTO): Promise<T> {
    try {
      return await this.updateImpl(id, data)
    } catch (error) {
      this.handleRepositoryError('update', error)
    }
  }

  public async delete(id: string): Promise<void> {
    try {
      await this.deleteImpl(id)
    } catch (error) {
      this.handleRepositoryError('delete', error)
    }
  }

  // --- Abstract hooks implementados por subclases concretas ---
  protected abstract findAllImpl(options?: QueryOptions | boolean): Promise<T[]>
  protected abstract findByIdImpl(id: string): Promise<T | null>
  protected abstract createImpl(data: CreateDTO, extra?: CreateExtra): Promise<T>
  protected abstract updateImpl(id: string, data: UpdateDTO): Promise<T>
  protected abstract deleteImpl(id: string): Promise<void>

  protected handleRepositoryError(operation: string, error: unknown): never {
    translateRepositoryError(operation, error)
  }
}

const UNEXPECTED_FAILURE_MESSAGE = 'No se pudo completar la operación.'

/**
 * Traduce lo que falle abajo a un ApplicationError tipado. Un DomainError (un
 * value object que rechazo un dato) sale como ValidationError con su `code`
 * y su propio mensaje, que es texto del front pensado para el usuario. Lo
 * demas imprevisto queda como InternalServerError con un mensaje neutro. El
 * detalle tecnico ("Database operation 'x' failed: ...") viaja en
 * `context.technicalMessage` para depurar, nunca como `message` (regla 20).
 * Exportada para los repositorios que no son CRUD generico
 * (HttpBookingRepository).
 */
export function translateRepositoryError(operation: string, error: unknown): never {
  if (error instanceof ApplicationError) {
    throw error
  }
  const msg = error instanceof Error ? error.message : 'Unknown repository error'
  const technicalMessage = `Database operation '${operation}' failed: ${msg}`
  if (error instanceof DomainError) {
    throw new ValidationError(error.message, { code: error.code, operation, technicalMessage })
  }
  throw new InternalServerError(UNEXPECTED_FAILURE_MESSAGE, { operation, technicalMessage })
}
