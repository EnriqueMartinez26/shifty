import type { CoverPosition } from '@application/services/StoreSettingsService'

/**
 * Encuadre de la portada (S10.1): que franja de la foto queda a la vista
 * cuando se recorta. Lo usan el portal y la vista previa del panel, para que
 * la tienda vea lo mismo que el cliente.
 */
const OBJECT_POSITION: Record<CoverPosition, string> = {
  top: 'center 20%',
  center: 'center 50%',
  bottom: 'center 80%'
}

// Sin elegir: un poco por debajo del medio, donde suele estar el trabajo en
// una foto vertical recortada a lo ancho.
const DEFAULT_OBJECT_POSITION = 'center 65%'

export const coverObjectPosition = (position: CoverPosition | null | undefined): string =>
  position ? OBJECT_POSITION[position] : DEFAULT_OBJECT_POSITION
