import {
  AddonSelection,
  type AddonOption,
  type SelectedAddon
} from '@domain/value-objects/AddonSelection'

import { publicAddonOptions } from '@application/mappers/PublicAddonMapper'
import type { PublicService } from '@application/services/PublicBookingService'

export const sumAmounts = (a: number, b: number): number => Math.round((a + b) * 100) / 100

/** Los adicionales de UN servicio elegido, contra el catalogo vigente. */
export interface ServiceAddonsGroup {
  serviceId: string
  service: PublicService | undefined
  options: AddonOption[]
  selection: AddonSelection
  /** Lo elegido cambio en el catalogo (borrado, otro precio, otro maximo). */
  changed: boolean
  /** Habia algo elegido para este servicio. */
  hasChosen: boolean
}

/**
 * Agrupa lo elegido por servicio (un adicional sin `serviceId` es del
 * principal) y lo concilia con el catalogo de cada uno. Sin el servicio en el
 * catalogo lo elegido no se puede cobrar: si el catalogo ya llego se avisa.
 */
export const groupAddonsByService = (
  serviceIds: readonly string[],
  catalog: readonly PublicService[] | undefined,
  chosen: readonly SelectedAddon[]
): ServiceAddonsGroup[] =>
  serviceIds.map((id) => {
    const service = catalog?.find((candidate) => candidate.public_id === id)
    const mine = chosen.filter((addon) => (addon.serviceId ?? serviceIds[0]) === id)
    const hasChosen = mine.some((addon) => addon.quantity > 0)
    const options = publicAddonOptions(service)
    const { selection, changed } = service
      ? AddonSelection.reconcile(options, mine)
      : { selection: AddonSelection.empty(), changed: Boolean(catalog) && hasChosen }
    return { serviceId: id, service, options, selection, changed, hasChosen }
  })

/**
 * Las lineas para el wizard: las de un servicio sumado llevan su `serviceId`;
 * las del principal van sin marca, como siempre.
 */
export const toSelectedAddons = (
  groups: readonly Pick<ServiceAddonsGroup, 'serviceId' | 'selection'>[]
): SelectedAddon[] =>
  groups.flatMap((group, index) =>
    group.selection
      .lines()
      .map((line) => (index === 0 ? line : { ...line, serviceId: group.serviceId }))
  )

/**
 * Lo elegido con la cantidad de UN adicional de UN servicio cambiada; los
 * demas servicios quedan como estaban. Arma las lineas con `toSelectedAddons`.
 */
export const withAddonQuantity = (
  groups: readonly ServiceAddonsGroup[],
  serviceId: string,
  addonId: string,
  quantity: number
): SelectedAddon[] =>
  toSelectedAddons(
    groups.map((group) =>
      group.serviceId === serviceId
        ? {
            serviceId,
            selection: AddonSelection.create(group.options, {
              ...group.selection.toQuantities(),
              [addonId]: quantity
            })
          }
        : group
    )
  )

/** Suma de los adicionales elegidos de todos los servicios. */
export const addonsTotalOf = (groups: readonly Pick<ServiceAddonsGroup, 'selection'>[]): number =>
  groups.reduce((sum, group) => sumAmounts(sum, group.selection.total()), 0)
