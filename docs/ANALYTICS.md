# Analítica de reservas (GA4)

## Estado y alcance

El código usa `VITE_GA4_MEASUREMENT_ID` como variable de build. El repositorio
tiene configurado `G-KDKJ9FX8VZ` en esa variable; el ID es público y no es una
credencial. No se incluye el valor en el código fuente. La analítica solo se
activa en `/booking/:slug` y `/b/:slug`, y solo después de que la persona la
acepte. No se carga en el panel, login, recuperación de clave, páginas legales
ni «Mis turnos».

La política de privacidad incluye una descripción propuesta de GA4. Su revisión
por el responsable queda pendiente antes de habilitar el servicio para clientes.
El cambio no configura la propiedad de Google, no verifica una cuenta real y no
despliega imágenes.

## Consentimiento y datos

Sin un ID válido, no aparece el aviso ni se carga el script. Antes de aceptar no
se crea la cola de `gtag` ni se contacta a Google. Aceptar carga la biblioteca y
permite la medición; rechazar o retirar el consentimiento bloquea nuevos envíos,
descarta cargas pendientes y elimina las cookies `shifty_ga*` accesibles desde
el navegador. La preferencia se guarda en `localStorage`; si el navegador lo
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
automática del código; antes de habilitar el build, el responsable debe revisar
la propiedad y desactivar Medición mejorada y destinos publicitarios para evitar
recolección adicional fuera del alcance documentado.

## Build y CSP

El build de Docker recibe el ID desde la variable de repositorio de GitHub; para
un build local se puede definir `VITE_GA4_MEASUREMENT_ID` en el entorno de
Compose. No se agrega a `.env.example` ni a archivos versionados. Cambiarlo
requiere construir una imagen nueva. El generador de CSP acepta solo IDs con
formato `G-...`, añade los hosts exactos necesarios únicamente cuando hay un ID
y deja intacta la política cuando está vacío. No agrega comodines ni
`unsafe-inline`.

## Verificación previa a activar

1. Revisar y aprobar el texto de privacidad y las condiciones aplicables al uso
   de Google Analytics.
2. Confirmar en la propiedad real que Medición mejorada y destinos publicitarios
   no amplían los eventos ni los datos recogidos.
3. En un entorno de prueba con el ID real, comprobar en DevTools que sin elegir
   no hay solicitudes a Google; rechazar tampoco las genera; aceptar carga un
   único script; retirar el consentimiento bloquea futuros eventos.
4. Inspeccionar eventos y solicitudes: solo los seis eventos documentados,
   página fija, sin ruta de tienda, query, fragmento, referrer ni datos del
   formulario. Probar además `/login`, panel y «Mis turnos» después de aceptar.
5. Validar el build Docker y la CSP de la imagen que se pretenda publicar.

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
