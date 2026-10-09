/**
 * Color System - Early Smartphone 2000s Theme
 * Naranja + Gris con degradados y sombras 2000s
 */

export const colors2000s = {
  // Fondos
  bg: {
    primary: '#e5e5e5', // Fondo principal degradado top
    secondary: '#d9d9d9', // Fondo principal degradado bottom
    button: '#f5f5f5', // Botones sin seleccionar - top
    buttonBottom: '#ebebeb', // Botones sin seleccionar - bottom
    disabled: '#e8e8e8', // Botones deshabilitados - top
    disabledBottom: '#dcdcdc' // Botones deshabilitados - bottom
  },

  // Naranja. light/dark son la marca (logo, barras, decoracion): blanco
  // encima da 2.31/2.85:1, asi que el texto blanco va sobre cta -> accent
  // (orangeCtaGradient). Los pares se miden en colors.contrast.test.ts.
  orange: {
    light: '#ff8c42', // Marca - top
    dark: '#e67e22', // Marca - bottom (theme-color)
    accent: '#9a4507', // Titulos, labels y links sobre claro; fondo del CTA - bottom
    cta: '#b4530a' // Fondo del CTA y de lo seleccionado - top (texto blanco)
  },

  // Textos
  text: {
    primary: '#404040', // Texto normal
    secondary: '#5c5c5c', // Labels, headers, ayudas y pies (AA sobre bg.secondary)
    disabled: '#b0b0b0', // SOLO controles deshabilitados (1.72:1): nunca contenido
    onOrange: '#ffffff' // Texto sobre naranja
  },

  // Bordes
  border: {
    default: 'rgba(0, 0, 0, 0.15)',
    light: 'rgba(0, 0, 0, 0.12)',
    hover: 'rgba(200, 90, 15, 0.3)'
  },

  // Sombras 2000s (inset + exterior)
  shadows: {
    insetLight: 'inset 0 1px 0 rgba(255, 255, 255, 0.6)',
    insetDark: 'inset 0 1px 2px rgba(0, 0, 0, 0.15)',
    insetPressed: 'inset 0 1px 2px rgba(0, 0, 0, 0.2), inset 0 -1px 0 rgba(0, 0, 0, 0.1)',
    outer: '0 1px 2px rgba(0, 0, 0, 0.08)',
    outerMedium: '0 2px 4px rgba(0, 0, 0, 0.1)',
    outerOrange: '0 2px 4px rgba(200, 90, 15, 0.25)'
  },

  // Estados específicos
  states: {
    hover: '#f9f9f9', // Hover background - top
    hoverBottom: '#f0f0f0' // Hover background - bottom
  },

  // Paleta semántica de estado (success/warning/danger/info)
  // Reemplaza los hex sueltos que se repetían ad-hoc en booking, cards y badges.
  status: {
    success: {
      light: '#10b981',
      dark: '#0f9f6e',
      accent: '#166534',
      bg: '#ecfdf5',
      border: '#bbf7d0',
      text: '#166534'
    },
    danger: {
      light: '#ef4444',
      dark: '#d13b3b',
      accent: '#b91c1c',
      bg: '#fef2f2',
      border: '#fecaca',
      text: '#b91c1c'
    },
    warning: {
      light: '#eab308',
      dark: '#b76a00',
      accent: '#92400e',
      bg: '#fffbeb',
      border: '#fde68a',
      text: '#92400e'
    },
    info: {
      light: '#3b82f6',
      dark: '#2563eb',
      accent: '#1d4ed8',
      bg: '#eff6ff',
      border: '#bfdbfe',
      text: '#1d4ed8'
    }
  }
} as const

// Fondo de todo texto blanco sobre naranja (CTA, chips y avatares
// seleccionados): 5.02:1 arriba y 6.50:1 abajo.
export const orangeCtaGradient = `linear-gradient(180deg, ${colors2000s.orange.cta} 0%, ${colors2000s.orange.accent} 100%)`

// Estilos CSS reutilizables
export const buttonStyles2000s = {
  default: {
    background: `linear-gradient(180deg, ${colors2000s.bg.button} 0%, ${colors2000s.bg.buttonBottom} 100%)`,
    border: `1px solid ${colors2000s.border.default}`,
    color: colors2000s.text.primary,
    boxShadow: `${colors2000s.shadows.insetLight}, ${colors2000s.shadows.outer}`,
    // A diferencia de sus hermanos (.hover/.selected/.disabled, que no
    // declaran radio y dejan que la clase Tailwind del que llama decida),
    // `.default` SI fija un radio propio, y por especificidad gana por
    // encima de cualquier `rounded-*` que el consumidor le ponga al lado.
    // Es intencional: varios botones alternan entre este estado y
    // `.selected` (que si respeta la clase del consumidor), asi que el
    // radio visible cambia segun el estado - no es un bug, es como quedo
    // pensado. Si alguna vez se quiere el mismo radio en los dos estados,
    // hay que decidirlo ahi explicitamente, no borrar esta linea a ciegas.
    borderRadius: '4px',
    transition: 'all 0.15s',
    cursor: 'pointer'
  },
  hover: {
    background: `linear-gradient(180deg, ${colors2000s.states.hover} 0%, ${colors2000s.states.hoverBottom} 100%)`,
    borderColor: colors2000s.border.hover,
    color: colors2000s.orange.accent
  },
  selected: {
    background: orangeCtaGradient,
    border: `1px solid ${colors2000s.orange.accent}`,
    color: colors2000s.text.onOrange,
    boxShadow: `${colors2000s.shadows.insetLight}, ${colors2000s.shadows.outerOrange}`
  },
  disabled: {
    background: `linear-gradient(180deg, ${colors2000s.bg.disabled} 0%, ${colors2000s.bg.disabledBottom} 100%)`,
    border: `1px solid ${colors2000s.border.light}`,
    color: colors2000s.text.disabled,
    cursor: 'not-allowed'
  }
} as const
