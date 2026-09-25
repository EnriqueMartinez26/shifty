import React, { useMemo, useState } from 'react'

import type { StoreFeatureFlags, StoreSettings } from '@application/services/StoreSettingsService'

import {
  buildSettingsBase,
  mergeDraft,
  narrowDraft,
  type SettingsFormData
} from '../lib/settingsDraft'

/**
 * El formulario de Configuracion, como base del servidor + borrador local.
 *
 * No hay ningun efecto que escriba el formulario: `formData` se deriva en el
 * render, asi que un refetch de ['store-settings'] no puede pisar lo que el
 * admin todavia no guardo. Solo gana en las claves que no estan en el
 * borrador.
 *
 * `setFormData` mantiene la firma de `useState` (objeto o funcion) para que
 * los llamados de la pagina sigan como estaban: recibe el formulario
 * completo y lo reduce al borrador comparando contra el servidor.
 */
export const useSettingsForm = (
  store: StoreSettings | undefined,
  flags: StoreFeatureFlags | undefined
) => {
  const [draft, setDraft] = useState<Partial<SettingsFormData>>({})

  const base = useMemo(() => (store ? buildSettingsBase(store, flags) : null), [store, flags])
  const formData = useMemo(() => (base ? mergeDraft(base, draft) : null), [base, draft])

  const setFormData: React.Dispatch<React.SetStateAction<SettingsFormData | null>> = (update) => {
    if (!base) return
    setDraft((previous) => {
      const next = typeof update === 'function' ? update(mergeDraft(base, previous)) : update
      // `null` es "no cambies nada", NO "vacia el formulario": es lo que
      // devuelve el guard `if (!prev) return prev` de `handleLogoUpload`
      // cuando todavia no hay formulario. No es un bug ni hay que "arreglarlo".
      if (!next) return previous
      return narrowDraft(base, next)
    })
  }

  return {
    // `base` se expone porque el plan de guardado compara contra el servidor:
    // con `formData` (que ya tiene el borrador encima) ningun flag figuraria
    // como cambiado y la mitad de funciones nunca se mandaria.
    base,
    formData,
    setFormData,
    draft,
    hasChanges: Object.keys(draft).length > 0,
    resetDraft: () => setDraft({})
  }
}
