import { z } from 'zod'

// Los valores espejan los `pattern` de `ServiceBase` y los CHECK
// `ck_services_deposit_mode` / `ck_services_deposit_type` de la base. Un valor
// fuera de estas listas lo rechaza Postgres, no solo Pydantic.
const DEPOSIT_MODES = ['none', 'optional', 'required'] as const
const DEPOSIT_TYPES = ['percent', 'fixed', 'full'] as const

// D-20260930-09: el formulario rechaza lo que el backend ya rechaza
// (backend/modules/services/schemas.py), al crear y al editar. El color de 6
// digitos, la duracion minima de 5 y el nombre minimo de 3 son mas estrictos
// que el backend a proposito; el minimo de 2 no se adopta.
const nameSchema = z
  .string()
  .min(3, 'El nombre debe tener al menos 3 caracteres')
  .max(255, 'El nombre no puede superar los 255 caracteres')
const descriptionSchema = z
  .string()
  .max(1000, 'La descripción no puede superar los 1000 caracteres')
const durationSchema = z.number().min(5, 'Mínimo 5 minutos').max(480, 'Máximo 8 horas')
const priceSchema = z
  .number()
  .min(0, 'El precio no puede ser negativo')
  .max(10_000_000, 'El precio no puede superar 10.000.000')
const colorSchema = z
  .string()
  .regex(/^#[0-9A-F]{6}$/i, 'Color inválido')
  .or(z.literal(''))
const urlSchema = z.string().url('URL inválida').or(z.literal(''))
const depositAmountSchema = z
  .number()
  .min(0, 'El monto de la seña no puede ser negativo')
  .max(10_000_000, 'El monto de la seña es demasiado alto')
  .nullable()
  .optional()

interface DepositFields {
  deposit_mode?: (typeof DEPOSIT_MODES)[number]
  deposit_type?: (typeof DEPOSIT_TYPES)[number]
  deposit_amount?: number | null
}

/**
 * La terna de sena, con el criterio de `deposit_policy_error` del backend.
 * `absentAmountIsMissing`: en el alta un monto ausente es "sin monto"; en el
 * PATCH es "el de la fila", que el cliente no ve y valida el backend
 * (`_validate_deposit_patch`). Igual con modo o tipo ausentes.
 */
const depositPolicyIssue = (
  data: DepositFields,
  absentAmountIsMissing: boolean
): string | undefined => {
  const amount = data.deposit_amount
  // Un porcentaje mayor a 100 cobraria mas que el servicio: se rechaza con
  // cualquier modo, como el backend y el CHECK `ck_services_deposit_percent_max`.
  if (data.deposit_type === 'percent' && typeof amount === 'number' && amount > 100) {
    return 'El porcentaje de la seña no puede superar 100'
  }

  // Sin sena el monto no significa nada, y `full` quiere decir 100%: no
  // necesita monto aparte. El monto se exige solo para `percent` y `fixed`.
  if (data.deposit_mode === undefined || data.deposit_type === undefined) return undefined
  if (data.deposit_mode === 'none' || data.deposit_type === 'full') return undefined

  if (amount === null || (amount === undefined && absentAmountIsMissing)) {
    return data.deposit_type === 'percent'
      ? 'Indicá el porcentaje de la seña'
      : 'Indicá el monto fijo de la seña'
  }

  // Una sena de 0 reservaba el turno sin cobrar (o ofrecia una sena opcional
  // de 0): el backend la rechaza, y la base tambien
  // (`ck_services_deposit_amount_presente`). Un negativo ya falla con el
  // `min(0)` del campo (zod 4 corre este refine igual): aca solo queda el 0.
  if (amount === 0) return 'El monto de la seña tiene que ser mayor a 0'
  return undefined
}

export const createServiceSchema = z
  .object({
    name: nameSchema,
    description: descriptionSchema.optional(),
    duration_minutes: durationSchema,
    price: priceSchema,
    color: colorSchema.optional(),
    image_url: urlSchema.optional(),
    youtube_trailer_url: urlSchema.optional(),
    // Los defaults son los del backend: un servicio que no configura sena
    // nace en "none" y se comporta igual que antes de exponer la politica.
    deposit_mode: z.enum(DEPOSIT_MODES).default('none'),
    deposit_type: z.enum(DEPOSIT_TYPES).default('percent'),
    deposit_amount: depositAmountSchema
  })
  .superRefine((data, ctx) => {
    const message = depositPolicyIssue(data, true)
    if (message) ctx.addIssue({ code: 'custom', path: ['deposit_amount'], message })
  })

/**
 * El PATCH de `ServiceService.updateService`, sobre el payload snake_case que
 * de verdad viaja (`ServiceMapper.toWritePayload`). Semantica de PATCH: lo
 * ausente no se valida y `null` borra solo donde `ServiceUpdate` lo deja; en
 * las columnas NOT NULL el backend responde 422 (B6-04) y aca tambien falla.
 * `image_url` no se valida como URL: una imagen subida vuelve como ruta
 * relativa de medios, y la valida `media.resolve_image_link`.
 */
export const updateServiceSchema = z
  .object({
    name: nameSchema.optional(),
    description: descriptionSchema.nullable().optional(),
    duration_minutes: durationSchema.optional(),
    price: priceSchema.optional(),
    color: colorSchema.nullable().optional(),
    image_url: z.string().nullable().optional(),
    youtube_trailer_url: urlSchema.nullable().optional(),
    deposit_mode: z.enum(DEPOSIT_MODES).optional(),
    deposit_type: z.enum(DEPOSIT_TYPES).optional(),
    deposit_amount: depositAmountSchema,
    is_active: z.boolean().optional()
  })
  .superRefine((data, ctx) => {
    const message = depositPolicyIssue(data, false)
    if (message) ctx.addIssue({ code: 'custom', path: ['deposit_amount'], message })
  })

/**
 * Los mensajes de una validacion de cliente (zod) que llego envuelta.
 * `BaseService.handleError` convierte el ZodError en un Error plano y lo guarda
 * en `originalError`; dentro de `execute` se envuelve otra vez. Solo se
 * devuelven textos de un ZodError: son los de estos schemas, nunca del
 * servidor (regla 20).
 */
export const getClientValidationMessages = (error: unknown): string[] => {
  let current: unknown = error
  for (let depth = 0; depth < 5 && typeof current === 'object' && current !== null; depth += 1) {
    if (current instanceof z.ZodError) return current.issues.map((issue) => issue.message)
    current = (current as { originalError?: unknown }).originalError
  }
  return []
}
