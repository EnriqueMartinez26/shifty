# Checklist de lanzamiento web

## Analítica GA4

- [x] Medición ID configurado en GitHub como `VITE_GA4_MEASUREMENT_ID`:
      `G-KDKJ9FX8VZ`.
- [x] El consentimiento limita la integración a `/booking/:slug` y `/b/:slug`;
      no se monta en el panel ni en «Mis turnos».
- [x] Se preparó texto propuesto para la política sobre el proveedor, el
      consentimiento, las cookies y los datos técnicos que recibe.
- [ ] Revisión y aprobación del texto de privacidad por el responsable.
- [x] Propiedad real verificada el 2026-10-08: flujo `Shifty`, dominio
      `https://shifty-ar.tech`, ID `G-KDKJ9FX8VZ`; Medición mejorada, Google
      signals y recogida de datos proporcionados por usuarios apagados; cero
      vinculaciones con Google Ads.
- [ ] Reconfirmar esos controles antes de habilitar GA4 para clientes.
- [ ] Ejecutar la prueba de red descrita en [ANALYTICS.md](ANALYTICS.md) con el
      ID y dominio reales después de publicar el cambio.
- [ ] Aprobar los checks de la PR y publicar la imagen; esto no autoriza el
      despliegue a producción.

El ID de medición es público; el código lo consume desde una variable de build y
no lo fija en el repositorio. La propiedad informó que no recibió datos durante
las últimas 48 horas; eso no prueba el flujo del sitio. No se hizo un deploy ni
una prueba de red real.
