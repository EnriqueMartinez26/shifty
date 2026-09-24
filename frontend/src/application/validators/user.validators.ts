import { z } from 'zod'

export const createUserSchema = z.object({
  email: z.string().email('Email inválido'),
  // Mismo piso que `UserCreate` en el backend (min_length=12). La fuerza
  // (letra, numero, denylist) la decide el backend; aca solo el largo.
  password: z.string().min(12, 'La contraseña debe tener al menos 12 caracteres'),
  first_name: z.string().min(2, 'Nombre muy corto').optional().or(z.literal('')),
  last_name: z.string().min(2, 'Apellido muy corto').optional().or(z.literal('')),
  phone: z.string().optional().or(z.literal('')),
  role: z.enum(['admin', 'staff', 'receptionist', 'client'])
})

// `updateUserSchema` se borro el 2026-09-21 por el mismo motivo que su gemelo
// de servicios: era una validacion de cliente escrita y nunca conectada a
// ningun formulario. `createUserSchema` SI se usa (lo cablea `UserService`).
// La validacion real del PATCH vive en el schema Pydantic del backend.
