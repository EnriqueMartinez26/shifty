# Llevar Shifty a producción exige cerrar el primer arranque

**Fecha de investigación: 8 de octubre de 2026.** Shifty necesita un dominio propio, un VPS de al menos **8 GiB como hipótesis inicial**, DNS, TLS, correo transaccional, credenciales productivas de Mercado Pago, copias externas, alertas y una prueba completa del release candidato. La opción que mejor coincide con el diseño actual es **un `.com.ar` más un Hostinger KVM 2 en Brasil, sujeta a disponibilidad y al total de compra**. Es una alternativa evaluada en esa fecha, no una compra aprobada; los precios y recomendaciones de contratación de este informe son históricos, deben cotizarse de nuevo y no autorizan gasto. El repositorio ya contiene Compose, imágenes por SHA, migraciones y runbooks, pero **el primer arranque no está resuelto**: nginx exige certificados antes de iniciar y el procedimiento de certificado depende de nginx; además, `make deploy` recarga nginx sin crearlo. Hay que corregir y ensayar ese bootstrap antes de exponer clientes. Después, la salida depende de evidencia del VPS real: carga, pago y webhook, OTP entregado, restauración y alertas recibidas. La existencia de scripts o tests en el repositorio no acredita que estos pasos hayan ocurrido en producción. ([Runbook del repositorio](D:/Proyectos/Shifty/docs/DEPLOY_RUNBOOK.md#L183); [nginx productivo](D:/Proyectos/Shifty/nginx/nginx.prod.conf#L104); [script de deploy](D:/Proyectos/Shifty/scripts/deploy.sh#L416))

## Dominio y VPS: contratar para 8 GiB y medir antes de escalar

El presupuesto del proyecto suma **5856 MiB en régimen y 6880 MiB durante un despliegue**, con dos réplicas de API, PostgreSQL, dos Redis, RabbitMQ, workers, beat, nginx y frontend. Deja 1312 MiB al sistema y caché de página en el pico; no deja espacio para un staging completo simultáneo. También presupone **2 vCPU y 100 conexiones máximas de PostgreSQL**. Por eso 8 GiB es el punto de partida defendible para el piloto, no una capacidad certificada ni un pronóstico de usuarios de negocio. Un VPS de 4 GiB abarata la factura, pero exigiría redimensionar el sistema y volver a probarlo. ([Presupuesto de memoria y conexiones](D:/Proyectos/Shifty/docs/DEPLOY_RUNBOOK.md#L183); [aceptación de capacidad](D:/Proyectos/Shifty/docs/PERF_ACCEPTANCE.md#L3))

La opción práctica inicial es **Hostinger KVM 2 con ubicación Brasil**, si el checkout ofrece esa región y confirma IPv4, 8 GiB, 2 vCPU y el precio final. Hostinger publica USD 8,99/mes promocionales y USD 14,99/mes de renovación como equivalentes de un **plazo de 24 meses pagado por adelantado**: aproximadamente **USD 215,76 al contratar** y **USD 359,76 por la siguiente renovación bienal**, antes de impuestos y cambios de oferta. No son pagos mensuales de USD 8,99. Hostinger anuncia Brasil entre sus ubicaciones VPS, pero la ciudad y disponibilidad del plan se confirman al contratar. ([Hostinger VPS](https://www.hostinger.com/vps-hosting); [ubicaciones](https://www.hostinger.com/support/1583267-where-are-hostinger-servers-located/); [límites de planes](https://www.hostinger.com/support/6976044-parameters-and-limits-of-hosting-plans-in-hostinger))

Si se prefiere facturación mensual sin ese adelanto, **AWS Lightsail de 8 GiB y 2 vCPU figura a USD 44/mes** y dispone de región São Paulo; **DigitalOcean Basic de 8 GiB y 4 vCPU figura a USD 48/mes**, pero su lista pública de centros no incluye Sudamérica. En Lightsail hay que contabilizar snapshots por GB y transferencia específica de São Paulo. En DigitalOcean, el backup diario agrega 30% del precio de la VM: **USD 14,40/mes** sobre la de USD 48. La elección final debe comparar precio total, latencia desde Argentina, soporte, acceso a consola y comportamiento medido de Shifty, no solo RAM nominal. ([Lightsail precios](https://aws.amazon.com/lightsail/pricing/); [Lightsail snapshots](https://docs.aws.amazon.com/lightsail/latest/userguide/amazon-lightsail-faq-snapshots.html); [DigitalOcean precios](https://www.digitalocean.com/pricing/droplets); [backup DigitalOcean](https://docs.digitalocean.com/products/backups/details/pricing/))

Para el dominio, **`.com.ar` cuesta ARS 8.500 por alta y ARS 8.500 por renovación anual** según el arancel publicado por NIC Argentina; un `.com` en Cloudflare Registrar aparece desde **USD 10,46 por año**. Disponibilidad del nombre y precio efectivo se comprueban antes de pagar. Recomiendo registrar primero el nombre de marca elegido, delegar DNS y crear un registro `A` hacia la IPv4 pública; agregar `AAAA` solo si la ruta IPv6 está configurada y comprobada. Usar inicialmente DNS directo simplifica comprobar el desafío ACME; si luego se activa el proxy de Cloudflare, configurar **Full (strict)** con certificado válido en el origen. El correo requerirá además los registros que indique su proveedor. ([NIC Argentina aranceles](https://nic.ar/es/dominios/aranceles); [Cloudflare Registrar](https://pricing.registrar.cloudflare.com/); [registros DNS](https://developers.cloudflare.com/dns/manage-dns-records/how-to/create-dns-records/); [Full strict](https://developers.cloudflare.com/ssl/origin-configuration/ssl-modes/full-strict/))

| Escenario orientativo | Pago inicial conocido | Base recurrente o renovación | Faltantes variables |
| --- | --- | --- | --- |
| `.com.ar` + Hostinger KVM 2 Brasil | **ARS 8.500 + USD 215,76** por el VPS de 24 meses | VPS equivalente promocional USD 8,99/mes; renovación anunciada USD 359,76 por 24 meses | Bucket externo, SMTP si supera el plan gratis, impuestos, cambio de precio y dominio anual. |
| `.com.ar` + Lightsail 8 GiB São Paulo | **ARS 8.500 + primer mes desde USD 44** | Desde USD 44/mes | Snapshots por GB, bucket externo, correo, transferencia excedente e impuestos. |
| `.com.ar` + DigitalOcean 8 GiB | **ARS 8.500 + primer mes desde USD 48** | USD 48/mes; USD 62,40 con backup diario del proveedor | Bucket externo, correo, impuestos y latencia de la región elegida. |

Un **bucket privado fuera del VPS** es obligatorio para el procedimiento de recuperación de Shifty; DigitalOcean Spaces sirve como referencia de **USD 5/mes hasta 250 GiB**, sujeto a uso y elección de proveedor. El snapshot del VPS ayuda a recuperar la máquina, pero no reemplaza el dump y restauración de PostgreSQL que exige el proyecto. Un correo transaccional puede comenzar en plan gratuito si el volumen real encaja: Resend publica 3000 mensajes/mes y 100/día, y Pro USD 20/mes; hay que validar dominio y DNS de envío. Estos importes son referencias públicas del 8 de octubre de 2026, **sin impuestos, cotización, promociones finales ni cargos por exceso**. ([Spaces precios](https://docs.digitalocean.com/products/spaces/details/pricing/); [Resend precios](https://resend.com/pricing); [runbook de backup](D:/Proyectos/Shifty/docs/BACKUP_RESTORE_RUNBOOK.md#L19))

## El primer release requiere corregir dos dependencias circulares

La configuración productiva solo expone **80 y 443 desde nginx**; los servicios internos se mantienen sin puertos publicados. La SPA y `/api/` comparten origen, y Mercado Pago llamará a `https://<dominio>/api/payments/webhooks/mercadopago`. Compose debe ser **2.24 o superior**, porque el override usa `!reset []` para quitar puertos internos. En el VPS hacen falta Ubuntu 24.04 LTS según el runbook, usuario sudo, SSH por llave, firewall para 22/80/443, hora sincronizada, Docker, acceso de solo lectura a GHCR, `/opt/shifty`, secretos fuera de Git y variables operativas. La plantilla `backend/.env.production.example` muestra URLs de base y Redis externos; al usar los servicios locales de Compose hay que ajustarlas a esos nombres internos, incluido `ssl=disable` para PostgreSQL dentro de la red Docker, sin copiar la plantilla literalmente. ([Compose productivo](D:/Proyectos/Shifty/docker-compose.prod.yml#L103); [configuración nginx](D:/Proyectos/Shifty/nginx/nginx.prod.conf#L362); [preparación del host](D:/Proyectos/Shifty/docs/DEPLOY_RUNBOOK.md#L15); [plantilla de entorno](D:/Proyectos/Shifty/backend/.env.production.example))

**El bloqueo de TLS es concreto.** El runbook prescribe Certbot `--webroot`, cuyo desafío HTTP lo serviría nginx; sin embargo, nginx exige `fullchain.pem` y `privkey.pem` al arrancar. El hook de certificado copia ambos archivos, pero luego ejecuta una prueba y recarga sobre un contenedor nginx ya activo. Para el primer certificado se necesita un procedimiento versionado y probado: por ejemplo, emitir con desafío HTTP-01 `standalone` usando el puerto 80 libre y después dejar las renovaciones en `webroot`, o iniciar temporalmente nginx solo HTTP para el desafío y sustituirlo por la configuración TLS. En ambos casos hay que ensayar `certbot renew --dry-run`, copia de archivos, permisos y recarga, y probar el reinicio del VPS. La documentación de Let's Encrypt y Certbot admite el desafío HTTP-01, pero **esta secuencia concreta aún es una propuesta para Shifty**. ([runbook de Certbot](D:/Proyectos/Shifty/docs/DEPLOY_RUNBOOK.md#L244); [nginx exige certificado](D:/Proyectos/Shifty/nginx/nginx.prod.conf#L104); [Let's Encrypt](https://letsencrypt.org/getting-started/))

**El bloqueo del borde es independiente.** `make deploy` presupone la base ya corriendo, actualiza backend, workers y frontend, y ejecuta `nginx -t` mediante `docker compose exec nginx`; no crea nginx en un host vacío. Debe añadirse una ruta de bootstrap explícita o un procedimiento versionado que levante dependencias, migre, inicie la aplicación y cree nginx una vez presentes los certificados y upstreams. El primer despliegue tampoco tiene imagen anterior para rollback automático. La solución debe ensayarse sobre un VPS limpio antes del corte. Los despliegues siguientes sí pueden usar `make deploy APP_VERSION=<sha>` y su compuerta de salud; los cambios del archivo de configuración del borde se aplican mediante `make deploy-edge`. ([preflight y despliegue](D:/Proyectos/Shifty/docs/DEPLOY_RUNBOOK.md#L310); [script de deploy](D:/Proyectos/Shifty/scripts/deploy.sh#L416); [cambio del borde](D:/Proyectos/Shifty/docs/DEPLOY_RUNBOOK.md#L342))

## Correo, Mercado Pago y datos deben funcionar desde el dominio público

Antes de construir el release hay que fijar **dominio, dirección de contacto, responsable legal, proveedor SMTP y configuración de Mercado Pago**. El frontend es estático: `VITE_SENTRY_DSN`, `VITE_SUPPORT_WHATSAPP`, `VITE_CONTACT_EMAIL` y `VITE_LEGAL_RESPONSABLES` se incorporan durante el build en GitHub; cambiarlos exige imagen nueva y despliegue de otro SHA. El backend productivo exige `PUBLIC_API_URL` y CORS con HTTPS, Sentry, `OTP_PROVIDER=email`, secreto de webhook y Client ID/Secret/redirect URI de la aplicación productiva de Mercado Pago. El token secreto queda en el backend, nunca en el bundle ni en Git. La cuenta de cada tienda se vincula por OAuth; deben probarse vínculo, creación de link, webhook firmado, idempotencia, conciliación y alerta de fallo. ([variables de build](D:/Proyectos/Shifty/docs/DEPLOY_RUNBOOK.md#L295); [requisitos de entorno](D:/Proyectos/Shifty/docs/DEPLOY_RUNBOOK.md#L23); [credenciales de Mercado Pago](https://www.mercadopago.com.ar/developers/en/docs/your-integrations/credentials); [webhooks de Mercado Pago](https://www.mercadopago.com.ar/developers/es/docs/split-payments/additional-content/your-integrations/notifications/webhooks?scope=prod))

El correo es funcionalmente crítico: OTP y avisos al cliente usan SMTP. Hay que verificar el dominio de envío con SPF, DKIM y DMARC según el proveedor, usar STARTTLS, solicitar un OTP real y comprobar su entrega, no solo que el servidor acepte el mensaje. Resend y Brevo ofrecen SMTP/planes gratuitos, pero la elección depende de límites, entregabilidad y soporte operativo; el costo no puede cerrarse sin volumen estimado de OTP y avisos. ([SMTP de Resend](https://resend.com/changelog/smtp-service); [planes de Resend](https://resend.com/pricing); [correo de Shifty](D:/Proyectos/Shifty/docs/RELEASE_CHECKLIST.md#L56))

La recuperación también exige recursos externos: **bucket privado, credenciales restringidas y `rclone`**, timer diario, checksum y copia fuera del VPS. Antes de migrar debe existir una copia reciente; el deploy rechaza una de más de 24 horas. En el primer arranque, eso implica respaldar la base inicial para pasar el preflight; **después de aplicar el esquema**, hacer una copia representativa y restaurarla en base aislada con comprobación del rol `shifty_app`, incluido RLS. Los objetivos son **RPO ≤24 h y RTO ≤4 h**, con evidencia de un simulacro de no más de 31 días. ([runbook de backup](D:/Proyectos/Shifty/docs/BACKUP_RESTORE_RUNBOOK.md#L19); [checklist de recuperación](D:/Proyectos/Shifty/docs/RELEASE_CHECKLIST.md#L46); [preflight del deploy](D:/Proyectos/Shifty/docs/DEPLOY_RUNBOOK.md#L310))

## La secuencia de salida termina con evidencia, no con contenedores encendidos

| Orden | Acción y prueba de salida |
| --- | --- |
| 1. Decidir y comprar | Elegir nombre, verificar disponibilidad, registrar dominio y contratar VPS de 8 GiB en la región disponible. Guardar precio total y fecha de renovación; apuntar DNS y probar resolución de A y, si se usa, AAAA. |
| 2. Preparar servicios externos | Crear proyecto Sentry y alertas, app productiva de Mercado Pago, SMTP con dominio de envío, bucket privado y canal de alerta que llegue a una persona. Definir responsables de soporte, pagos, restauración y escalamiento. |
| 3. Preparar el host | Aplicar hardening del runbook; instalar Compose ≥2.24, Certbot y `rclone`; autenticar GHCR; configurar `.env` de servidor y `/etc/shifty/ops.env`; verificar que el Compose final solo publique nginx. No imprimir secretos en la evidencia. |
| 4. Resolver el bootstrap | Corregir/versionar el primer certificado y el alta inicial de nginx. Ensayar desde VPS vacío, renovación TLS, reinicio completo y acceso HTTPS. Esta es la primera tarea técnica bloqueante. |
| 5. Backup inicial | Levantar dependencias, adjuntar el volumen `/backups`, ejecutar un primer backup externo y verificar checksum antes de migrar. |
| 6. Desplegar el SHA | Elegir SHA completo de `main` con `Quality`, build de imágenes y `security-scan` verdes; revisar un solo head Alembic y migraciones expand/contract; ejecutar el bootstrap para primer release y, en los siguientes, `make deploy APP_VERSION=<sha>`. |
| 7. Demostrar recuperación | Repetir backup con el esquema aplicado y restaurar en entorno aislado con el rol de aplicación. Registrar RPO/RTO y fecha del simulacro. |
| 8. Demostrar servicio | Comprobar `https://<dominio>/api/ops/health/ready`, RabbitMQ sin alarmas, sin contenedores enfermos, Sentry, alerta recibida, OTP real, reserva, cobro y webhook, jobs. Correr aceptación de capacidad de **200 usuarios, 5 minutos de rampa y 20 de meseta**, con el candidato y VPS reales; adjuntar resultado `APROBADA` o corregir y repetir. |

La prueba de 200 usuarios tiene umbrales definidos en el repositorio: p95 menor a 500 ms salvo login menor a 1 s, cero 5xx/429 y errores de conexión, ráfagas concurrentes sin doble reserva y colas dentro de límite. **No hay evidencia en las notas de que se haya superado en el VPS real**; una corrida local reducida no la sustituye. La salud `/ready` verifica PostgreSQL y Redis, pero no RabbitMQ, SMTP, Mercado Pago ni beat. Hace falta comprobarlos por separado y asegurar que las métricas de `/ops/slo` se conviertan en alertas que lleguen a un responsable; publicar el endpoint no basta. ([aceptación de capacidad](D:/Proyectos/Shifty/docs/PERF_ACCEPTANCE.md#L3); [checklist del release](D:/Proyectos/Shifty/docs/RELEASE_CHECKLIST.md#L27); [salud API](D:/Proyectos/Shifty/backend/modules/ops/router.py#L56))

## Conclusión

**Comprar dominio y VPS es necesario, pero el riesgo principal hoy está en el primer arranque y en demostrar recuperación y operación real.** Recomiendo elegir el `.com.ar` y cotizar primero KVM 2 Brasil, mientras se corrige y prueba el bootstrap TLS/nginx en un entorno limpio. Preparar SMTP, Mercado Pago, almacenamiento externo y alertas antes de la prueba integral del release candidato. El criterio para admitir tiendas es el [checklist de release](D:/Proyectos/Shifty/docs/RELEASE_CHECKLIST.md#L1) con evidencia fechada para ese SHA; hasta entonces el estado es **preparado en código, pendiente de verificación productiva**.

## Actualización de alcance y documentación (11 de octubre de 2026)

Esta nota actualiza el alcance y los pendientes de documentación; **no vuelve a
cotizar ni confirma compras, despliegues o pruebas operativas**.

- Por falta de presupuesto, se quitó del alcance actual la aceptación de carga
  de 200 usuarios y el aprovisionamiento de staging/runner dedicados. Las
  referencias anteriores a esa aceptación describen el plan previo; no son una
  autorización de gasto ni una tarea activa.
- Se corrigieron los documentos de GA4 para separar el código, la variable de
  GitHub Actions y lo observado en Production de Vercel. GitHub registra
  despliegues Production exitosos creados por `vercel[bot]`. En una sesión
  nueva, `/b/ejemplo` no hizo solicitudes a Google antes de elegir. Tras una
  aceptación autorizada, se observó una petición explícita `booking_started`
  que respondió HTTP 204. Por separado, GA4 mostró una recepción en Tiempo
  real. No se eligió servicio ni se creó
  una reserva. GA4 también registró `first_visit` y `session_start`
  automáticos. El repositorio no adjunta HAR, captura de Realtime ni export de
  los ajustes; queda como observación registrada en la sesión autorizada.
- La propiedad contiene un flujo web `Shifty` en `https://shifty-ar.tech` y
  el ID de medición coincide con el que cargó el bundle (el valor se omite).
  Medición mejorada, Google Signals y recopilación de datos proporcionados por
  usuarios están desactivados; recopilación granular de ubicación/dispositivo
  está activada. Se permiten anuncios personalizados en 307/307 regiones, pero
  no hay vínculo con Google Ads ni etiquetas de sitio conectadas. La retención
  está configurada en 2 meses para eventos y 14 meses para datos de usuario;
  borrar ante nueva actividad está activado. La fuente exacta del ID usado por
  Vercel y las demás vinculaciones de productos no se confirmaron.
- El borrador de privacidad ahora describe el consentimiento y la evidencia
  técnica observada, incluida la diferencia entre las señales que envía la
  etiqueta y la capacidad de personalización habilitada en la propiedad.
  Continúa sin aprobación legal: faltan datos confirmados del responsable y
  proveedores, entidad/región de tratamiento y mecanismos de transferencia,
  además de la revisión de un abogado matriculado. Production aún muestra la
  versión resumida anterior; las correcciones locales todavía no están
  desplegadas.

**Estado de salida:** este addendum no reemplaza las evidencias productivas que
el informe principal pide para salud, correo, cobros, alertas y restauración.
La recepción de `booking_started` ya tiene evidencia de runtime y propiedad.
Privacidad y documentación quedan parcialmente abiertas hasta confirmar los
datos legales y de proveedores, revisar las vinculaciones restantes con el
responsable, obtener aprobación profesional y desplegar el aviso aprobado.
