import { z } from 'zod'

// Los valores espejan los `pattern` de `ServiceBase` y los CHECK
// `ck_services_deposit_mode` / `ck_services_deposit_type` de la base. Un valor
// fuera de estas listas lo rechaza Postgres, no solo Pydantic.
const DEPOSIT_MODES = ['none', 'optional', 'required'] as const
const DEPOSIT_TYPES = ['percent', 'fixed', 'full'] as const

export const createServiceSchema = z
  .object({
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
    }
  })

// No hay tope de 100 para el porcentaje a proposito. El backend acepta hasta
// 10.000.000 para cualquier tipo, y una validacion de cliente mas estricta que
// el contrato deja datos legitimos imposibles de editar: un servicio con 500%
// cargado por otra via no se podria ni renombrar desde el panel. Si el tope es
// una regla de negocio deseada, va en el backend, donde tambien protege a la
// API (2026-09-21).

// `updateServiceSchema` y sus alias `z.infer` se borraron el 2026-09-21: eran
// una validacion de cliente escrita y nunca conectada a ningun formulario. La
// validacion real del PATCH vive en el schema Pydantic del backend; esto no
// protegia nada. Si se cablea el formulario de edicion, se reintroduce con su
// consumidor en el mismo commit.
