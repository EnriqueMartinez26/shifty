# Analítica de reservas (GA4)

## Estado y alcance

El código usa `VITE_GA4_MEASUREMENT_ID` durante el build; no se documenta aquí su
valor. La integración solo inicia la medición en `/booking/:slug` y `/b/:slug`,
después de que la persona acepte analítica. El panel, login, recuperación de
clave, páginas legales y «Mis turnos» no son rutas elegibles ni envían eventos;
si se navega a ellas dentro de la SPA después de aceptar, el script que ya se
descargó puede permanecer hasta recargar, con la medición bloqueada.

**Estado observado el 2026-10-11:** en una sesión nueva de Production,
`/b/ejemplo` no hizo solicitudes a Google antes de elegir. Tras la aceptación
autorizada, el navegador hizo una petición explícita `booking_started` que
respondió HTTP 204; por separado, GA4 mostró una recepción en Tiempo real. GA4
también generó `first_visit` y `session_start`. No se eligió servicio ni se
creó una reserva. El ID cargado por el bundle coincidió con el flujo web
`Shifty` de `https://shifty-ar.tech`, pero no se confirmó qué fuente de
configuración usa Vercel ni se probaron los demás eventos propios. Esta
observación quedó registrada en la sesión controlada autorizada; el repo no
incluye HAR, captura de Realtime ni export de configuración para reproducirla.

En la propiedad revisada, Medición mejorada, Google Signals y la recopilación
de datos proporcionados por usuarios están desactivados; la recopilación
granular de ubicación/dispositivo está activada. La personalización publicitaria
está permitida en 307/307 regiones configurables, aunque no hay vínculo con
Google Ads ni etiquetas de sitio conectadas. La retención observada es de 2
meses para eventos y 14 meses para datos de usuario; borrar ante nueva
actividad está activado. Falta confirmar las demás vinculaciones y la fuente
del ID en Vercel. Los valores de la propiedad son observaciones reportadas del
11 de octubre, sin captura o export adjunto a este repositorio.

El aviso corregido y este documento todavía no están desplegados. La política
requiere completar los datos legales y de proveedores, aprobación factual de
Mateo y revisión profesional antes de publicarse. Esta evidencia de una prueba
acotada no constituye aprobación legal ni habilita el lanzamiento de GA4 a
clientes.

## Consentimiento y datos

Sin un ID válido, no aparece el aviso ni se carga el script. Antes de aceptar no
se crea la cola de `gtag` ni se contacta a Google. Aceptar carga la biblioteca y
permite la medición; rechazar o retirar el consentimiento bloquea nuevos envíos,
descarta cargas pendientes y elimina las cookies de esta integración que sean
accesibles desde el navegador. Si la biblioteca ya se descargó, puede permanecer
en la página hasta recargarla, aunque la medición queda bloqueada. La preferencia
se guarda en `localStorage`; si el navegador lo
bloquea, se conserva solo en memoria durante esa visita. Otras pestañas reciben
los cambios de consentimiento.

Los únicos eventos propios son `booking_started`, `service_selected`,
`slot_selected`, `availability_empty`, `booking_created` y `booking_error`.
No se pasan propiedades de formulario ni datos del turno. El identificador de
una reserva se usa solo en memoria para deduplicar y no se envía ni persiste.
La configuración reporta una página fija (`<origen>/booking`), título fijo y
referrer vacío; no usa la ruta, query, fragmento ni `document.referrer`. Google
recibe de todos modos datos técnicos de conexión y, tras aceptar, puede usar
identificadores y cookies del navegador. La integración no equivale a analítica
anónima.

Los eventos ocurridos antes de aceptar o antes de que cargue el tag se descartan.
La carga de Google es best-effort: un bloqueo, una falla de red o CSP no debe
impedir reservar. La opción `send_page_view: false` evita la vista inicial
automática del código. GA4 puede generar eventos técnicos propios como
`first_visit` y `session_start`, observados el 2026-10-11, además de los seis
eventos definidos por Shifty. La prueba de producción solo cubrió el envío y
recepción de `booking_started`; no valida los demás eventos.

## Build y CSP

El build de Docker recibe el ID desde la variable de repositorio de GitHub; para
un build local se puede definir `VITE_GA4_MEASUREMENT_ID` en el entorno de
Compose. No se agrega a `.env.example` ni a archivos versionados. Cambiarlo
requiere construir una imagen nueva. El generador de CSP acepta solo IDs con
formato `G-...`, añade los hosts exactos necesarios únicamente cuando hay un ID
y deja intacta la política cuando está vacío. No agrega comodines ni
`unsafe-inline`.

## Verificación previa a activar

1. **Pendiente:** completar y verificar identidad/contacto del responsable,
   proveedores/regiones y mecanismo de transferencia; Mateo debe aprobar esos
   hechos y un abogado matriculado debe revisar el texto antes de publicarlo.
2. **Pendiente:** confirmar la fuente exacta de la variable que usa Vercel y
   revisar con el responsable las vinculaciones restantes y el ajuste de
   personalización publicitaria permitido en 307/307 regiones.
3. **Parcialmente verificado en Production:** no hubo solicitud antes de
   aceptar; después se observó HTTP 204 para `booking_started` y recepción
   separada en Tiempo real. No hubo selección de servicio, reserva ni pago.
4. **Pendiente si se requiere cobertura completa:** validar los otros cinco
   eventos propios, retiro del consentimiento, cookies eliminables y ausencia
   de tráfico en login, panel y «Mis turnos»; los checks de código no prueban
   recepción de esos eventos en la propiedad.
5. Validar el build Docker y la CSP de la imagen candidata; esto no sustituye
   la aprobación del texto ni autoriza un despliegue.

Pruebas locales focales desde `frontend/`:

```sh
npm test -- --runInBand bookingAnalytics.test.ts AnalyticsConsent.test.tsx BookingStepDateTime.analytics.test.tsx BookingWizardContainer.test.tsx
npm run check
npm run build
```

Las pruebas locales verifican las guardas propias y los parámetros encolados;
no ejecutan la biblioteca remota ni prueban la propiedad de Analytics. Los
datos de reservas y cobros en el backend siguen siendo la fuente de verdad.

## Referencias

- [Control de vistas de página en GA4](https://developers.google.com/analytics/devguides/collection/ga4/views)
- [Medición mejorada](https://support.google.com/analytics/answer/9216061)
- [Referencia de configuración de gtag.js](https://developers.google.com/analytics/devguides/collection/ga4/reference/config)
- [Deshabilitar recolección con `ga-disable`](https://developers.google.com/tag-platform/security/guides/privacy)
