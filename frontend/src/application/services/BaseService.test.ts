import { z } from 'zod'

import { ConflictError, NotFoundError } from '@shared/errors'

import { BaseService } from './BaseService'

// Concrete subclass of BaseService to test the abstract class logic
class TestService extends BaseService<unknown> {
  protected repository = {
    fetchData: jest.fn()
  }

  async runSuccessOperation(data: string): Promise<string> {
    return await this.execute(async () => {
      return data
    }, 'runSuccessOperation')
  }

  async runFailedOperation(message: string): Promise<void> {
    return await this.execute(async () => {
      throw new Error(message)
    }, 'runFailedOperation')
  }

  async runTypeErrorOperation(): Promise<void> {
    return await this.execute(async () => {
      const obj = null as unknown as { invalidProperty: never }
      return obj.invalidProperty
    }, 'runTypeErrorOperation')
  }

  async runCountedFailingOperation(operation: () => Promise<string>): Promise<string> {
    return await this.execute(operation, 'runCountedFailingOperation')
  }

  async runValidationOperation(data: unknown, schema: z.ZodSchema): Promise<void> {
    return await this.execute(async () => {
      this.validate(data, schema)
    }, 'runValidationOperation')
  }

  async runParsingOperation<S extends z.ZodTypeAny>(data: unknown, schema: S) {
    return await this.execute(async () => this.validate(data, schema), 'runParsingOperation')
  }

  public triggerLog(level: string, message: string, data?: unknown): void {
    this.log(level, message, data)
  }
}

describe('BaseService', () => {
  let service: TestService
  let consoleWarnSpy: jest.SpyInstance
  let consoleErrorSpy: jest.SpyInstance

  beforeEach(() => {
    service = new TestService()
    consoleWarnSpy = jest.spyOn(console, 'warn').mockImplementation(() => {})
    consoleErrorSpy = jest.spyOn(console, 'error').mockImplementation(() => {})
  })

  afterEach(() => {
    consoleWarnSpy.mockRestore()
    consoleErrorSpy.mockRestore()
  })

  describe('execute() template method', () => {
    it('should successfully execute operations and log start and completion states', async () => {
      const result = await service.runSuccessOperation('hello')

      expect(result).toBe('hello')
      expect(consoleWarnSpy).toHaveBeenCalledWith(
        expect.stringContaining('[INFO] TestService.runSuccessOperation - started')
      )
      expect(consoleWarnSpy).toHaveBeenCalledWith(
        expect.stringContaining('[SUCCESS] TestService.runSuccessOperation - completed')
      )
    })

    it.each(['timeout', 'Network Error', 'fetch failed', 'rate limit exceeded', 'ECONNREFUSED'])(
      'should invoke the operation exactly once when it fails with "%s" (no automatic retries)',
      async (message) => {
        // Regression: a POST that timed out client-side but was processed by the server
        // was replayed here and hit the GiST overlap exclusion, so the user saw a conflict
        // on their own booking. There are no automatic retries at any layer.
        const operation = jest.fn<Promise<string>, []>().mockRejectedValue(new Error(message))

        await expect(service.runCountedFailingOperation(operation)).rejects.toThrow(message)

        expect(operation).toHaveBeenCalledTimes(1)
        expect(consoleErrorSpy).toHaveBeenCalledWith(
          expect.stringContaining(`[ERROR] TestService - Exception: ${message}`)
        )
        expect(consoleWarnSpy).not.toHaveBeenCalledWith(expect.stringContaining('Retrying'))
      }
    )
  })

  describe('Validation', () => {
    const testSchema = z.object({
      name: z.string().min(3),
      age: z.number().int().positive()
    })

    it('should pass validation if data conforms to schema', async () => {
      const validData = { name: 'Alice', age: 30 }
      await expect(service.runValidationOperation(validData, testSchema)).resolves.not.toThrow()
    })

    it('devuelve el valor parseado para que el llamador no parsee dos veces (F9-09)', async () => {
      const trimmed = z.object({ name: z.string().trim() })

      await expect(service.runParsingOperation({ name: '  Ana  ' }, trimmed)).resolves.toEqual({
        name: 'Ana'
      })
    })

    it('should throw Error and log ERROR level on validation failures', async () => {
      const invalidData = { name: 'Al', age: -5 } // name too short, age negative

      await expect(service.runValidationOperation(invalidData, testSchema)).rejects.toThrow(
        'Error de validación: Verifique los datos ingresados.'
      )

      expect(consoleErrorSpy).toHaveBeenCalledWith(
        expect.stringContaining('[ERROR] TestService - Validation Failure.')
      )
    })
  })

  describe('Error handling', () => {
    it('should catch generic errors, log them, and throw a user-friendly wrapper error', async () => {
      const errorMessage = 'Custom domain exception'

      await expect(service.runFailedOperation(errorMessage)).rejects.toThrow(errorMessage)

      expect(consoleErrorSpy).toHaveBeenCalledWith(
        expect.stringContaining('[ERROR] TestService - Exception: Custom domain exception')
      )
    })

    it.each([
      ['ConflictError', new ConflictError('El horario ya esta ocupado')],
      ['NotFoundError', new NotFoundError('Staff no encontrado')]
    ])('deja pasar el %s tipado sin re-envolverlo (F9-03)', async (_name, typed) => {
      // Re-envolverlo en un Error plano dejaba inerte el `instanceof` del
      // GlobalErrorHandler y de la UI: el 409 llegaba como error generico.
      const error: unknown = await service
        .runCountedFailingOperation(() => Promise.reject(typed))
        .catch((reason: unknown) => reason)

      expect(error).toBe(typed)
      expect(error).toBeInstanceOf(typed.constructor)
      expect(consoleErrorSpy).toHaveBeenCalledWith(
        expect.stringContaining(`[ERROR] TestService - ${typed.name}: ${typed.message}`)
      )
    })

    it('should catch TypeErrors, log them, and throw a user-friendly wrapper error', async () => {
      await expect(service.runTypeErrorOperation()).rejects.toThrow(
        'Error de tipo de datos interno.'
      )

      expect(consoleErrorSpy).toHaveBeenCalledWith(
        expect.stringContaining('[ERROR] TestService - TypeError: Cannot read properties of null')
      )
    })
  })

  describe('Logging', () => {
    it('should format logs with [LEVEL] prefixes', () => {
      service.triggerLog('INFO', 'Test log info')
      expect(consoleWarnSpy).toHaveBeenCalledWith('[INFO] Test log info')

      service.triggerLog('ERROR', 'Test log error', { detail: 'stack trace' })
      expect(consoleErrorSpy).toHaveBeenCalledWith('[ERROR] Test log error', {
        detail: 'stack trace'
      })
    })
  })
})
