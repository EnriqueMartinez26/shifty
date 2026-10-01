import { IRepository } from './IRepository'
import type { Service, ServiceWriteInput } from '../entities/Service'

export interface IServiceRepository extends IRepository<Service, Service, ServiceWriteInput> {
  /** Sube (o reemplaza) la imagen del servicio; se guarda al instante. */
  uploadImage(id: string, file: Blob): Promise<Service>
  /** Quita la imagen del servicio (subida o URL externa). */
  removeImage(id: string): Promise<Service>
}
