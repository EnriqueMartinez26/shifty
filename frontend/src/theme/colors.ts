/**
 * Color System - Early Smartphone 2000s Theme
 * Naranja + Gris con degradados y sombras 2000s
 */

export const colors2000s = {
  // Fondos
  bg: {
    primary: '#e5e5e5',    // Fondo principal degradado top
    secondary: '#d9d9d9',  // Fondo principal degradado bottom
    button: '#f5f5f5',     // Botones sin seleccionar - top
    buttonBottom: '#ebebeb', // Botones sin seleccionar - bottom
    disabled: '#e8e8e8',   // Botones deshabilitados - top
    disabledBottom: '#dcdcdc', // Botones deshabilitados - bottom
  },

  // Naranja (seleccionado)
  orange: {
    light: '#ff8c42',      // Naranja seleccionado - top
    dark: '#e67e22',       // Naranja seleccionado - bottom
    accent: '#c85a0f',     // Naranja oscuro para títulos/labels
  },

  // Textos
  text: {
    primary: '#5a5a5a',    // Texto normal
    secondary: '#7a7a7a',  // Labels, headers
    disabled: '#b0b0b0',   // Texto deshabilitado
    onOrange: '#ffffff',   // Texto sobre naranja
  },

  // Bordes
  border: {
    default: 'rgba(0, 0, 0, 0.15)',
    light: 'rgba(0, 0, 0, 0.12)',
    hover: 'rgba(200, 90, 15, 0.3)',
  },

  // Sombras 2000s (inset + exterior)
  shadows: {
    insetLight: 'inset 0 1px 0 rgba(255, 255, 255, 0.6)',
    insetDark: 'inset 0 1px 2px rgba(0, 0, 0, 0.15)',
    insetPressed: 'inset 0 1px 2px rgba(0, 0, 0, 0.2), inset 0 -1px 0 rgba(0, 0, 0, 0.1)',
    outer: '0 1px 2px rgba(0, 0, 0, 0.08)',
    outerMedium: '0 2px 4px rgba(0, 0, 0, 0.1)',
    outerOrange: '0 2px 4px rgba(200, 90, 15, 0.25)',
  },

  // Estados específicos
  states: {
    hover: '#f9f9f9',      // Hover background - top
    hoverBottom: '#f0f0f0', // Hover background - bottom
  },
} as const;

// Estilos CSS reutilizables
export const buttonStyles2000s = {
  default: {
    background: `linear-gradient(180deg, ${colors2000s.bg.button} 0%, ${colors2000s.bg.buttonBottom} 100%)`,
    border: `1px solid ${colors2000s.border.default}`,
    color: colors2000s.text.primary,
    boxShadow: `${colors2000s.shadows.insetLight}, ${colors2000s.shadows.outer}`,
    borderRadius: '4px',
    transition: 'all 0.15s',
    cursor: 'pointer',
  },
  hover: {
    background: `linear-gradient(180deg, ${colors2000s.states.hover} 0%, ${colors2000s.states.hoverBottom} 100%)`,
    borderColor: colors2000s.border.hover,
    color: colors2000s.orange.accent,
  },
  selected: {
    background: `linear-gradient(180deg, ${colors2000s.orange.light} 0%, ${colors2000s.orange.dark} 100%)`,
    border: `1px solid ${colors2000s.orange.accent}`,
    color: colors2000s.text.onOrange,
    boxShadow: `${colors2000s.shadows.insetLight}, ${colors2000s.shadows.outerOrange}`,
  },
  disabled: {
    background: `linear-gradient(180deg, ${colors2000s.bg.disabled} 0%, ${colors2000s.bg.disabledBottom} 100%)`,
    border: `1px solid ${colors2000s.border.light}`,
    color: colors2000s.text.disabled,
    cursor: 'not-allowed',
  },
} as const;
