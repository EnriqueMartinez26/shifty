/**
 * useService Hook
 *
 * React hook for accessing registered services from the DI container.
 * Provides type-safe service resolution within React components.
 *
 * @example
 * ```typescript
 * // In a component
 * const userService = useService<UserService>('userService');
 * const users = await userService.getAllUsers();
 * ```
 */

import { useMemo } from 'react';
import { ServiceContainer } from '../../infrastructure/di/ServiceContainer';

/**
 * Access a registered service from the DI container
 *
 * This hook:
 * - Retrieves the service from the container on mount
 * - Caches the result to prevent unnecessary lookups
 * - Throws an error if the service is not registered
 * - Is type-safe through TypeScript generics
 *
 * @template T - The type of the service being requested
 * @param {string} key - The registration key of the service
 * @returns {T} The resolved service instance
 * @throws {Error} If service key is not registered in the container
 *
 * @example
 * ```typescript
 * // Basic usage
 * const userService = useService<UserService>('userService');
 *
 * // With effect
 * useEffect(() => {
 *   const loadUsers = async () => {
 *     const users = await userService.getAllUsers();
 *     setUsers(users);
 *   };
 *   loadUsers();
 * }, [userService]);
 *
 * // With error handling
 * try {
 *   const service = useService<UserService>('userService');
 * } catch (error) {
 *   console.error('Service not registered:', error);
 * }
 * ```
 */
export function useService<T>(key: string): T {
  const service = useMemo(() => {
    const container = ServiceContainer.getInstance();

    if (!container.isRegistered(key)) {
      throw new Error(
        `Service "${key}" is not registered in the DI container. ` +
        `Available services: ${container.getRegisteredKeys().join(', ')}`
      );
    }

    return container.resolve<T>(key);
  }, [key]);

  return service;
}

export default useService;
