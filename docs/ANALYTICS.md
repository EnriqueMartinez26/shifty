# Analítica de reservas (GA4)

Descripción de lo que el código hace hoy. Si el código y este archivo difieren,
gana el código. Todo vive en el frontend: no hay endpoint de analítica ni
consentimiento de analítica en el backend.

## Alcance

- **Solo el portal público de reservas**: rutas `/booking/:slug` y `/b/:slug`
  (`isBookingAnalyticsPath`, `frontend/src/infrastructure/analytics/bookingAnalytics.ts`).
  No se carga en el panel, login, «Mis turnos» ni páginas legales: al salir de
  esas rutas se bloquea el tag y no se envía nada.
- **Solo con ID válido**: sin `VITE_GA4_MEASUREMENT_ID` (o con un valor que no
  cumpla `G-[A-Z0-9]{4,20}`) no aparece el aviso ni se carga nada.
- **Solo tras consentimiento explícito** (ver abajo).

## Configuración del ID

`VITE_GA4_MEASUREMENT_ID` es una variable de build de Vite, leída en un único
lugar (`frontend/src/shared/utils/env.ts::getGa4MeasurementId`). No es una
credencial. Cadena: variable de repositorio de GitHub
(`.github/workflows/build-images.yml`, build-arg) o entorno de Compose
(`docker-compose.yml`) → `ARG`/`ENV` en `frontend/Dockerfile` → bundle.
Cambiarlo exige construir una imagen nueva. Vacío = analítica apagada.

La CSP se genera en el mismo build (`frontend/configure-analytics-csp.mjs`):
con ID agrega solo `https://www.googletagmanager.com` a `script-src` y
`https://www.google-analytics.com` / `https://region1.google-analytics.com` a
`connect-src` e `img-src`; sin ID deja la política original; un ID malformado
rompe el build. Sin comodines ni `unsafe-inline`.
Pruebas: `frontend/configure-analytics-csp.test.mjs` (`npm run test:csp`) y
`backend/tests/unit/test_ga4_build_contract.py` (cableado CI/compose/Dockerfile).

## Consentimiento

UI: `frontend/src/presentation/components/organisms/AnalyticsConsent.tsx`.
Botones «Aceptar analítica» / «Rechazar analítica» (misma presentación) y, una
vez elegido, el botón «Preferencias de analítica» para cambiar la decisión.

- Se guarda en `localStorage`, clave `shifty:analytics-consent:v1`, valores
  `accepted` | `rejected`. La `v1` está en el nombre de la clave: cambiar el
  alcance del consentimiento implica una clave nueva (no hay versionado de otro
  tipo). Con storage bloqueado la elección vive en memoria durante la visita.
- Es solo del navegador. **No pasa por el backend.** Los tests
  `test_consentimiento_en_el_servidor.py` y `test_consentimiento_versionado.py`
  son del consentimiento de términos y política de privacidad de la reserva
  (`accepts_terms`, `terms_version`, `privacy_version`), no de la analítica.
- Otras pestañas se sincronizan por el evento `storage`; al volver al portal se
  relee la preferencia, así una revocación en otra pestaña se respeta.
- Antes de aceptar (o tras rechazar) no se crea `gtag`/`dataLayer` ni se
  contacta a Google.

## Qué se envía

Al aceptar se inserta `https://www.googletagmanager.com/gtag/js?id=<ID>`
(`async`, `referrerPolicy = 'no-referrer'`) y se configura:

- `consent default`: `analytics_storage: granted` (solo se llega ahí tras
  aceptar), `ad_storage`, `ad_user_data` y `ad_personalization`: `denied`.
- `config`: `send_page_view: false`, `allow_google_signals: false`,
  `allow_ad_personalization_signals: false`, `ignore_referrer: true`,
  parámetros de campaña vacíos, cookies con prefijo `shifty`, sin dominio y con
  vencimiento de 30 días.
- Página enmascarada: `page_location = <origen>/booking` (sin slug de tienda,
  query ni fragmento), `page_referrer = ''`, `page_title = 'Reserva de turno'`.
  Nunca se usan `location`, `document.title` ni `document.referrer`.
