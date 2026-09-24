import { BaseService } from './BaseService'
import { Staff, type StaffWriteInput } from '../../domain/entities/Staff'
import type { IStaffRepository } from '../../domain/repositories/IStaffRepository'
import { Email } from '../../domain/value-objects/Email'
import apiClient from '../../infrastructure/http/client'
import { HttpStaffRepository } from '../../infrastructure/repositories/HttpStaffRepository'
import type { CreateStaffSchema } from '../validators/staff.validators'
import { createStaffSchema } from '../validators/staff.validators'

/**
 * Service to manage Staff operations.
 * Extends BaseService<Staff> to leverage template execute method, logging, and error handling.
 */
export class StaffService extends BaseService<Staff> {
  protected repository: IStaffRepository

  /**
   * Initializes a new instance of the StaffService.
   *
   * @param staffRepository The injected Staff repository implementation.
   */
  constructor(staffRepository: IStaffRepository) {
    super()
    this.repository = staffRepository
  }

  /**
   * Lists all staff members in the system.
   *
   * @returns A promise that resolves to an array of Staff entities.
   */
  async listStaff(): Promise<Staff[]> {
    return await this.execute(async () => {
      return await this.repository.findAll()
    }, 'listStaff')
  }

  /**
   * Creates a new staff member with the provided data.
   *
   * @param data The staff data to create (will be validated).
   * @returns A promise that resolves to the created Staff entity.
   */
  async createStaff(data: CreateStaffSchema): Promise<Staff> {
    return await this.execute(async () => {
      this.validate(data, createStaffSchema)
      const validated = createStaffSchema.parse(data)

      // El id lo asigna el backend: se arma con la fabrica de entidad nueva,
      // igual que ServiceService, en vez de inventar un public_id aca.
      const staff = Staff.create({
        kind: validated.kind,
        firstName: validated.first_name,
        lastName: validated.last_name,
        email: validated.kind === 'resource' ? null : Email.create(validated.email),
        displayName: validated.display_name,
        serviceIds: validated.service_ids
      })

      return await this.repository.create(staff)
    }, 'createStaff')
  }

  /**
   * Updates an existing staff member's information.
   *
   * @param id The unique identifier of the staff member.
   * @param data The edited form values; `kind` is the staff's current kind.
   * @returns A promise that resolves to the updated Staff entity.
   * @throws NotFoundError if the backend answers 404.
   */
  async updateStaff(id: string, data: CreateStaffSchema): Promise<Staff> {
    return await this.execute(async () => {
      this.validate(data, createStaffSchema)
      const validated = createStaffSchema.parse(data)

      // Un recurso no tiene nombre, apellido ni email: mandarlos vacios choca
      // con el min_length de StaffUpdate. El tipo no cambia al editar (el
      // formulario lo fija desde el staff existente).
      const shared = { displayName: validated.display_name, serviceIds: validated.service_ids }
      const input: StaffWriteInput =
        validated.kind === 'resource'
          ? shared
          : {
              ...shared,
              firstName: validated.first_name,
              lastName: validated.last_name,
              email: validated.email
            }

      return await this.repository.update(id, input)
    }, 'updateStaff')
  }

  /**
   * Deletes a staff member from the system by ID.
   *
   * @param id The unique identifier of the staff member to delete.
   * @returns A promise resolving to void.
   */
  async deleteStaff(id: string): Promise<void> {
    await this.execute(async () => {
      await this.repository.delete(id)
    }, 'deleteStaff')
  }
}

export const staffService = new StaffService(new HttpStaffRepository(apiClient))
