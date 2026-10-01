import { z } from 'zod'

// Los valores espejan los `pattern` de `ServiceBase` y los CHECK
// `ck_services_deposit_mode` / `ck_services_deposit_type` de la base. Un valor
// fuera de estas listas lo rechaza Postgres, no solo Pydantic.
const DEPOSIT_MODES = ['none', 'optional', 'required'] as const
const DEPOSIT_TYPES = ['percent', 'fixed', 'full'] as const

// D-20260930-09: el formulario rechaza lo que el backend ya rechaza
// (backend/modules/services/schemas.py). El color de 6 digitos, la duracion
// minima de 5 y el nombre minimo de 3 son mas estrictos que el backend a
// proposito; el minimo de 2 no se adopta.
export const createServiceSchema = z
  .object({
    name: z
      .string()
      .min(3, 'El nombre debe tener al menos 3 caracteres')
      .max(255, 'El nombre no puede superar los 255 caracteres'),
    description: z
      .string()
      .max(1000, 'La descripción no puede superar los 1000 caracteres')
      .optional()
      .or(z.literal('')),
    duration_minutes: z.number().min(5, 'Minimo 5 minutos').max(480, 'Maximo 8 horas'),
    price: z
      .number()
      .min(0, 'El precio no puede ser negativo')
      .max(10_000_000, 'El precio no puede superar 10.000.000'),
    color: z
      .string()
      .regex(/^#[0-9A-F]{6}$/i, 'Color invalido')
      .optional()
      .or(z.literal('')),
    image_url: z.string().url('URL invalida').optional().or(z.literal('')),
    youtube_trailer_url: z.string().url('URL invalida').optional().or(z.literal('')),
    // Los defaults son los del backend: un servicio que no configura sena
    // nace en "none" y se comporta igual que antes de exponer la politica.
    deposit_mode: z.enum(DEPOSIT_MODES).default('none'),
    deposit_type: z.enum(DEPOSIT_TYPES).default('percent'),
    deposit_amount: z
      .number()
      .min(0, 'El monto de la sena no puede ser negativo')
      .max(10_000_000, 'El monto de la sena es demasiado alto')
      .nullable()
      .optional()
  })
  .superRefine((data, ctx) => {
    // Mismo orden que `deposit_policy_error` del backend. Un porcentaje
    // mayor a 100 cobraria mas que el servicio: se rechaza con cualquier modo,
    // como el backend y el CHECK `ck_services_deposit_percent_max`.
    if (
      data.deposit_type === 'percent' &&
      data.deposit_amount !== null &&
      data.deposit_amount !== undefined &&
      data.deposit_amount > 100
    ) {
      ctx.addIssue({
        code: 'custom',
        path: ['deposit_amount'],
        message: 'El porcentaje de la seña no puede superar 100'
      })
      return
    }

    // Sin sena el monto no significa nada, y `full` quiere decir 100%: no
    // necesita monto aparte. El monto se exige solo para `percent` y `fixed`.
    if (data.deposit_mode === 'none' || data.deposit_type === 'full') {
      return
    }

    if (data.deposit_amount === null || data.deposit_amount === undefined) {
      ctx.addIssue({
        code: 'custom',
        path: ['deposit_amount'],
        message:
          data.deposit_type === 'percent'
            ? 'Indicá el porcentaje de la seña'
            : 'Indicá el monto fijo de la seña'
      })
      return
    }

    // Una sena de 0 reservaba el turno sin cobrar (o ofrecia una sena
    // opcional de 0): el backend la rechaza, y la base tambien
    // (`ck_services_deposit_amount_presente`). Un negativo ya falla con el
    // `min(0)` del campo (zod 4 corre este refine igual): aca solo queda el 0.
    if (data.deposit_amount === 0) {
      ctx.addIssue({
        code: 'custom',
        path: ['deposit_amount'],
        message: 'El monto de la seña tiene que ser mayor a 0'
      })
    }
  })

// Este schema valida solo el alta (`ServiceService.createService`). La
// edicion no tiene validacion de cliente: la valida el PATCH del backend, que
// revisa la terna de sena contra la fila solo si el PATCH la toca
// (`_validate_deposit_patch`). El comentario anterior ("el backend acepta
// hasta 10.000.000 para cualquier tipo", 2026-09-21) quedo viejo: el backend y
// la base rechazan un porcentaje mayor a 100 y una sena de 0 (B6-02, B6-03).

// `updateServiceSchema` y sus alias `z.infer` se borraron el 2026-09-21: eran
// una validacion de cliente escrita y nunca conectada a ningun formulario. La
// validacion real del PATCH vive en el schema Pydantic del backend; esto no
// protegia nada. Si se cablea el formulario de edicion, se reintroduce con su
// consumidor en el mismo commit.