- Eventos (únicos permitidos, lista cerrada en `EVENTS`): `booking_started`
  (al activarse), `service_selected`, `slot_selected`, `availability_empty`,
  `booking_error` y `booking_created`. Disparados desde
  `BookingWizardContainer.tsx`. Cada evento lleva solo `send_to` y los tres
  campos de página; ningún dato del formulario, turno, tienda, servicio ni
  profesional. El `public_id` de la reserva sirve solo para deduplicar
  `booking_created` en memoria y no sale ni se persiste.
- Los eventos previos a aceptar o previos a que cargue el tag se descartan.

Sobre los parámetros de red (`npa=1`, `gcs=G101`): el código no los escribe; los
deriva la biblioteca de Google de la configuración anterior (anuncios denegados
y personalización apagada). Ninguna prueba del repo los fija; verificarlos en
DevTools (paso 3 abajo). La política de privacidad (`Legal.tsx`, sección 5)
afirma «no personalizar anuncios», así que esa verificación respalda el texto.

## Cómo se apaga

- **Para todos**: build sin `VITE_GA4_MEASUREMENT_ID` (nueva imagen).
- **Una persona**: «Preferencias de analítica» → «Rechazar analítica». Pone
  `ga-disable-<ID>`, descarta la cola pendiente, bloquea envíos y borra las
  cookies `shifty_ga*` accesibles; no borra lo que Google ya recibió.
- Un tag bloqueado, falla de red o de CSP nunca interrumpe la reserva
  (`try/catch` en cada envío; `onerror` apaga la integración).

## Garantías de privacidad y sus pruebas

| Garantía | Prueba |
| --- | --- |
| Sin script ni cola antes de aceptar; rechazar no contacta a Google | `bookingAnalytics.test.ts` |
| Solo eventos permitidos, página fija, sin datos de reserva ni formulario | `bookingAnalytics.test.ts` |
| `public_id` no se transmite ni se persiste | `bookingAnalytics.test.ts` |
| Revocar bloquea eventos y borra solo cookies `shifty_ga*` | `bookingAnalytics.test.ts` |
| Salir a login/panel/«Mis turnos» bloquea el tag | `bookingAnalytics.test.ts`, `AnalyticsConsent.test.tsx` |
| Revocación durante la carga o en otra pestaña se respeta | `bookingAnalytics.test.ts` |
| Fallos de Google no rompen la reserva | `bookingAnalytics.test.ts` |
| Sin ID válido no hay aviso | `AnalyticsConsent.test.tsx` |
| Eventos del flujo de reserva | `BookingStepDateTime.analytics.test.tsx` |

Estas pruebas verifican las guardas propias y lo que se encola en `gtag`; no
ejecutan la biblioteca remota ni la propiedad de Analytics.

## Configuración de la propiedad GA4 (fuera del código)

No verificable desde el repo. Estado registrado en `docs/legal/README.md` y
`docs/legal/POLITICA_DE_PRIVACIDAD.md`: Medición mejorada apagada (2026-10-10);
Google signals, datos proporcionados por usuarios y vinculaciones con Google Ads
apagados (2026-10-08), a reconfirmar antes de habilitar clientes. Estos
controles son del lado de Google: el código no los garantiza.

## Verificación antes de activar

1. Texto de privacidad revisado por el responsable (pendiente de OK; ver
   `docs/legal/`).
2. Reconfirmar los controles de la propiedad listados arriba.
3. En un entorno con el ID real, con DevTools: sin elegir o rechazando no hay
   solicitudes a Google; aceptar carga un único script; las solicitudes llevan
   página `/booking`, sin slug, query ni referrer, y `npa=1`/`gcs=G101`;
   retirar el consentimiento detiene los envíos. Probar `/login`, panel y
   «Mis turnos» tras aceptar: sin tráfico.
4. Validar la CSP de la imagen que se publique.

Desde `frontend/`:

```sh
npm test -- --runInBand bookingAnalytics.test.ts AnalyticsConsent.test.tsx BookingStepDateTime.analytics.test.tsx BookingWizardContainer.test.tsx
npm run test:csp
npm run check
```

Los datos de reservas y cobros del backend siguen siendo la fuente de verdad.

## Referencias

- [Control de vistas de página en GA4](https://developers.google.com/analytics/devguides/collection/ga4/views)
- [Referencia de configuración de gtag.js](https://developers.google.com/analytics/devguides/collection/ga4/reference/config)
- [Deshabilitar recolección con `ga-disable`](https://developers.google.com/tag-platform/security/guides/privacy)
