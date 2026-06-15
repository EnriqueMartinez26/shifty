import { z } from 'zod'

export const createServiceSchema = z.object({
  name: z.string().min(3, 'El nombre debe tener al menos 3 caracteres'),
  description: z.string().optional().or(z.literal('')),
  duration_minutes: z.number().min(5, 'Minimo 5 minutos').max(480, 'Maximo 8 horas'),
  price: z.number().min(0, 'El precio no puede ser negativo'),
  color: z
    .string()
    .regex(/^#[0-9A-F]{6}$/i, 'Color invalido')
    .optional()
    .or(z.literal('')),
  image_url: z.string().url('URL invalida').optional().or(z.literal('')),
  youtube_trailer_url: z.string().url('URL invalida').optional().or(z.literal(''))
})

export const updateServiceSchema = createServiceSchema.partial()

export type CreateServiceSchema = z.infer<typeof createServiceSchema>
export type UpdateServiceSchema = z.infer<typeof updateServiceSchema>
