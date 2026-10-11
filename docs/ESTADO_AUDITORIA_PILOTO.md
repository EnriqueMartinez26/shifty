# Estado de auditoría y preparación del piloto

**Actualizado: 2026-10-06.** Este documento resume el estado del repo y los
pendientes para el piloto. CI verde demuestra contratos automatizados; no
demuestra que pagos, correo o infraestructura real hayan funcionado en
producción.

## Repo y controles

- `main` quedó actualizado localmente a `841ccf4`, tras los PR #125, #126,
  #127 y #128. El CI de `main` posterior a ambos merges pasó: Quality,
  CodeQL, Security scan y Build images. El #125
  endurece el chequeo de configuración del host; #126 y #127 corrigen el
  flujo OTP. Esto no acredita la configuración real del VPS ni elimina el
  riesgo de agotar intentos OTP descrito más abajo.
- La protección de `main` exige 15 checks, aplica también a administradores,
  usa `strict=false` y no exige aprobaciones generales; sí exige revisión de
  Code Owners. El #128, limitado a `CLAUDE.md`, fue aprobado por Enrique y
  mergeado.
- Quedan ocho PR abiertos, todos de Dependabot.
- Se retiraron 21 ramas locales y 89 remotas después de comprobar su estado.
  Quedan 33 worktrees registrados: 28 están limpios y sus commits ya están en
  `main` o tienen parches equivalentes. Preservar `x-dashboard-2` (cambios
  locales), `ah-password-backend` (commit único `1cfb3d14`), `integ` y
  `integration-review-119-121-122` (árboles distintos de `main`). Persisten
  cuatro directorios físicos sin registro Git: `ad-docs` y tres residuos
  anteriores. La limpieza **no está terminada**. Los cuatro
  `.claude/settings.local.json` de worktrees de agentes se copiaron con hashes
  verificados a `D:\Proyectos\Shifty-worktree-settings-backup-20261006`.
  Se conservaron los seis elementos sin seguimiento preexistentes del checkout
  raíz y el informe local; no hacer limpieza masiva.

## Pendientes antes de un piloto con cobros

| Área | Estado / evidencia disponible | Siguiente paso | Responsable |
| --- | --- | --- | --- |
| OTP | #126 y #127 están en `main`; la documentación registra el límite de intentos restante. | Probar entrega/reenvío con correo real y decidir si se abre trabajo para reducir el riesgo de agotamiento anónimo. | Ingeniería |
| Host, SSH, firewall y HTTPS | El repo documenta los controles y tiene un chequeo automatizado; #125 mejora ese chequeo. No hay evidencia adjunta de ejecución satisfactoria en el VPS. | Ejecutar y guardar salida del chequeo en el host; verificar puertos publicados, TLS y actualizaciones. | Operaciones |
| Mercado Pago | El código y CI cubren integración y webhook; falta la prueba de dinero real y la configuración productiva de OAuth/webhook. | Confirmar app productiva y redirect URI; hacer un cobro y reembolso controlados y conciliar el resultado. | Enrique + Mateo |
| Backup y cifrado | Hay procedimiento y workflow automatizado de drill; falta evidencia vigente de restauración en el entorno operativo y validación de tokens con `FIELD_ENCRYPTION_KEY`. | Restaurar un backup aislado, validar acceso con el rol de aplicación y documentar resultado y duración. | Operaciones |
| Correo | No hay evidencia operativa de entregabilidad, rebotes o quejas en el proveedor. | Verificar SPF/DKIM/DMARC y sandbox; definir alertas y tratamiento de rebotes/quejas. | Operaciones |
| Legales, privacidad y fiscal | Pendiente de revisión profesional y datos definitivos. | Abogado y contador deben validar textos, responsable, datos fiscales y obligaciones aplicables antes de captar clientes. | Enrique + profesionales |
| Piloto y soporte | Sin aceptación documentada de tiendas piloto ni procedimiento operativo completo. | Elegir 2–3 tiendas, acordar casos de aceptación, canal/horario de soporte, baja, incidentes y accesos de continuidad. | Enrique + tiendas piloto |

## Criterio de salida

No considerar listo para cobrar hasta que estén evidenciados: un ciclo real de
cobro y devolución, OAuth productivo, restauración comprobada, VPS endurecido,
correo entregable y aceptación de las tiendas piloto. La revisión legal y
fiscal requiere confirmación de los profesionales correspondientes.

## Referencias del repo

- [`docs/DEPLOY_RUNBOOK.md`](DEPLOY_RUNBOOK.md): precondiciones de producción,
  hardening del host, verificación del firewall y entregabilidad.
- [`docs/BACKUP_RESTORE_RUNBOOK.md`](BACKUP_RESTORE_RUNBOOK.md): restauración,
  validación con el rol de aplicación y evidencia del drill.
- [`docs/MERCADOPAGO_SETUP.md`](MERCADOPAGO_SETUP.md): OAuth, webhook y pruebas
  previas a producción.

## Actualización del 11 de octubre de 2026

Esta actualización complementa la foto histórica del 6 de octubre; no revalida
los controles del VPS ni las operaciones reales pendientes.

- **Privacidad:** el borrador se contrastó con la integración GA4 y se
  corrigieron las afirmaciones obsoletas sobre cookies y analítica. Sigue sin
  ser publicable: faltan identidad/contacto del responsable, proveedores y
  regiones, plazos, mecanismo de transferencias y revisión de un abogado
  matriculado. No hubo aprobación legal profesional.
- **GA4:** el código limita la analítica al portal de reserva y exige aceptación
  explícita. La variable `VITE_GA4_MEASUREMENT_ID` está configurada en GitHub
  Actions y pasa al build Docker; GitHub registra builds y deployments
  Production exitosos. En una sesión nueva de `/b/ejemplo`, antes de elegir,
  no hubo solicitudes a Google. Tras una aceptación autorizada, el bundle de
  Production envió una petición explícita `booking_started` que respondió
  HTTP 204. Por separado, GA4 mostró una recepción en Tiempo real. No se eligió
  servicio ni se creó una reserva.
  El repositorio no adjunta HAR, captura de Realtime ni export de los ajustes;
  esta es una observación registrada durante la sesión autorizada.
  GA4 registró además `first_visit` y `session_start` automáticos. El ID del
  bundle coincide con el flujo web `Shifty` del dominio. Medición mejorada,
  Google Signals y recopilación de datos proporcionados por usuarios están
  desactivados; recopilación granular de ubicación/dispositivo está activada.
  La personalización publicitaria se permite en 307/307 regiones, pero no hay
  vínculo con Google Ads ni etiquetas de sitio conectadas. Retención observada:
  2 meses para eventos y 14 meses para datos de usuario; borrar al tener nueva
  actividad está activado. No se probaron los demás eventos ni las otras
  vinculaciones de productos. Falta registrar la fuente exacta de la variable
  que usa Vercel. La política en Production aún es la versión resumida anterior;
  las correcciones locales no están desplegadas.
- **Rendimiento:** según la decisión del 11 de octubre por falta de presupuesto,
  se quitó del alcance actual la aceptación de 200 usuarios con staging y
  runner dedicados; no se inicia su aprovisionamiento.

Por lo tanto, la recepción de `booking_started` y la configuración principal
del flujo quedaron verificadas. Privacidad y documentación continúan
**parcialmente pendientes**: faltan la revisión profesional del texto, resolver
con asesoramiento el alcance de la personalización regional, confirmar los
datos legales y de proveedores, y desplegar el aviso corregido después de su
aprobación.
