import type { AddonOption } from '../../domain/value-objects/AddonSelection'
import type { PublicService } from '../services/PublicBookingService'

/**
 * Los adicionales de un servicio del portal como opciones para elegir, en su
 * orden. Vive aparte de PublicBookingService para que la pantalla no arrastre
 * el cliente HTTP al importarlo.
 */
export const publicAddonOptions = (service: PublicService | undefined): AddonOption[] =>
  [...(service?.addons ?? [])]
    .sort((a, b) => a.position - b.position)
    .map((addon) => ({
      id: addon.id,
      name: addon.name,
      unitPrice: Number(addon.unit_price),
      maxQuantity: addon.max_quantity
    }))
