import { z } from 'zod'

export const createBookingSchema = z.object({
  store_public_id: z.string().min(1, 'ID de negocio requerido').optional(),
  service_id: z
    .string()
    .uuid('ID de servicio invalido')
    .or(z.string().min(1, 'ID de servicio requerido')),
  staff_id: z
    .string()
    .uuid('ID de staff invalido')
    .or(z.string().min(1, 'ID de staff requerido'))
    .optional(),
  starts_at: z
    .string()
    .datetime({ offset: true })
    .or(z.string().regex(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}/, 'Formato de fecha invalido')),
  client_name: z.string().min(2, 'El nombre debe tener al menos 2 caracteres'),
  client_email: z
    .union([z.string().email('Correo electronico invalido'), z.literal(''), z.undefined()])
    .optional(),
  client_phone: z
    .string()
    .min(8, 'Numero de telefono muy corto')
    .max(20, 'Numero de telefono muy largo'),
  notes: z.string().optional().or(z.literal('')),
  idempotency_key: z.string().min(10, 'Clave de idempotencia invalida').optional()
})

export type CreateBookingSchema = z.infer<typeof createBookingSchema>
