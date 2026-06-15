import { z } from 'zod'

export const createUserSchema = z.object({
  email: z.string().email('Email inválido'),
  password: z.string().min(6, 'La contraseña debe tener al menos 6 caracteres'),
  first_name: z.string().min(2, 'Nombre muy corto').optional().or(z.literal('')),
  last_name: z.string().min(2, 'Apellido muy corto').optional().or(z.literal('')),
  phone: z.string().optional().or(z.literal('')),
  role: z.enum(['admin', 'staff', 'client'])
})

export const updateUserSchema = z.object({
  first_name: z.string().min(2).optional().or(z.literal('')),
  last_name: z.string().min(2).optional().or(z.literal('')),
  phone: z.string().optional().or(z.literal('')),
  role: z.enum(['admin', 'staff', 'client']).optional(),
  password: z.string().min(6).optional().or(z.literal('')),
  is_active: z.boolean().optional()
})

export type CreateUserSchema = z.infer<typeof createUserSchema>
export type UpdateUserSchema = z.infer<typeof updateUserSchema>
