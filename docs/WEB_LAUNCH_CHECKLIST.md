# Checklist de lanzamiento web

## Analítica GA4

- [x] Medición ID configurado en GitHub como `VITE_GA4_MEASUREMENT_ID`:
      `G-KDKJ9FX8VZ`.
- [x] El consentimiento limita la integración a `/booking/:slug` y `/b/:slug`;
      no se monta en el panel ni en «Mis turnos».
- [x] La política de privacidad describe el proveedor, el consentimiento, las
      cookies y los datos técnicos que recibe.
- [ ] Revisión y aprobación del texto de privacidad por el responsable.
- [ ] Revisar la configuración real de la propiedad: desactivar Medición
      mejorada y destinos publicitarios que amplíen los datos recogidos.
- [ ] Ejecutar la prueba de red descrita en [ANALYTICS.md](ANALYTICS.md) con el
      ID y dominio reales.
- [ ] Aprobar los checks de la PR y publicar la imagen; esto no autoriza el
      despliegue a producción.

El ID de medición es público; el código lo consume desde una variable de build y
no lo fija en el repositorio. La existencia de esa variable no prueba que la
propiedad esté configurada correctamente ni que se haya realizado una prueba
real. No se hizo un deploy.
