# Checklist de lanzamiento web

## Analítica GA4

- [x] Variable `VITE_GA4_MEASUREMENT_ID` configurada en GitHub Actions; el
      valor no se copia a la documentación.
- [x] El consentimiento limita la integración a `/booking/:slug` y `/b/:slug`;
      no inicia la medición en el panel ni en «Mis turnos».
- [x] Se contrastó el borrador de privacidad con el comportamiento del código y
      los ajustes observados de GA4; quedan pendientes datos legales/proveedores
      y revisión profesional.
- [ ] Mateo debe confirmar los datos factuales y la política de destinos,
      incluida la personalización publicitaria permitida en 307/307 regiones.
- [ ] Un abogado matriculado debe revisar y aprobar el texto antes de publicar.
- [x] Prueba acotada en Production el 2026-10-11: sin solicitudes antes de
      aceptar; después, petición explícita `booking_started` respondió HTTP
      204 y, por separado, GA4 mostró una recepción en Tiempo real. GA4 también
      registró `first_visit` y `session_start`. No se eligió servicio ni se
      creó una reserva o pago.
- [ ] Archivar la evidencia durable de la corrida y de los ajustes de propiedad
      (captura o export sin credenciales ni datos de clientes); por ahora el
      repositorio conserva solo el registro narrativo de la observación.
- [ ] Confirmar la fuente exacta del ID usada por Vercel y las demás
      vinculaciones de productos; no se probaron los otros cinco eventos.
- [ ] Publicar el aviso corregido solo después de las aprobaciones anteriores
      y desplegar mediante el proceso habitual.

El flujo web `Shifty` observado corresponde a `https://shifty-ar.tech` y el ID
cargado por Production coincidió con el flujo. Medición mejorada, Google
Signals y recopilación de datos proporcionados por usuarios están apagados;
ubicación/dispositivo granular está activo. No hay vínculo con Google Ads ni
etiquetas conectadas. La página legal corregida todavía no está en Production;
la prueba realizada no valida otras rutas, eventos ni recorridos.

## Marca y previews

- [x] La rama propuesta agrega `robots.txt`, la imagen OG de 1200 × 630, los
      metadatos `noindex`, Open Graph y Twitter, y los iconos derivados de la
      fuente de marca conservada en `docs/assets/`.
- [ ] Tras el merge, comprobar que `/robots.txt` devuelve `text/plain`, que
      `/og-shifty.jpg` devuelve JPEG 1200 × 630 y que el HTML inicial incluye
      `noindex`, `og:url`, `og:image` y `twitter:card`.
- [ ] Revisar el preview de WhatsApp con un slug público real. `/b/sol` era un
      slug de prueba y no valida una tienda real.
- [ ] Después del OK de merge, comprobar el build de imagen y hacer el deploy
      de producción por el runbook; el workflow de imágenes no despliega el VPS.
