/**
 * Una fecha corrupta antes lanzaba `RangeError` y llegaba a la telemetria por
 * el `Sentry.ErrorBoundary` de `App.tsx`. Degradarla a texto de respaldo dejo
 * de tumbar la pantalla, pero tambien dejo el dato corrupto sin ninguna senal:
 * nadie se entera de que la API mando algo ilegible. Esto devuelve la senal
 * sin devolver el crash.
 *
 * El destino se inyecta desde `main.tsx` en vez de importar Sentry aca. No es
 * purismo de capas: `presentation/lib` lo consumen pantallas que tienen tests
 * de componente, e importar el modulo de observabilidad arrastra `runtime-env`
 * y con el `import.meta`, que `ts-jest` no compila fuera de ese archivo
 * (regla 28 del CLAUDE.md). Sin inyeccion, agregar telemetria aca rompe toda
 * suite que renderice una pantalla que formatee una fecha.
 */

type InstantReporter = (message: string) => void

/** Sin destino configurado no se reporta: en tests eso es lo que se quiere. */
let reporter: InstantReporter | null = null

export const setUnreadableInstantReporter = (report: InstantReporter): void => {
  reporter = report
}

/** Recorte defensivo: el valor crudo va al mensaje y no se sabe que trae. */
const MAX_RAW_LENGTH = 64

/**
 * Un instante ilegible se re-renderiza en cada pasada de React. Sin este
 * registro, una sola fecha corrupta genera un evento por render.
 */
const alreadyReported = new Set<string>()

export const reportUnreadableInstant = (field: string, raw: unknown): void => {
  const value = typeof raw === 'string' ? raw.slice(0, MAX_RAW_LENGTH) : typeof raw
  const key = `${field}:${value}`
  if (alreadyReported.has(key)) return
  alreadyReported.add(key)
  reporter?.(`Instante ilegible en ${field}: ${value}`)
}

/** Solo para los tests: el registro de deduplicacion vive a nivel de modulo. */
export const resetUnreadableInstantReports = (): void => {
  alreadyReported.clear()
  reporter = null
}
