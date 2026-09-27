import { z } from 'zod'

export const createUserSchema = z.object({
  email: z.string().email('Email inválido'),
  // Mismo piso que `UserCreate` en el backend (min_length=12). La fuerza
  // (letra, numero, denylist) la decide el backend; aca solo el largo.
  password: z.string().min(12, 'La contraseña debe tener al menos 12 caracteres'),
  // Mismos topes que `UserCreate` (min_length=1, max_length=100/50). Un campo
  // en blanco NO llega aca: `presentation/lib/userFormPayload` lo recorta y lo
  // vuelve ausente antes; `''` era un 422 del backend (FF-10).
  first_name: z.string().min(1).max(100, 'Nombre muy largo').optional(),
  last_name: z.string().min(1).max(100, 'Apellido muy largo').optional(),
  phone: z.string().min(1).max(50, 'Teléfono muy largo').optional(),
  role: z.enum(['admin', 'staff', 'receptionist', 'client'])
})

// `updateUserSchema` se borro el 2026-09-21 por el mismo motivo que su gemelo
// de servicios: era una validacion de cliente escrita y nunca conectada a
// ningun formulario. `createUserSchema` SI se usa (lo cablea `UserService`).
// La validacion real del PATCH vive en el schema Pydantic del backend.
