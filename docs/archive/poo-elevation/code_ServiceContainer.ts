/**
 * Historical DI example kept only as archived reference.
 *
 * Original path: POO_ELEVATION/code_ServiceContainer.ts
 * It does not participate in the active frontend runtime.
 */
export class ServiceContainer {
  private static instance: ServiceContainer | null = null
  private services: Map<string, () => any> = new Map()
  private singletons: Map<string, any> = new Map()
  private initialized = false

  private constructor() {}

  static getInstance(): ServiceContainer {
    if (!ServiceContainer.instance) {
      ServiceContainer.instance = new ServiceContainer()
    }
    return ServiceContainer.instance
  }

  static reset(): void {
    ServiceContainer.instance = null
  }

  register<T = any>(
    key: string,
    factory: () => T,
    options: { singleton?: boolean } = {}
  ): void {
    if (this.services.has(key)) {
      console.warn(`Service "${key}" already registered, overwriting`)
    }

    this.services.set(key, factory)

    if (options.singleton) {
      this.singletons.set(key, factory())
    }
  }

  get<T = any>(key: string): T {
    if (this.singletons.has(key)) {
      return this.singletons.get(key) as T
    }

    const factory = this.services.get(key)
    if (!factory) {
      throw new ServiceNotFoundError(
        `Service "${key}" not registered. Available services: ${Array.from(this.services.keys()).join(", ")}`
      )
    }

    return factory() as T
  }

  has(key: string): boolean {
    return this.services.has(key) || this.singletons.has(key)
  }

  initialize(): void {
    if (this.initialized) return

    const singletonKeys = Array.from(this.services.entries())
      .filter(([key]) => this.singletons.has(key))
      .map(([key]) => key)

    for (const key of singletonKeys) {
      try {
        this.get(key)
      } catch (error) {
        console.error(`Failed to initialize service: ${key}`, error)
        throw error
      }
    }

    this.initialized = true
    console.log(`DI Container initialized with ${this.services.size} services`)
  }

  getRegisteredServices(): string[] {
    return Array.from(this.services.keys())
  }

  clear(): void {
    this.services.clear()
    this.singletons.clear()
    this.initialized = false
  }
}

export class ServiceNotFoundError extends Error {
  constructor(message: string) {
    super(message)
    this.name = "ServiceNotFoundError"
    Object.setPrototypeOf(this, ServiceNotFoundError.prototype)
  }
}
