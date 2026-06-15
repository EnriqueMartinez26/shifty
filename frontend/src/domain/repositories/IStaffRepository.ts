import { IRepository } from './IRepository'
import { Staff } from '../entities/Staff'

export interface IStaffRepository extends IRepository<Staff, Staff, Staff> {}
export default IStaffRepository
