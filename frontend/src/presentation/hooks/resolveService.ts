import { ServiceContainer } from '../../infrastructure/di/ServiceContainer'

export function resolveService<T>(serviceKey: string): T {
  const container = ServiceContainer.getInstance()

  if (!container.isRegistered(serviceKey)) {
    throw new Error(
      `[resolveService] El servicio con clave "${serviceKey}" no se encuentra registrado en el ServiceContainer.`
    )
  }

  return container.resolve<T>(serviceKey)
}

export default resolveService
