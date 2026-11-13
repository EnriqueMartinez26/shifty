/**
 * Reabre el aviso de analitica desde el pie del portal. El aviso vive en
 * `AnalyticsConsent` (montado una vez en App) y escucha este evento: asi el
 * enlace del pie no necesita compartir estado con el.
 */
export const ANALYTICS_PREFERENCES_EVENT = 'shifty:analytics-preferences'

export const openAnalyticsPreferences = (): void => {
  window.dispatchEvent(new Event(ANALYTICS_PREFERENCES_EVENT))
}
