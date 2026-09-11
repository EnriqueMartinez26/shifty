import type { CSSProperties } from 'react'

import { colors2000s } from '../../theme/colors'

// Superficies 2000s: fondo + borde + sombra + radio, un solo lugar.
//
// Esto eran 16 funciones que repetian la misma formula (background, border,
// boxShadow) con variaciones minimas y sin ningun vocabulario compartido:
// cada una decidia por su cuenta que color de borde y que combinacion de
// sombra usar, asi que una tienda visual (p.ej. "todos los paneles usan el
// mismo radio") requeria auditar 16 lugares a mano en vez de uno. La
// variacion real nunca fueron 16 formas, fueron 4 valores.
//
// createSurfaceStyle() es el unico lugar que arma esos 4 valores. Los
// nombres de abajo (create2000sPanelStyle, createBookingInputStyle, etc.)
// se conservan tal cual porque 23 archivos ya los importan por ese nombre y
// esos nombres siguen siendo el vocabulario correcto del dominio (un
// "panel" y una "surface de booking" son conceptos distintos aunque hoy
// compartan la misma receta) - lo que cambia es que ahora son un alias de
// una linea a la formula compartida, no una copia de su cuerpo.

const SURFACE_BACKGROUNDS = {
  brand: `linear-gradient(180deg, ${colors2000s.bg.button} 0%, ${colors2000s.bg.buttonBottom} 100%)`,
  orange: `linear-gradient(180deg, ${colors2000s.orange.light} 0%, ${colors2000s.orange.dark} 100%)`,
  plain: '#ffffff'
} as const

const SURFACE_SHADOWS = {
  // Panel que se levanta del fondo (bevel + sombra exterior marcada).
  raised: `${colors2000s.shadows.insetLight}, ${colors2000s.shadows.outerMedium}`,
  // Variante mas sutil del mismo levantado (choice card sin seleccionar).
  raisedSoft: `${colors2000s.shadows.insetLight}, ${colors2000s.shadows.outer}`,
  // CTA naranja (choice card seleccionada, boton de volver del wizard).
  raisedOrange: `${colors2000s.shadows.insetLight}, ${colors2000s.shadows.outerOrange}`,
  // Fila de lista: apenas se despega del fondo, sin sombra exterior.
  flush: colors2000s.shadows.insetLight,
  // Input o caja "hundida" en la superficie.
  pressed: colors2000s.shadows.insetDark,
  // Card suelta que flota sobre el fondo sin bevel.
  lifted: colors2000s.shadows.outer
} as const

export interface SurfaceStyleOptions {
  background?: string
  borderColor?: string
  borderStyle?: 'solid' | 'dashed'
  boxShadow?: string
  borderRadius?: number
  color?: string
}

export const createSurfaceStyle = ({
  background = SURFACE_BACKGROUNDS.plain,
  borderColor = colors2000s.border.light,
  borderStyle = 'solid',
  boxShadow = SURFACE_SHADOWS.pressed,
  borderRadius,
  color
}: SurfaceStyleOptions = {}): CSSProperties => ({
  background,
  border: `1px ${borderStyle} ${borderColor}`,
  boxShadow,
  ...(borderRadius !== undefined ? { borderRadius } : {}),
  ...(color ? { color } : {})
})

// --- Paneles: la superficie grande que envuelve una seccion completa ---

export const create2000sPanelStyle = (): CSSProperties =>
  createSurfaceStyle({
    background: SURFACE_BACKGROUNDS.brand,
    borderColor: colors2000s.border.default,
    boxShadow: SURFACE_SHADOWS.raised
  })

// Un modal es un panel mostrado en un overlay: misma receta, mismo nombre
// para el caso de uso. No hay diferencia real que amerite una copia.
export const create2000sModalSurfaceStyle = create2000sPanelStyle

export const createDashboardPanelStyle = (): CSSProperties => ({
  ...create2000sPanelStyle(),
  borderRadius: 8,
  minWidth: 0,
  overflow: 'hidden'
})

// --- Inputs: campo de formulario, superficie "hundida" ---

export const create2000sInputStyle = (): CSSProperties =>
  createSurfaceStyle({
    borderColor: colors2000s.border.default,
    boxShadow: SURFACE_SHADOWS.pressed,
    color: colors2000s.text.primary
  })

export const create2000sModalInputStyle = (): CSSProperties => ({
  ...create2000sInputStyle(),
  outline: 'none'
})

export const createBookingInputStyle = (): CSSProperties => ({
  ...create2000sInputStyle(),
  borderRadius: 6
})

export const createSettingsInputStyle = create2000sInputStyle

// --- Cards: contenido mas chico anidado dentro de un panel ---

export const create2000sInnerCardStyle = (): CSSProperties =>
  createSurfaceStyle({ boxShadow: SURFACE_SHADOWS.lifted })

export const create2000sListCardStyle = (
  background: string = SURFACE_BACKGROUNDS.plain,
  borderColor: string = colors2000s.border.light
): CSSProperties =>
  createSurfaceStyle({ background, borderColor, boxShadow: SURFACE_SHADOWS.pressed })

export const createDashboardListItemStyle = (
  borderColor: string,
  background: string,
  padding = 16
): CSSProperties => ({
  padding,
  ...createSurfaceStyle({
    background,
    borderColor,
    boxShadow: SURFACE_SHADOWS.flush,
    borderRadius: 6
  })
})

export const createBookingSurfaceStyle = (): CSSProperties =>
  createSurfaceStyle({
    borderColor: colors2000s.border.light,
    boxShadow: SURFACE_SHADOWS.pressed,
    borderRadius: 8
  })

export const createBookingAccentBoxStyle = (
  background: string,
  borderColor: string,
  color: string = colors2000s.text.primary
): CSSProperties =>
  createSurfaceStyle({
    background,
    borderColor,
    boxShadow: SURFACE_SHADOWS.pressed,
    borderRadius: 6,
    color
  })

export const create2000sEmptyStateStyle = (): CSSProperties =>
  createSurfaceStyle({
    borderColor: colors2000s.border.default,
    borderStyle: 'dashed',
    boxShadow: SURFACE_SHADOWS.pressed
  })

// --- Estado seleccionable: card que cambia de aspecto segun `isSelected` ---

// Igual que el boton de volver: el `border-width`/`border-style` los pone
// la clase Tailwind del elemento, esto solo aporta color+fondo+sombra. Por
// eso NO pasa por createSurfaceStyle (que siempre emite el shorthand
// `border` completo) - hacerlo cambiaria que propiedad CSS se emite.
export const createBookingChoiceCardStyle = (isSelected: boolean): CSSProperties => ({
  background: isSelected ? SURFACE_BACKGROUNDS.orange : SURFACE_BACKGROUNDS.brand,
  borderColor: isSelected ? colors2000s.orange.accent : colors2000s.border.default,
  borderRadius: 6,
  boxShadow: isSelected ? SURFACE_SHADOWS.raisedOrange : SURFACE_SHADOWS.raisedSoft
})

// Boton tematico (no una superficie con borde real: el `border` estructural
// lo pone la clase Tailwind del boton, esto solo aporta el color). Se deja
// fuera de createSurfaceStyle a proposito - forzarlo ahi cambiaria que
// propiedad CSS emite (`border` completo en vez de solo `borderColor`).
export const createBookingBackButtonStyle = (): CSSProperties => ({
  background: SURFACE_BACKGROUNDS.orange,
  borderColor: colors2000s.orange.accent,
  boxShadow: SURFACE_SHADOWS.raisedOrange,
  color: '#ffffff'
})
