/**
 * Base de los errores que lanza el dominio. Lleva un `code` estable para que
 * las capas de afuera lo distingan de un fallo de red o de un bug sin mirar el
 * texto. No sabe nada de HTTP: la traduccion a ApplicationError la hace
 * infrastructure (BaseRepository).
 */
export class DomainError extends Error {
  public readonly code: string

  constructor(code: string, message: string) {
    super(message)
    this.name = new.target.name
    this.code = code
    Object.setPrototypeOf(this, new.target.prototype)
  }
}

/** Un value object rechazo el valor con el que se lo quiso construir. */
export class InvalidValueError extends DomainError {}
