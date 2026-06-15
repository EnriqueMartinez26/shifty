/**
 * Dependency Injection Container
 *
 * Singleton registry for service instantiation and resolution.
 * Implements the Service Locator pattern with type-safe generics.
 *
 * @example
 * ```typescript
 * const container = ServiceContainer.getInstance();
 * container.register('userService', () => new UserService());
 * const userService = container.resolve<UserService>('userService');
 * ```
 */

/**
 * Factory function type for service instantiation
 */
type ServiceFactory<T> = () => T

/**
 * Service Container Registry
 *
 * Maintains a singleton registry of services and their factories.
 * Ensures all instances are created consistently and can be resolved type-safely.
 */
export class ServiceContainer {
  private static instance: ServiceContainer
  private registry: Map<string, ServiceFactory<unknown>>
  private instances: Map<string, unknown>

  /**
   * Private constructor to enforce singleton pattern
   */
  private constructor() {
    this.registry = new Map()
    this.instances = new Map()
  }

  /**
   * Get singleton instance of ServiceContainer
   *
   * @returns {ServiceContainer} The singleton instance
   */
  static getInstance(): ServiceContainer {
    if (!ServiceContainer.instance) {
      ServiceContainer.instance = new ServiceContainer()
    }
    return ServiceContainer.instance
  }

  /**
   * Register a service factory with the container
   *
   * @template T - The type of the service being registered
   * @param {string} key - Unique key to identify the service
   * @param {ServiceFactory<T>} factory - Function that creates the service instance
   * @throws {Error} If key is empty or factory is not a function
   *
   * @example
   * ```typescript
   * container.register('userService', () => new UserService(userRepository));
   * ```
   */
  register<T>(key: string, factory: ServiceFactory<T>): void {
    if (!key || key.trim().length === 0) {
      throw new Error('Service key cannot be empty')
    }

    if (typeof factory !== 'function') {
      throw new Error(`Factory for key "${key}" must be a function`)
    }

    this.registry.set(key, factory)
    // Clear cached instance when registering
    this.instances.delete(key)
  }

  /**
   * Resolve a service by key
   *
   * Lazily instantiates the service on first access and caches it.
   * Subsequent calls return the same instance (singleton behavior).
   *
   * @template T - The type of the service to resolve
   * @param {string} key - The key of the service to resolve
   * @returns {T} The resolved service instance
   * @throws {Error} If service key is not registered
   *
   * @example
   * ```typescript
   * const userService = container.resolve<UserService>('userService');
   * ```
   */
  resolve<T>(key: string): T {
    if (!this.registry.has(key)) {
      throw new Error(
        `Service with key "${key}" is not registered. Available services: ${Array.from(
          this.registry.keys()
        ).join(', ')}`
      )
    }

    // Return cached instance if available
    if (this.instances.has(key)) {
      return this.instances.get(key) as T
    }

    // Create and cache new instance
    const factory = this.registry.get(key) as ServiceFactory<T>
    const instance = factory()
    this.instances.set(key, instance)

    return instance
  }

  /**
   * Check if a service is registered
   *
   * @param {string} key - The key to check
   * @returns {boolean} True if service is registered, false otherwise
   *
   * @example
   * ```typescript
   * if (container.isRegistered('userService')) {
   *   const service = container.resolve('userService');
   * }
   * ```
   */
  isRegistered(key: string): boolean {
    return this.registry.has(key)
  }

  /**
   * Get all registered service keys
   *
   * Useful for debugging and introspection.
   *
   * @returns {string[]} Array of registered service keys
   *
   * @example
   * ```typescript
   * const keys = container.getRegisteredKeys();
   * console.log('Registered services:', keys);
   * ```
   */
  getRegisteredKeys(): string[] {
    return Array.from(this.registry.keys())
  }

  /**
   * Clear all registered services and cached instances
   *
   * Typically used in testing to reset container state.
   *
   * @example
   * ```typescript
   * afterEach(() => {
   *   container.clear();
   * });
   * ```
   */
  clear(): void {
    this.registry.clear()
    this.instances.clear()
  }

  /**
   * Reset singleton instance (for testing)
   *
   * @internal
   */
  static reset(): void {
    ServiceContainer.instance = new ServiceContainer()
  }
}

export default ServiceContainer
