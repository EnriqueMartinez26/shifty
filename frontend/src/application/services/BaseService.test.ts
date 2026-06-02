import { BaseService } from './BaseService';
import { z } from 'zod';

// Concrete subclass of BaseService to test the abstract class logic
class TestService extends BaseService<any> {
  protected repository = {
    fetchData: jest.fn(),
  };

  constructor() {
    super();
    // Reduce retry delay to make tests run instantly
    this.retryOptions = {
      maxAttempts: 2,
      delayMs: 2,
    };
  }

  async runSuccessOperation(data: string): Promise<string> {
    return await this.execute(async () => {
      return data;
    }, 'runSuccessOperation');
  }

  async runFailedOperation(message: string): Promise<void> {
    return await this.execute(async () => {
      throw new Error(message);
    }, 'runFailedOperation');
  }

  async runTypeErrorOperation(): Promise<void> {
    return await this.execute(async () => {
      const obj: any = null;
      return obj.invalidProperty;
    }, 'runTypeErrorOperation');
  }

  async runRetryableOperation(attemptsBeforeSuccess: number): Promise<string> {
    let callCount = 0;
    return await this.execute(async () => {
      callCount++;
      if (callCount < attemptsBeforeSuccess) {
        throw new Error('Network timeout occurred');
      }
      return 'success after retry';
    }, 'runRetryableOperation');
  }

  async runValidationOperation(data: unknown, schema: z.ZodSchema): Promise<void> {
    return await this.execute(async () => {
      this.validate(data, schema);
    }, 'runValidationOperation');
  }

  public triggerLog(level: string, message: string, data?: any): void {
    this.log(level, message, data);
  }
}

describe('BaseService', () => {
  let service: TestService;
  let consoleLogSpy: jest.SpyInstance;
  let consoleErrorSpy: jest.SpyInstance;

  beforeEach(() => {
    service = new TestService();
    consoleLogSpy = jest.spyOn(console, 'log').mockImplementation(() => {});
    consoleErrorSpy = jest.spyOn(console, 'error').mockImplementation(() => {});
  });

  afterEach(() => {
    consoleLogSpy.mockRestore();
    consoleErrorSpy.mockRestore();
  });

  describe('execute() template method', () => {
    it('should successfully execute operations and log start and completion states', async () => {
      const result = await service.runSuccessOperation('hello');
      
      expect(result).toBe('hello');
      expect(consoleLogSpy).toHaveBeenCalledWith(
        expect.stringContaining('[INFO] TestService.runSuccessOperation - started')
      );
      expect(consoleLogSpy).toHaveBeenCalledWith(
        expect.stringContaining('[SUCCESS] TestService.runSuccessOperation - completed')
      );
    });

    it('should retry a failed operation if the error is retryable and succeeds eventually', async () => {
      const result = await service.runRetryableOperation(2);
      
      expect(result).toBe('success after retry');
      // Should log the start, the warning/retry, and the ultimate completion
      expect(consoleLogSpy).toHaveBeenCalledWith(
        expect.stringContaining('[INFO] TestService.runRetryableOperation - started')
      );
      expect(consoleLogSpy).toHaveBeenCalledWith(
        expect.stringContaining('[WARNING] TestService.runRetryableOperation - Attempt 1 failed. Retrying')
      );
      expect(consoleLogSpy).toHaveBeenCalledWith(
        expect.stringContaining('[SUCCESS] TestService.runRetryableOperation - completed')
      );
    });
  });

  describe('Validation', () => {
    const testSchema = z.object({
      name: z.string().min(3),
      age: z.number().int().positive(),
    });

    it('should pass validation if data conforms to schema', async () => {
      const validData = { name: 'Alice', age: 30 };
      await expect(service.runValidationOperation(validData, testSchema)).resolves.not.toThrow();
    });

    it('should throw Error and log ERROR level on validation failures', async () => {
      const invalidData = { name: 'Al', age: -5 }; // name too short, age negative
      
      await expect(service.runValidationOperation(invalidData, testSchema)).rejects.toThrow(
        'Error de validación: Verifique los datos ingresados.'
      );

      expect(consoleErrorSpy).toHaveBeenCalledWith(
        expect.stringContaining('[ERROR] TestService - Validation Failure.')
      );
    });
  });

  describe('Error handling', () => {
    it('should catch generic errors, log them, and throw a user-friendly wrapper error', async () => {
      const errorMessage = 'Custom domain exception';
      
      await expect(service.runFailedOperation(errorMessage)).rejects.toThrow(errorMessage);
      
      expect(consoleErrorSpy).toHaveBeenCalledWith(
        expect.stringContaining('[ERROR] TestService - Exception: Custom domain exception')
      );
    });

    it('should catch TypeErrors, log them, and throw a user-friendly wrapper error', async () => {
      await expect(service.runTypeErrorOperation()).rejects.toThrow(
        'Error de tipo de datos interno.'
      );
      
      expect(consoleErrorSpy).toHaveBeenCalledWith(
        expect.stringContaining('[ERROR] TestService - TypeError: Cannot read properties of null')
      );
    });
  });

  describe('Logging', () => {
    it('should format logs with [LEVEL] prefixes', () => {
      service.triggerLog('INFO', 'Test log info');
      expect(consoleLogSpy).toHaveBeenCalledWith('[INFO] Test log info');

      service.triggerLog('ERROR', 'Test log error', { detail: 'stack trace' });
      expect(consoleErrorSpy).toHaveBeenCalledWith('[ERROR] Test log error', { detail: 'stack trace' });
    });
  });
});
