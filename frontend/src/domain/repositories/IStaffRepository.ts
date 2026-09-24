import { IRepository } from './IRepository'
import type { Staff, StaffWriteInput } from '../entities/Staff'

export interface IStaffRepository extends IRepository<Staff, Staff, StaffWriteInput> {}
