import { IRepository } from './IRepository'
import { Service } from '../entities/Service'

export interface IServiceRepository extends IRepository<Service, Service, Partial<Service>> {}
export default IServiceRepository
