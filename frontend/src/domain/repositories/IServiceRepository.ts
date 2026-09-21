import { IRepository } from './IRepository'
import type { Service, ServiceWriteInput } from '../entities/Service'

export interface IServiceRepository extends IRepository<Service, Service, ServiceWriteInput> {}
