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
