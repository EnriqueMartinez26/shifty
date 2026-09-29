import type { User, UserWriteInput } from '@domain/entities/User'
import type { CreateUserInput } from '@domain/use-cases/user/CreateUserUseCase'

import type { UserFormValues } from '../types/forms'

/**
 * Unico lugar donde el formulario de usuarios se traduce a lo que viaja
 * (FF-10). El formulario guarda `''` en los campos vacios y el backend exige
 * `min_length=1` en nombre y apellido: mandar `''` (o `'  '`) era un 422, y en
 * el telefono guardaba un texto vacio en vez de borrarlo.
 *
 * Se recorta ANTES de la validacion zod de `UserService`, asi la regla de
 * blancos vive aca y no repartida entre el modal, el contenedor y el servicio.
 */
const blankToNull = (value: string): string | null => {
  const trimmed = value.trim()
  return trimmed ? trimmed : null
}

/** Alta: un campo opcional en blanco no viaja (el caso de uso lo guarda null). */
export const toCreateUserInput = (form: UserFormValues): CreateUserInput => ({
  email: form.email.trim(),
  password: form.password,
  firstName: blankToNull(form.first_name) ?? undefined,
  lastName: blankToNull(form.last_name) ?? undefined,
  phone: blankToNull(form.phone) ?? undefined,
  role: form.role
})

/**
 * Edicion: solo viaja lo que cambio respecto de `current`. Vaciar un campo
 * que tenia valor manda `null` (borrarlo); dejarlo como estaba no lo manda.
 * Asi editar el rol de alguien sin nombre ya no reenvia un nombre invalido.
 */
export const toUserWriteInput = (form: UserFormValues, current: User): UserWriteInput => {
  const input: UserWriteInput = {}
  const firstName = blankToNull(form.first_name)
  const lastName = blankToNull(form.last_name)
  const phone = blankToNull(form.phone)
  if (firstName !== current.firstName) input.firstName = firstName
  if (lastName !== current.lastName) input.lastName = lastName
  if (phone !== current.phone) input.phone = phone
  if (form.role !== current.role.getValue()) input.role = form.role
  if (form.password) input.password = form.password
  return input
}
