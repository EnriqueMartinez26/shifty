/* istanbul ignore file */

/**
 * Punto unico de acceso a los flags de entorno de Vite (`import.meta.env`).
 *
 * `import.meta` es sintaxis solo-ESM: ts-jest transpila a CommonJS y rompe al
 * verla en archivos de `src`. Por eso se centraliza aca y se mockea en el setup
 * de Jest (ver src/test/setup.ts), igual que runtime-env. El resto del codigo
 * consume estas funciones en vez de tocar `import.meta` directo.
 */

export const isProduction = (): boolean => import.meta.env.PROD

export const isDevelopment = (): boolean => import.meta.env.DEV
