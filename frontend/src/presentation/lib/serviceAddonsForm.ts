import type { ServiceAddon } from '@domain/entities/ServiceAddon'

import { createUuid } from '@shared/utils/uuid'

import type { ServiceAddonFormValue } from '../types/forms'

/** Los adicionales guardados como filas del formulario, con su id. */
export const toAddonFormValues = (addons: readonly ServiceAddon[]): ServiceAddonFormValue[] =>
  addons.map((addon) => ({
    key: addon.id ?? createUuid(),
    id: addon.id,
    name: addon.name,
    unitPrice: addon.unitPrice,
    maxQuantity: addon.maxQuantity
  }))

/**
 * Si la lista del formulario difiere de la guardada (alta, baja, orden o
 * cualquier campo). Sin cambios, la edicion no manda `addons`: editar solo la
 * descripcion no toca los adicionales.
 */
export const addonsChanged = (
  saved: readonly ServiceAddon[],
  edited: readonly ServiceAddonFormValue[]
): boolean =>
  saved.length !== edited.length ||
  edited.some((row, index) => {
    const addon = saved[index]
    return (
      !addon ||
      addon.id !== row.id ||
      addon.name !== row.name.trim() ||
      addon.unitPrice !== row.unitPrice ||
      addon.maxQuantity !== row.maxQuantity
    )
  })
