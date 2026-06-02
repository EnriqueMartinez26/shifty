import { ServiceContainer } from '../../infrastructure/di/ServiceContainer';

/**
 * Hook personalizado genérico para resolver servicios registrados en el contenedor de dependencias.
 * Proporciona tipado seguro al resolver la instancia.
 * 
 * @template T - Tipo del servicio a resolver
 * @param serviceKey - Clave única bajo la cual se registró el servicio en el contenedor
 * @returns La instancia resuelta del servicio
 * @throws {Error} Si el contenedor de dependencias no está inicializado o el servicio no está registrado
 */
export function useService<T>(serviceKey: string): T {
  const container = ServiceContainer.getInstance();
  
  if (!container.isRegistered(serviceKey)) {
    throw new Error(
      `[useService] El servicio con clave "${serviceKey}" no se encuentra registrado en el ServiceContainer.`
    );
  }

  return container.resolve<T>(serviceKey);
}
export default useService;
