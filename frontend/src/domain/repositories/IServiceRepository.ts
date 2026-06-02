import { Service } from '../entities/Service';
import { IRepository } from './IRepository';

export interface IServiceRepository extends IRepository<Service, Service, Partial<Service>> {}
export default IServiceRepository;
