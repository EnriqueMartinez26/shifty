import { BaseService } from './BaseService';
import { Staff } from '../../domain/entities/Staff';
import type { IStaffRepository } from '../../domain/repositories/IStaffRepository';
import { createStaffSchema } from '../validators/staff.validators';

/**
 * Service to manage Staff operations.
 * Extends BaseService<Staff> to leverage template execute method, logging, and error handling.
 */
export class StaffService extends BaseService<Staff> {
  protected repository: IStaffRepository;

  /**
   * Initializes a new instance of the StaffService.
   * 
   * @param staffRepository The injected Staff repository implementation.
   */
  constructor(staffRepository: IStaffRepository) {
    super();
    this.repository = staffRepository;
  }

  /**
   * Lists all staff members in the system.
   * 
   * @returns A promise that resolves to an array of Staff entities.
   */
  async listStaff(): Promise<Staff[]> {
    return await this.execute(async () => {
      return await this.repository.findAll();
    }, 'listStaff');
  }

  /**
   * Creates a new staff member with the provided data.
   * 
   * @param data The staff data to create (will be validated).
   * @returns A promise that resolves to the created Staff entity.
   */
  async createStaff(data: any): Promise<Staff> {
    return await this.execute(async () => {
      this.validate(data, createStaffSchema);
      const validated = createStaffSchema.parse(data);

      const staff = Staff.fromPrimitives({
        public_id: crypto.randomUUID(),
        first_name: validated.first_name,
        last_name: validated.last_name,
        email: validated.email,
        display_name: validated.display_name,
        is_active: true,
        service_ids: validated.service_ids,
      });

      return await this.repository.create(staff);
    }, 'createStaff');
  }

  /**
   * Updates an existing staff member's information.
   * 
   * @param id The unique identifier of the staff member.
   * @param data The new staff data to replace existing values.
   * @returns A promise that resolves to the updated Staff entity.
   * @throws Error if the staff member is not found.
   */
  async updateStaff(id: string, data: any): Promise<Staff> {
    return await this.execute(async () => {
      const existing = await this.repository.findById(id);
      if (!existing) throw new Error("Staff no encontrado");

      this.validate(data, createStaffSchema);
      const validated = createStaffSchema.parse(data);

      const updatedStaff = Staff.fromPrimitives({
        ...existing.toPrimitives(),
        first_name: validated.first_name,
        last_name: validated.last_name,
        email: validated.email,
        display_name: validated.display_name,
        service_ids: validated.service_ids,
      });

      return await this.repository.update(id, updatedStaff);
    }, 'updateStaff');
  }

  /**
   * Deletes a staff member from the system by ID.
   * 
   * @param id The unique identifier of the staff member to delete.
   * @returns A promise resolving to void.
   */
  async deleteStaff(id: string): Promise<void> {
    await this.execute(async () => {
      await this.repository.delete(id);
    }, 'deleteStaff');
  }
}
