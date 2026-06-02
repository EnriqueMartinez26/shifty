import React from "react";

/**
 * Icon2000s — Wrapper de íconos con acabado skeuomórfico "Early Smartphone 2000s"
 *
 * Renderiza paths SVG de @mdi/js directamente (sin @mdi/react),
 * y aplica filtros CSS de profundidad según el estado del ícono:
 *   - "idle"    → relieve suave elevado
 *   - "active"  → glow naranja brillante
 *   - "pressed" → hundido (sombra invertida)
 *   - "muted"   → gris sin relieve
 *
 * Uso:
 *   import { mdiHome } from "@mdi/js";
 *   <Icon2000s path={mdiHome} size={22} variant="active" />
 */

export type IconVariant = "idle" | "active" | "pressed" | "muted";

interface Icon2000sProps {
  /** Path SVG de @mdi/js — ej: mdiHome, mdiCalendar, etc. */
  path: string;
  /** Tamaño en píxeles. Default: 22 */
  size?: number;
  /** Variante visual que determina el filtro CSS aplicado */
  variant?: IconVariant;
  /** Color base del fill. Si no se especifica, lo determina la variante */
  color?: string;
  className?: string;
  style?: React.CSSProperties;
}

/** Filtros drop-shadow por variante — el núcleo del efecto skeuomórfico */
const FILTER_MAP: Record<IconVariant, string> = {
  // Borde superior claro (highlight) + sombra inferior suave → ícono en relieve neutro
  idle: [
    "drop-shadow(0 1px 0 rgba(255,255,255,0.85))",
    "drop-shadow(0 -1px 0 rgba(0,0,0,0.08))",
    "drop-shadow(0 1px 2px rgba(0,0,0,0.12))",
  ].join(" "),

  // Glow naranja + highlight blanco superior → ícono "encendido"
  active: [
    "drop-shadow(0 0 5px rgba(255,140,66,0.7))",
    "drop-shadow(0 1px 0 rgba(255,255,255,0.5))",
    "drop-shadow(0 2px 4px rgba(200,90,15,0.4))",
  ].join(" "),

  // Sombra invertida → ícono "hundido/presionado"
  pressed: [
    "drop-shadow(0 -1px 0 rgba(255,255,255,0.4))",
    "drop-shadow(0 1px 2px rgba(0,0,0,0.3))",
  ].join(" "),

  // Sin filtro → deshabilitado
  muted: "none",
};

const COLOR_MAP: Record<IconVariant, string> = {
  idle:    "#7a7a7a",
  active:  "#ffffff",
  pressed: "#c85a0f",
  muted:   "#b0b0b0",
};

export const Icon2000s: React.FC<Icon2000sProps> = ({
  path,
  size = 22,
  variant = "idle",
  color,
  className = "",
  style = {},
}) => {
  const fill   = color ?? COLOR_MAP[variant];
  const filter = FILTER_MAP[variant];

  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      width={size}
      height={size}
      className={className}
      style={{
        filter,
        transition: "filter 0.15s ease",
        flexShrink: 0,
        display: "inline-block",
        verticalAlign: "middle",
        ...style,
      }}
      aria-hidden="true"
    >
      <path d={path} fill={fill} />
    </svg>
  );
};

/**
 * LucideIcon2000s — Aplica los mismos filtros CSS skeuomórficos
 * a cualquier componente de ícono de Lucide-React.
 *
 * Uso:
 *   import { Settings } from "lucide-react";
 *   <LucideIcon2000s icon={Settings} size={20} variant="active" />
 */
interface LucideIcon2000sProps {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  icon: React.ComponentType<any>;
  size?: number;
  variant?: IconVariant;
  color?: string;
  className?: string;
  style?: React.CSSProperties;
}

export const LucideIcon2000s: React.FC<LucideIcon2000sProps> = ({
  icon: LucideComponent,
  size = 20,
  variant = "idle",
  color,
  className = "",
  style = {},
}) => {
  const fill   = color ?? COLOR_MAP[variant];
  const filter = FILTER_MAP[variant];

  return (
    <LucideComponent
      size={size}
      color={fill}
      className={className}
      style={{
        filter,
        transition: "filter 0.15s ease",
        flexShrink: 0,
        ...style,
      }}
    />
  );
};

export default Icon2000s;
