export interface QueryOptions {
  includeInactive?: boolean
  limit?: number
  offset?: number
  sortBy?: string
  order?: 'asc' | 'desc'
}

/**
 * Interfaz genérica base para todos los repositorios del dominio.
 *
 * @template T - Tipo de la entidad de dominio.
 * @template CreateDTO - Tipo del payload de creación.
 * @template UpdateDTO - Tipo del payload de actualización.
 * @template CreateExtra - Dato adicional del alta que no es parte de la
 *   entidad (p. ej. la contraseña inicial de un usuario). `never` por defecto:
 *   un repositorio que no lo declara no acepta un segundo argumento.
 */
export interface IRepository<T, CreateDTO = T, UpdateDTO = Partial<T>, CreateExtra = never> {
  findAll(options?: QueryOptions | boolean): Promise<T[]>
  findById(id: string): Promise<T | null>
  create(data: CreateDTO, extra?: CreateExtra): Promise<T>
  update(id: string, data: UpdateDTO): Promise<T>
  delete(id: string): Promise<void>
}
