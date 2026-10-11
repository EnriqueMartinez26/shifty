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
