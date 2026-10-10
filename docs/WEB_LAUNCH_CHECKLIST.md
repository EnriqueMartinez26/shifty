# Checklist de lanzamiento web

## Analítica GA4

- [x] Medición ID configurado en GitHub como `VITE_GA4_MEASUREMENT_ID`:
      `G-KDKJ9FX8VZ`.
- [x] El consentimiento limita la integración a `/booking/:slug` y `/b/:slug`;
      no se monta en el panel ni en «Mis turnos».
- [x] Se preparó texto propuesto para la política sobre el proveedor, el
      consentimiento, las cookies y los datos técnicos que recibe.
- [ ] Revisión y aprobación del texto de privacidad por el responsable.
- [x] Propiedad real verificada el 2026-10-10: flujo `Shifty`, dominio
      `https://shifty-ar.tech`, ID `G-KDKJ9FX8VZ`, coincidente con la
      variable de GitHub. Medición mejorada apagada (reconfirmada el
      2026-10-10). Google signals, recogida de datos proporcionados por
      usuarios y vinculaciones con Google Ads se verificaron apagados el
      2026-10-08; reconfirmarlos antes de activar.
- [ ] Reconfirmar esos controles antes de habilitar GA4 para clientes.
- [ ] Ejecutar la prueba de red descrita en [ANALYTICS.md](ANALYTICS.md) con el
      ID y dominio reales después de publicar el cambio.
- [ ] Aprobar los checks de la PR y publicar la imagen; esto no autoriza el
      despliegue a producción.

El ID de medición es público; el código lo consume desde una variable de build y
no lo fija en el repositorio. GA4 informó que no recibió datos durante las
últimas 48 horas. El deploy de producción observado fue `7bd151a7` el
2026-10-10; no confirma la recepción de eventos ni contiene los assets de esta
propuesta. No se hizo una prueba de red con consentimiento.

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
