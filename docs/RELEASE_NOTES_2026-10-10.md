# Notas del lanzamiento Shifty — 2026-10-10

## Identificación

- Release: `a203ee546f3a21bc3ad83b38d43767b2ff011bed`.
- Ventana: lanzamiento del 2026-10-10. El reporte operativo de Mateo indica que la app quedó desplegada a las 09:19 UTC.
- Owner: Enrique.

## Excepción aprobada: aceptación de capacidad

- Decisión: `D-20261010-01`.
- Aprobación: Enrique eligió explícitamente “Firmar excepción” el 2026-10-10 en esta conversación. Es una aprobación del owner asentada en el registro del proyecto; no es una firma legal ni criptográfica.
- Alcance: solo el lanzamiento identificado arriba.
- Ítem exceptuado: aceptación de carga de `docs/PERF_ACCEPTANCE.md` (200 usuarios, rampa de 5 minutos y meseta de 20 minutos en un entorno de staging apropiado).
- Estado de la evidencia: no hay una ejecución aceptada para este SHA. Perf Acceptance #13 figura como `skipped` en [la ejecución de GitHub Actions](https://github.com/EnriqueMartinez26/shifty/actions/runs/38053590145). El ensayo local del 2026-09-24 usó 3 tiendas, 20 usuarios y 90 s de meseta: 1.336 solicitudes, 0 errores y 4 muestras SLO; su veredicto `APROBADA` corresponde solo a ese ensayo abreviado. No satisface la aceptación requerida de 200 usuarios, rampa de 5 minutos y meseta de 20 minutos en staging.
- Riesgo aceptado: la capacidad bajo carga, incluida la latencia y el comportamiento de colas, queda sin medir y sin aceptar para este lanzamiento.
- Restricción: esta excepción no certifica capacidad ni se extiende a otro SHA. No ejecutar la prueba contra producción; cualquier aceptación futura requiere el entorno aislado indicado por el runbook.

Esta excepción no cierra los smoke funcionales, la revisión legal del texto de GA4 ni la prueba final de cobro y devolución de Mercado Pago. Enrique informó que Mateo completó la prueba de Sentry; adjuntar al expediente el enlace o ID del evento y el entorno/release observado.

## Excepción aprobada para el release siguiente: aceptación de capacidad (2026-10-12)

- Decisión: `D-20261012-01`. No extiende `D-20261010-01`, que cubrió solo el SHA de arriba.
- Aprobación: instrucción explícita de Enrique (owner) del 2026-10-12: para este lanzamiento se exceptúa la prueba de carga de 200 usuarios y se registra la excepción con su mitigación y su rollback.
- Alcance: el release a producción que sigue a las slices de P4 (#162, #165 y #155). El SHA exacto se escribe acá al desplegar, porque cualquier merge lo cambia: `pendiente: sha completo de .deploy/current después del deploy`.
- Ítem exceptuado: solo la aceptación de capacidad de `docs/PERF_ACCEPTANCE.md` (200 usuarios, rampa de 5 minutos y meseta de 20 minutos en staging; ítem de capacidad de `docs/RELEASE_CHECKLIST.md` §2). Los demás ítems del checklist siguen vigentes.
- Motivo: todavía no hay un staging privado y aislado, y el tráfico del lanzamiento son pocas tiendas incorporadas en persona.
- Riesgo aceptado: la capacidad bajo carga (latencia y colas) queda sin medir ni aceptar.
- Mitigación:
  - Latencia por ruta cada 5 minutos (`deploy/cron/shifty-latency`).
  - UptimeRobot sobre `https://<dominio>/api/ops/health/ready` (configurado fuera del repo).
  - Sentry en la API y los workers.
  - Chequeos y alertas del host (`deploy/cron/shifty-guard` y los chequeos de `docs/DEPLOY_RUNBOOK.md` §8).
  - Backend gradual con compuerta de 60 s en `scripts/deploy.sh`.
  - Incorporación de las tiendas de a una, mirando latencia y errores antes de sumar la siguiente.
- Rollback: `bash scripts/deploy.sh rollback` (o `make rollback`). Es automático si falla la compuerta de 60 s y vuelve a la versión guardada en `.deploy/previous`. No migra: las migraciones son solo expand, así que la versión anterior corre sobre el esquema nuevo.
- Vencimiento: lo que llegue primero entre incorporar una sexta tienda o el 2026-11-12. Antes de cualquiera de los dos, la aceptación corre en el staging aislado o hace falta una decisión nueva. **Enrique: ajustar el número de tiendas y la fecha si no coinciden con el plan de incorporación.**
- Lo que no se exceptúa: las guardas de P4 siguen obligatorias para cualquier corrida de carga (verificador del destino `scripts/verify_perf_target.py`, clientes sin redirecciones, dominio de producción y `www` rechazados). Nunca se corre la prueba contra producción.

## Release del 2026-10-21: excepción de capacidad hasta 20 tiendas

- Release: `109f38fe232cd73fa4df4c2a5528bf7ef53ec22d` (antes corría `27ab7f01ef26659541b017ea80a6a0974eae7b85`).
- Ventana: deploy del 2026-10-21, de 06:16:35 a 06:18:55 UTC (`bash scripts/deploy.sh deploy`).
- Contenido: cambios de interfaz del panel y del portal público (adaptación a celular, accesibilidad, contador de fechas de la reserva) y actualizaciones de dependencias. Sin migraciones ni cambios en `nginx/nginx.prod.conf` ni en `docker-compose.prod.yml`.
- Decisión: `D-20261021-01`, propuesta por Mateo y adoptada por Enrique (owner) en su aprobación del PR [#237](https://github.com/EnriqueMartinez26/shifty/pull/237) el 2026-10-21.
- Ítem exceptuado: solo la aceptación de capacidad de `docs/RELEASE_CHECKLIST.md` (staging aislado y `perf-acceptance.yml` en el runner dedicado). Los demás ítems del checklist y la QA manual en celular siguen vigentes.
- Evidencia del deploy:
  - preflight: Quality verde en `main` para el SHA, compose 5.6.0, disco al 7 %;
  - sin migraciones pendientes (`alembic upgrade head` no aplicó revisiones);
  - backend gradual (2 réplicas nuevas sanas) y frontend sin corte;
  - compuerta: `ok (0 fallos sueltos, 5xx 0/94)`;
  - `.deploy/current` = `109f38fe232cd73fa4df4c2a5528bf7ef53ec22d`, y `docker compose images` muestra ese tag en backend ×2, frontend, `celery`, `celery_beat` y `celery_interactive`;
  - después del deploy: `/api/ops/health/ready` respondió 200 y el smoke de solo lectura del portal de la primera tienda (4 servicios, horarios y vista previa de total y seña con adicionales) no encontró problemas.
- Pendiente: QA manual en un celular real de las pantallas del cliente que cambiaron.
- Rollback: `bash scripts/deploy.sh rollback`, que vuelve a `.deploy/previous` sin migrar.
