/**
 * Service Dependencies Configuration
 *
 * Centralizes the registration of all application services.
 * This is the single source of truth for dependency injection configuration.
 *
 * @example
 * ```typescript
 * // In main.tsx
 * registerDependencies();
 * ```
 */

import { ServiceContainer } from './ServiceContainer';
import { UserService } from '../../application/services/UserService';
import { StaffService } from '../../application/services/StaffService';
import { AppointmentService } from '../../application/services/AppointmentService';
import { BookingService } from '../../application/services/BookingService';
import { ServiceService } from '../../application/services/ServiceService';
import { HttpUserRepository } from '../repositories/HttpUserRepository';
import { HttpStaffRepository } from '../repositories/HttpStaffRepository';
import { HttpAppointmentRepository } from '../repositories/HttpAppointmentRepository';
import { HttpBookingRepository } from '../repositories/HttpBookingRepository';
import { HttpServiceRepository } from '../repositories/HttpServiceRepository';
import apiClient from '../http/client';
import { EventBus } from '../../shared/events/EventBus';
import { InMemoryUserRepository } from '../repositories/InMemoryUserRepository';


/**
 * Register all application dependencies
 *
 * Should be called once during application initialization (typically in main.tsx).
 * This function:
 * - Creates repository instances
 * - Creates service instances with injected dependencies
 * - Registers all in the service container
 *
 * @returns {ServiceContainer} The configured service container
 *
 * @throws {Error} If services are already registered or dependencies fail to initialize
 *
 * @example
 * ```typescript
 * import { registerDependencies } from '@/infrastructure/di/dependencies';
 *
 * // In main.tsx, before rendering app
 * registerDependencies();
 *
 * // Then in components, use the services via hooks
 * ```
 */
export function registerDependencies(): ServiceContainer {
  const container = ServiceContainer.getInstance();

  // Clear any existing registrations to ensure clean slate
  // This is safe to call on every registration
  if (container.isRegistered('userService')) {
    container.clear();
  }

  // ===== EVENT BUS =====
  container.register('eventBus', () => EventBus.getInstance());

  // ===== REPOSITORIES =====
  // Register repository factories (HTTP implementations)
  container.register(
    'userRepository',
    () => new HttpUserRepository(apiClient)
  );

  container.register(
    'staffRepository',
    () => new HttpStaffRepository(apiClient)
  );

  container.register(
    'appointmentRepository',
    () => new HttpAppointmentRepository()
  );

  container.register(
    'bookingRepository',
    () => new HttpBookingRepository(apiClient)
  );

  container.register(
    'serviceRepository',
    () => new HttpServiceRepository(apiClient)
  );

  // ===== SERVICES =====
  // Register service factories with injected dependencies
  container.register('userService', () => {
    const userRepository = container.resolve<HttpUserRepository>(
      'userRepository'
    );
    return new UserService(userRepository);
  });

  container.register('staffService', () => {
    const staffRepository = container.resolve<HttpStaffRepository>(
      'staffRepository'
    );
    return new StaffService(staffRepository);
  });

  container.register('appointmentService', () => {
    const bookingRepository = container.resolve<HttpBookingRepository>(
      'bookingRepository'
    );
    return new AppointmentService(bookingRepository);
  });

  container.register('bookingService', () => {
    const bookingRepository = container.resolve<HttpBookingRepository>(
      'bookingRepository'
    );
    return new BookingService(bookingRepository);
  });

  container.register('serviceService', () => {
    const serviceRepository = container.resolve<HttpServiceRepository>(
      'serviceRepository'
    );
    return new ServiceService(serviceRepository);
  });

  return container;
}

/**
 * Create a test container with in-memory repositories
 *
 * Used for testing to avoid HTTP calls.
 * This function would use InMemory implementations once they're created.
 *
 * @returns {ServiceContainer} Test container with mock repositories
 *
 * @example
 * ```typescript
 * // In test setup
 * const container = createTestContainer();
 * const userService = container.resolve<UserService>('userService');
 * ```
 */
export function createTestContainer(): ServiceContainer {
  const container = ServiceContainer.getInstance();
  container.clear();

  // Register EventBus
  container.register('eventBus', () => EventBus.getInstance());

  // Register in-memory implementations
  container.register('userRepository', () => new InMemoryUserRepository());
  
  // HTTP Implementations for other repositories
  container.register('staffRepository', () => new HttpStaffRepository(apiClient));
  container.register('appointmentRepository', () => new HttpAppointmentRepository());
  container.register('bookingRepository', () => new HttpBookingRepository(apiClient));
  container.register('serviceRepository', () => new HttpServiceRepository(apiClient));

  // Services with injected in-memory/http dependencies
  container.register('userService', () => {
    const userRepository = container.resolve<InMemoryUserRepository>('userRepository');
    return new UserService(userRepository);
  });

  container.register('staffService', () => {
    const staffRepository = container.resolve<HttpStaffRepository>('staffRepository');
    return new StaffService(staffRepository);
  });

  container.register('appointmentService', () => {
    const bookingRepository = container.resolve<HttpBookingRepository>('bookingRepository');
    return new AppointmentService(bookingRepository);
  });

  container.register('bookingService', () => {
    const bookingRepository = container.resolve<HttpBookingRepository>('bookingRepository');
    return new BookingService(bookingRepository);
  });

  container.register('serviceService', () => {
    const serviceRepository = container.resolve<HttpServiceRepository>('serviceRepository');
    return new ServiceService(serviceRepository);
  });

  return container;
}

/**
 * Get the application's service container
 *
 * Convenience function to avoid repeated getInstance() calls.
 *
 * @returns {ServiceContainer} The service container
 *
 * @example
 * ```typescript
 * const container = getContainer();
 * const userService = container.resolve<UserService>('userService');
 * ```
 */
export function getContainer(): ServiceContainer {
  return ServiceContainer.getInstance();
}

export default registerDependencies;
