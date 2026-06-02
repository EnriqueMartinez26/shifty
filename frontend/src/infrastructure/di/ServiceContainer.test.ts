/**
 * ServiceContainer Tests
 *
 * Unit tests for the Dependency Injection container.
 * Tests cover registration, resolution, and error handling.
 */

import { ServiceContainer } from './ServiceContainer';

describe('ServiceContainer', () => {
  let container: ServiceContainer;

  /**
   * Setup: Reset container before each test
   */
  beforeEach(() => {
    ServiceContainer.reset();
    container = ServiceContainer.getInstance();
  });

  /**
   * Teardown: Clear container after each test
   */
  afterEach(() => {
    container.clear();
  });

  // ===== SINGLETON PATTERN =====

  describe('Singleton Pattern', () => {
    it('should return the same instance on multiple calls to getInstance', () => {
      const instance1 = ServiceContainer.getInstance();
      const instance2 = ServiceContainer.getInstance();

      expect(instance1).toBe(instance2);
    });

    it('should maintain separate instances when reset is called', () => {
      const instance1 = ServiceContainer.getInstance();
      ServiceContainer.reset();
      const instance2 = ServiceContainer.getInstance();

      // After reset, should be a new instance
      expect(instance1).not.toBe(instance2);
    });
  });

  // ===== REGISTRATION =====

  describe('register()', () => {
    it('should register a service factory', () => {
      const factory = () => ({ name: 'test' });
      container.register('testService', factory);

      expect(container.isRegistered('testService')).toBe(true);
    });

    it('should throw error when key is empty', () => {
      const factory = () => ({ name: 'test' });

      expect(() => container.register('', factory)).toThrow(
        'Service key cannot be empty'
      );
    });

    it('should throw error when key is whitespace only', () => {
      const factory = () => ({ name: 'test' });

      expect(() => container.register('   ', factory)).toThrow(
        'Service key cannot be empty'
      );
    });

    it('should throw error when factory is not a function', () => {
      expect(() =>
        container.register('testService', 'not a function' as any)
      ).toThrow('Factory for key "testService" must be a function');
    });

    it('should allow re-registration of same key', () => {
      const factory1 = () => ({ value: 1 });
      const factory2 = () => ({ value: 2 });

      container.register('service', factory1);
      container.register('service', factory2);

      expect(container.isRegistered('service')).toBe(true);
    });

    it('should clear cached instance when re-registering', () => {
      const factory1 = () => ({ value: 1 });
      const factory2 = () => ({ value: 2 });

      container.register('service', factory1);
      const instance1 = container.resolve<{ value: number }>('service');

      container.register('service', factory2);
      const instance2 = container.resolve<{ value: number }>('service');

      expect(instance1.value).toBe(1);
      expect(instance2.value).toBe(2);
    });
  });

  // ===== RESOLUTION =====

  describe('resolve()', () => {
    it('should resolve a registered service', () => {
      const expectedService = { name: 'testService' };
      container.register('testService', () => expectedService);

      const resolved = container.resolve<{ name: string }>('testService');

      expect(resolved).toBe(expectedService);
    });

    it('should throw error when service is not registered', () => {
      expect(() => container.resolve('nonExistent')).toThrow(
        'Service with key "nonExistent" is not registered'
      );
    });

    it('should throw error with list of available services', () => {
      container.register('service1', () => ({}));
      container.register('service2', () => ({}));

      expect(() => container.resolve('nonExistent')).toThrow(
        /Available services: service1, service2/
      );
    });

    it('should return singleton instance on multiple calls', () => {
      const factory = jest.fn(() => ({ name: 'test' }));
      container.register('testService', factory);

      const instance1 = container.resolve('testService');
      const instance2 = container.resolve('testService');

      expect(instance1).toBe(instance2);
      expect(factory).toHaveBeenCalledTimes(1);
    });

    it('should support generic type inference', () => {
      interface TestService {
        getValue(): number;
      }

      const testService: TestService = {
        getValue: () => 42,
      };

      container.register('testService', () => testService);
      const resolved = container.resolve<TestService>('testService');

      expect(resolved.getValue()).toBe(42);
    });

    it('should create new instance on first call to factory', () => {
      const factory = jest.fn(() => ({ id: Math.random() }));
      container.register('service', factory);

      container.resolve('service');

      expect(factory).toHaveBeenCalledTimes(1);
    });
  });

  // ===== REGISTRATION CHECK =====

  describe('isRegistered()', () => {
    it('should return true for registered service', () => {
      container.register('testService', () => ({}));

      expect(container.isRegistered('testService')).toBe(true);
    });

    it('should return false for unregistered service', () => {
      expect(container.isRegistered('nonExistent')).toBe(false);
    });

    it('should return false after service is cleared', () => {
      container.register('testService', () => ({}));
      container.clear();

      expect(container.isRegistered('testService')).toBe(false);
    });
  });

  // ===== REGISTERED KEYS =====

  describe('getRegisteredKeys()', () => {
    it('should return array of all registered keys', () => {
      container.register('service1', () => ({}));
      container.register('service2', () => ({}));
      container.register('service3', () => ({}));

      const keys = container.getRegisteredKeys();

      expect(keys).toContain('service1');
      expect(keys).toContain('service2');
      expect(keys).toContain('service3');
      expect(keys.length).toBe(3);
    });

    it('should return empty array when no services registered', () => {
      const keys = container.getRegisteredKeys();

      expect(keys).toEqual([]);
    });

    it('should update when new services are registered', () => {
      expect(container.getRegisteredKeys().length).toBe(0);

      container.register('service1', () => ({}));
      expect(container.getRegisteredKeys().length).toBe(1);

      container.register('service2', () => ({}));
      expect(container.getRegisteredKeys().length).toBe(2);
    });
  });

  // ===== CLEAR =====

  describe('clear()', () => {
    it('should remove all registered services', () => {
      container.register('service1', () => ({}));
      container.register('service2', () => ({}));

      container.clear();

      expect(container.isRegistered('service1')).toBe(false);
      expect(container.isRegistered('service2')).toBe(false);
    });

    it('should clear cached instances', () => {
      const factory = jest.fn(() => ({}));
      container.register('service', factory);

      container.resolve('service');
      expect(factory).toHaveBeenCalledTimes(1);

      container.clear();
      container.register('service', factory);
      container.resolve('service');

      // Factory should be called again after clear
      expect(factory).toHaveBeenCalledTimes(2);
    });

    it('should reset getRegisteredKeys result', () => {
      container.register('service', () => ({}));
      expect(container.getRegisteredKeys().length).toBe(1);

      container.clear();
      expect(container.getRegisteredKeys().length).toBe(0);
    });
  });

  // ===== COMPLEX SCENARIOS =====

  describe('Complex Scenarios', () => {
    it('should handle service with dependencies', () => {
      interface Logger {
        log(message: string): void;
      }

      interface UserService {
        getUsers(): void;
      }

      const mockLogger: Logger = { log: jest.fn() };

      container.register('logger', () => mockLogger);
      container.register('userService', () => {
        const logger = container.resolve<Logger>('logger');
        return {
          getUsers() {
            logger.log('Getting users');
          },
        } as UserService;
      });

      const userService = container.resolve<UserService>('userService');
      userService.getUsers();

      expect(mockLogger.log).toHaveBeenCalledWith('Getting users');
    });

    it('should maintain type safety with multiple service types', () => {
      interface ServiceA {
        typeA: 'A';
      }

      interface ServiceB {
        typeB: 'B';
      }

      container.register('serviceA', () => ({ typeA: 'A' } as ServiceA));
      container.register('serviceB', () => ({ typeB: 'B' } as ServiceB));

      const serviceA = container.resolve<ServiceA>('serviceA');
      const serviceB = container.resolve<ServiceB>('serviceB');

      expect(serviceA.typeA).toBe('A');
      expect(serviceB.typeB).toBe('B');
    });

    it('should handle rapid register/resolve cycles', () => {
      for (let i = 0; i < 100; i++) {
        container.register(`service${i}`, () => ({ id: i }));
      }

      for (let i = 0; i < 100; i++) {
        const service = container.resolve<{ id: number }>(`service${i}`);
        expect(service.id).toBe(i);
      }
    });
  });
});
