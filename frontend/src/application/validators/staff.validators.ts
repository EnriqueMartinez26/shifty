import { z } from 'zod'

const emailSchema = z.string().email()

/**
 * Persona o recurso (cancha, sala, box). Un recurso solo necesita nombre de
 * muestra y servicios; una persona sigue exigiendo nombre, apellido y email
 * porque el backend le crea un usuario con login.
 *
 * Es un objeto con refinamiento y no una union discriminada porque el
 * formulario viejo no manda `kind` y zod 4 no aplica el default del
 * discriminador cuando falta la clave.
 */
export const createStaffSchema = z
  .object({
    kind: z.enum(['person', 'resource']).default('person'),
    first_name: z.string().default(''),
    last_name: z.string().default(''),
    email: z.string().default(''),
    display_name: z.string().min(2, 'Nombre de muestra muy corto'),
    service_ids: z.array(z.string()).min(1, 'Debe tener al menos un servicio asignado')
  })
  .superRefine((data, ctx) => {
    if (data.kind === 'resource') return
    if (data.first_name.trim().length < 2) {
      ctx.addIssue({ code: 'custom', path: ['first_name'], message: 'Nombre muy corto' })
    }
    if (data.last_name.trim().length < 2) {
      ctx.addIssue({ code: 'custom', path: ['last_name'], message: 'Apellido muy corto' })
    }
    if (!emailSchema.safeParse(data.email).success) {
      ctx.addIssue({ code: 'custom', path: ['email'], message: 'Email inválido' })
    }
  })

export type CreateStaffSchema = z.input<typeof createStaffSchema>
