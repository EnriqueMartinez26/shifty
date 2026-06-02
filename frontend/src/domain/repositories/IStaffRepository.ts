import { Staff } from '../entities/Staff';
import { IRepository } from './IRepository';

export interface IStaffRepository extends IRepository<Staff, Staff, Staff> {}
export default IStaffRepository;
