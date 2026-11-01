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
- Decisión: `D-20261021-01`, propuesta por Mateo y adoptada por Enrique (owner) en su aprobación del PR [#237](https://github.com/EnriqueMartinez26/shifty/pull/237) sobre el head `50a08ed6`, el 2026-10-21 a las 06:10:27 UTC.
- Ítem exceptuado: solo la aceptación de capacidad de `docs/RELEASE_CHECKLIST.md` (staging aislado y `perf-acceptance.yml` en el runner dedicado). Los demás ítems del checklist y la QA manual en celular siguen vigentes.
- Evidencia del deploy:
  - preflight: Quality verde en `main` para el SHA, compose 5.6.0, disco al 7 %;
  - migración: `alembic upgrade head` corrió con el código viejo sirviendo y no aplicó revisiones (el log solo muestra el contexto de Alembic; entre los dos SHA no cambia `backend/alembic/versions/`);
  - log del deploy: "backend: 2 replicas nuevas sirviendo" (contenedores `Healthy`) y "frontend: 1 replicas nuevas sirviendo", seguidos de `nginx -t` ok y reload;
  - compuerta: `ok (0 fallos sueltos, 5xx 0/94)`;
  - `.deploy/current` = `109f38fe232cd73fa4df4c2a5528bf7ef53ec22d`, y `docker compose images` muestra ese tag en backend ×2, frontend, `celery`, `celery_beat` y `celery_interactive`;
  - después del deploy: `/api/ops/health/ready` respondió 200 y el smoke de solo lectura del portal de la primera tienda (4 servicios, horarios y vista previa de total y seña con adicionales) no encontró problemas.
- Pendiente:
  - QA manual en un celular real de las pantallas del cliente que cambiaron;
  - constancia escrita de la revisión legal de las páginas legales: falta un correo o comentario que diga qué páginas se revisaron y en qué fecha. Hasta tenerla no se registra ninguna fecha ni versión revisada.
- Rollback: `bash scripts/deploy.sh rollback`, que vuelve a `.deploy/previous` sin migrar.

## Release del 2026-10-22: backend del rediseño del portal

- Release: `059f8e857bef0098c22154789d8b91cbec00177d` (antes corría `109f38fe232cd73fa4df4c2a5528bf7ef53ec22d`).
- Ventana: deploy del 2026-10-22, de 06:17:28 a 06:19:54 UTC (`bash scripts/deploy.sh deploy`).
- Contenido:
  - #236: una reserva pública sin cobro nace confirmada, y un turno a más de 30 días con seña obligatoria se cobra solo por Mercado Pago (`D-20261020-01`, `D-20261020-02`);
  - #240: CTA y selección en la rampa naranja oscura con texto blanco;
  - #243: `services.requires_prior_design` y `services.prior_design_message` (diseño previo);
  - #249: `cover_position` de la tienda en `theme_config`;
  - #232: E2E aislado con Playwright en CI;
  - #248: dos tests intermitentes estabilizados.
  - El frontend del rediseño todavía no sale: la cadena #239 → #250 espera revisión.
- Decisión aplicada: `D-20261021-01` (excepción de la aceptación de capacidad hasta 20 tiendas). Los demás ítems del checklist siguen vigentes.
- Evidencia del deploy:
  - preflight: Quality verde en `main` para el SHA, compose 5.6.0, disco al 6 %;
  - migración con el código viejo sirviendo: `Running upgrade c9e1a3b5d7f2 -> a7c9e1b3d5f7, services.requires_prior_design + prior_design_message: diseno previo`;
  - log del deploy: "backend: 2 replicas nuevas sirviendo" (contenedores `Healthy`) y "frontend: 1 replicas nuevas sirviendo", seguidos de `nginx -t` ok y reload;
  - compuerta: `ok (0 fallos sueltos, 5xx 0/26)`, y el script terminó con `deploy: ok, corre 059f8e857bef0098c22154789d8b91cbec00177d`;
  - después del deploy, desde afuera:
    - `/api/ops/health/ready` respondió 200;
    - `GET /public/stores/jaziz-nails` trae `cover_position` y `deposit_far_limit_days`, los dos en `null`, lo correcto para una tienda sin encuadre elegido y con Mercado Pago;
    - `GET /public/services` trae `requires_prior_design` y `prior_design_message` en los 4 servicios;
    - el smoke de solo lectura del portal de la primera tienda no encontró problemas.
- Pendiente:
  - QA manual en un celular real;
  - constancia escrita de la revisión legal: qué páginas se revisaron y en qué fecha y versión.
- Rollback: `bash scripts/deploy.sh rollback`, que vuelve a `.deploy/previous` sin migrar. La migración solo agrega columnas con valor por defecto, así que el código anterior corre sobre el esquema nuevo.

## Release del 2026-11-01: retirar texto auxiliar de fecha y horario

- Release: `879fdd9847647fd5cbcad450ce255729dec9362d` (antes corría `e1c130a03574495207e217f5209f052b5fac3bdd`). PR [#268](https://github.com/EnriqueMartinez26/shifty/pull/268), issue [#267](https://github.com/EnriqueMartinez26/shifty/issues/267). Owner: Enrique (autorizó el deploy).
- Ventana UTC: 2026-11-01 22:39:09–22:49:55 (`bash scripts/deploy.sh deploy`).
- Contenido: elimina “Elegí el día y el horario que te quede mejor.” del paso de fecha/hora y conserva 20 px de espacio vacío, fuera del árbol accesible. Solo cambia `frontend/src/presentation/components/organisms/booking/BookingStepDateTime.tsx` y su test. Sin cambios de API, base de datos, pagos, imágenes de borde ni colores de marca.
- Riesgo visual heredado, sin cambio: se mantiene la limitación de contraste aceptada en D-20261029-01 para texto blanco sobre naranja Shifty; este release no modifica esos controles ni declara conformidad WCAG AA.
- Verificación previa: los 12 checks requeridos de la PR pasaron; `Quality`, `Security scan`, `CodeQL` y `Build images` pasaron en `main` para el SHA del release. Preflight del VPS: Quality verde para el SHA, Compose 5.6.0, disco al 8 % y backup más reciente de 16 h 39 min (06:00:11 UTC).
- Evidencia de deploy: migración corrió con el backend anterior sirviendo y no aplicó revisiones; las dos réplicas nuevas de backend y la de frontend quedaron `Healthy`; `nginx -t` y reload pasaron; workers recreados; compuerta `ok (0 fallos sueltos, 5xx 0/26)`. `.deploy/current` y las imágenes de backend, frontend y workers coinciden con `879fdd9847647fd5cbcad450ce255729dec9362d`; `.deploy/previous` es `e1c130a03574495207e217f5209f052b5fac3bdd`.
- Smoke externo: `/api/ops/health/ready` y `/b/jaziz-nails` respondieron 200. En escritorio y a 390×844 se comprobó el paso 2: el texto no aparece y el espaciador `h-5` conserva 20 px. El acento rosa configurado de Jaziz Nails siguió visible. No se creó una reserva ni se envió un pago. `/b/salon-sentinel` respondió “Negocio no encontrado”; por eso esta verificación de producción no se atribuye a Salon Sentinel.
- Excepción de capacidad aplicada: D-20261021-01, vigente hasta el 2026-11-12 o antes si se incorpora la tienda 21 o aparecen señales sostenidas de saturación. El preflight observó 3 tiendas y los registros recientes de latencia sin violaciones; no se corrió carga contra producción.
- Checklist que sigue abierto (no es una excepción aprobada): el workflow [Monthly Backup Restore Drill](https://github.com/EnriqueMartinez26/shifty/actions/runs/41303326879) del 2026-11-01 falló antes de ejecutar el drill porque faltan `BACKUP_DATABASE_URL`, `DRILL_DATABASE_URL` y `APP_DB_PASSWORD`; la última evidencia documentada de restore es del 2026-09-24 y supera 31 días. No se copiaron secretos ni se restauró una copia de datos productivos. Tampoco se ejecutó en producción un smoke funcional de login, escritura de reserva, reportes, webhook de pagos o procesamiento de workers; solo se hizo navegación pública de solo lectura y health check. El release quedó desplegado, pero no se declara cerrado el checklist de restauración ni la cobertura completa de smoke.
- Recuperación: rollback con `bash scripts/deploy.sh rollback` al SHA guardado en `.deploy/previous` (`e1c130a03574495207e217f5209f052b5fac3bdd`). Owner de restauración y escalación: Enrique, dueño del VPS y del repositorio.
