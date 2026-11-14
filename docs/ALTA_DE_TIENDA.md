# Alta de una tienda

Guía de alta y verificación en un entorno aislado. No reemplaza la aprobación comercial, legal ni la decisión de anunciar. Para el procedimiento detallado de publicación y manejo de bloqueos, ver [ALTA_TIENDA_RUNBOOK.md](ALTA_TIENDA_RUNBOOK.md).

## Responsables

| Paso | Responsable |
| --- | --- |
| Confirmar nombre, slug, servicios, horarios, canal de seña, plan, importe y fechas | Enrique confirma las condiciones comerciales con el negocio; el administrador de la tienda confirma los datos operativos. |
| Revisar contrato, tratamiento de datos y condiciones de cancelación/reembolso | Asesoría legal y Enrique. La pantalla de alta no registra la aceptación contractual. |
| Crear plan, tienda, cuenta administradora y suscripción | Operador autorizado de SuperAdmin. |
| Completar identidad, horarios, catálogo, personal y canales | Administrador de la tienda. |
| Preparar Mercado Pago de prueba y SMTP de captura | Responsable de infraestructura junto con Mateo; usar únicamente cuentas de prueba controladas. |
| Ejecutar y registrar la verificación de QA | Mateo y el administrador de la tienda, en una tienda aislada con datos sintéticos. |
| Decidir si se anuncia la tienda | Enrique, después de revisar la evidencia y los pendientes. |

No incluyas contraseñas, tokens, datos de clientes ni comprobantes en este documento, capturas o tickets. Si una validación depende de una cuenta o servicio de prueba que no está disponible, registrala como **NO EJECUTADA** y dejá el alta incompleta.

## 1. Acordar los datos antes del alta

Confirmá por escrito el plan, precio, moneda, intervalo de facturación, límites, fecha de inicio y fecha de fin; la identidad que se publicará; los horarios; la política de cancelación y seña; y qué funciones están aprobadas. No tomes un valor inicial del formulario como decisión comercial.

La creación de la tienda no crea el catálogo, personal, horarios ni suscripción. La ficha se crea activa: no uses una tienda incompleta como si fuera un borrador privado. Hacé las pruebas con una tienda de QA aislada y no crees reservas ni cobros de prueba en producción.

## 2. Crear plan, tienda, administrador y suscripción

El operador de SuperAdmin entra a `/control-global`. La API exige una cuenta SuperAdmin; los endpoints de alta actuales y sus respuestas exitosas son:

| Acción | Ruta API (relativa a la base de API) | Éxito |
| --- | --- | --- |
| Crear plan | `POST /superadmin/plans` | `201` |
| Crear tienda | `POST /superadmin/stores` | `201` |
| Crear el admin de esa tienda | `POST /superadmin/stores/{store_public_id}/admins` | `201` |
| Asignar o actualizar suscripción | `POST /superadmin/stores/{store_public_id}/subscription` | `200` |

**Plan.** Usá un plan existente aprobado o creá uno con nombre y precio acordados. Si se omiten, el schema define `currency = ARS`, `billing_interval = monthly`, `max_staff = null` y `max_services = null` (sin límite configurado por esos campos). El precio es obligatorio. Confirmá que el plan final refleje el acuerdo; estos defaults no fijan un precio ni una oferta.

**Tienda.** Nombre y slug son obligatorios y el slug debe ser único. Valores que asigna el backend si se omiten: `logo_url = null`, `primary_color = #000000`, `cancellation_hours = 24`, `buffer_minutes = 0`, `send_email_confirmation = true` y `send_email_reminders = true`. La ficha queda activa y puede resolverse públicamente antes de que se complete el resto del alta. Revisá y ajustá estos datos antes de compartir el portal.

**Administrador.** El alta pide email, contraseña inicial, nombre y apellido; teléfono es opcional. Creá la cuenta en la tienda recién creada, verificá el acceso con el titular y entregá la contraseña por el canal seguro acordado. No la reutilices en evidencias.

**Suscripción y vencimiento.** Asigná el plan desde el detalle de la tienda y cargá el período acordado. El backend admite los estados `active`, `past_due`, `suspended` y `cancelled`; para una suscripción nueva el estado predeterminado es `active`. Si no se envían `base_amount` o `currency`, toma el precio y la moneda del plan. Aunque la API admite omitir `current_period_start` y `current_period_end`, en esta alta ambos deben quedar acordados y la fecha de fin debe ser explícita. El backend limita cada fecha a una ventana de cinco años alrededor de la fecha actual. Volvé al resumen y verificá plan, estado, importe, moneda y `current_period_end`; si falta la fecha de fin, no cierres el alta.

## 3. Completar la operación de la tienda

El administrador de la tienda entra a `/dashboard/settings`, `/dashboard/services` y `/dashboard/staff`:

1. **Identidad y contacto:** completá rubro, nombre, slug, logo, descripción y enlaces. Cargá el WhatsApp de atención solo si el negocio controla ese número y quiere publicarlo.
2. **Horarios del local:** una tienda nueva empieza sin franjas. La semana vacía significa que todos los días están cerrados; configurá los horarios acordados en hora local. No des por válida una semana vacía ni conserves un horario sugerido sin confirmación. Actualmente se admite un solo período de apertura por día.
3. **Servicios:** cargá nombre, duración, precio, estado activo, adicionales y modalidad/importe de seña según el acuerdo. Una seña obligatoria necesita un canal disponible antes de guardar y ofrecer el servicio.
4. **Personal y recursos:** agregá cada profesional o recurso, asignale los servicios y revisá su disponibilidad. Una persona requiere nombre, apellido y email; una sala/box puede ser un recurso sin cuenta. Si un profesional no tiene horarios propios, usa los horarios del local; confirmá que sea intencional.
5. **Políticas y coordinación:** publicá la política de seña y cancelación que aprobó el negocio. Para la coordinación manual por WhatsApp, cargá un número válido del negocio y habilitá `allow_manual_coordination`. El cliente verá la política y la opción de coordinación antes de reservar.
6. **Confirmaciones por email:** los avisos de confirmación y recordatorio parten habilitados al crear la tienda. Revisá los valores acordados y prepará una casilla sintética con un servidor SMTP de captura para QA; sin esa infraestructura no marques el envío como validado.

### Defaults exactos de las funciones

El schema actual inicializa todas las flags de la tienda en `false`:

| Flag | Valor inicial |
| --- | --- |
| `payments` | `false` |
| `ledger` | `false` |
| `advanced_reports` | `false` |
| `new_calendar` | `false` |
| `otp_booking` | `false` |
| `multi_service_booking` | `false` |

Habilitá solo flags aprobadas. Mercado Pago requiere `payments = true`. No habilites `multi_service_booking` por el solo hecho de que exista la opción: requiere aprobación de producto.

## 4. Mercado Pago en modo de prueba

Este paso requiere que infraestructura haya configurado OAuth de Mercado Pago para el entorno de QA, incluida la URL de retorno exacta registrada en la aplicación, y que el entorno de pruebas pueda recibir el webhook del proveedor. Los nombres de configuración relevantes son `MERCADOPAGO_OAUTH_CLIENT_ID`, `MERCADOPAGO_OAUTH_CLIENT_SECRET`, `MERCADOPAGO_OAUTH_REDIRECT_URI` y `MERCADOPAGO_WEBHOOK_SECRET`; sus valores se cargan fuera del repositorio y nunca se copian aquí.

1. En una tienda aislada, el admin publica la política de seña y habilita `payments` según la aprobación recibida.
2. En Ajustes > Mercado Pago, inicia la conexión y autoriza la cuenta de vendedor **de prueba** indicada para QA. El backend inicia OAuth en `POST /payments/mercadopago/oauth/start`; el proveedor vuelve a `GET /payments/mercadopago/oauth/callback`, que redirige al panel con el resultado de conexión.
3. Confirmá que el panel indique conexión y que la configuración corresponda a la cuenta de prueba. Para el checkout, usá únicamente los datos de comprador de prueba que provea la cuenta de Mercado Pago en su entorno de prueba.
4. Desde el portal de QA, completá una reserva sintética con una seña por Mercado Pago. Antes de continuar, verificá visualmente que el checkout y la cuenta sean de prueba; si no podés confirmarlo, detené la prueba. No ingreses una tarjeta real ni autorices un cobro real.
5. Comprobá que el retorno al portal solo consulta el estado y que el webhook firmado confirma la reserva después de que el backend valida el pago. Guardá únicamente IDs de prueba y el resultado, sin credenciales ni datos personales.

El código implementa Checkout Pro y OAuth por tienda, pero no expone una opción que garantice por sí sola que una conexión o un checkout sean sandbox. La cuenta de prueba, la aplicación, el webhook y el checkout se deben confirmar en el entorno de Mercado Pago antes del ensayo. No se ejecutó ni se verificó Mercado Pago sandbox durante esta sesión.

## 5. WhatsApp y pruebas de correo

Para probar el canal manual, configurá en la tienda de QA un WhatsApp de prueba controlado, `allow_manual_coordination = true` y un servicio con seña según el escenario. Usá datos sintéticos y un destinatario de prueba acordado. Verificá la pantalla de reserva, el enlace de coordinación y el registro manual de la seña desde el panel; no contactes clientes ni el número productivo como parte de QA.

Para un servicio con seña obligatoria, el backend necesita al menos un canal válido: Mercado Pago con `payments` habilitado y cuenta conectada, o WhatsApp con coordinación manual habilitada. Si no hay Mercado Pago utilizable, una seña obligatoria no admite reservas más allá de 30 días de anticipación. El flujo de correo exige una casilla de prueba y SMTP de captura para verificar entrega sin enviar mensajes a clientes reales.

## 6. Checklist de cierre de QA

Mateo y el administrador de la tienda marcan cada punto con evidencia saneada. Si el entorno o la cuenta de prueba no está disponible, usar **NO EJECUTADA**, indicar responsable y dejar el alta incompleta.

- [ ] La prueba corre en una tienda aislada, no en producción, y no usa datos de clientes.
- [ ] El plan, estado e importe acordados están visibles y la suscripción tiene `current_period_end` con la fecha de fin acordada.
- [ ] Los seis defaults de flags se revisaron; cada cambio respecto de `false` tiene aprobación.
- [ ] La URL pública `/booking/{slug}` o `/b/{slug}` responde HTTP `200` y muestra la tienda correcta, sus horarios, servicios, contacto y política. Un `200` del frontend solo no reemplaza revisar el contenido.
- [ ] Se completó una reserva de prueba por cada canal que ofrece la tienda: Mercado Pago con vendedor/comprador sandbox y webhook de prueba; WhatsApp/manual con número controlado de QA y datos sintéticos. No se acepta una prueba de cobro en producción.
- [ ] La reserva por Mercado Pago termina con el estado correspondiente al resultado confirmado por el webhook; la reserva manual muestra el canal WhatsApp y puede registrarse desde el panel.
- [ ] La confirmación llega a una casilla controlada en el SMTP de captura. Si no hay SMTP de prueba, queda **NO EJECUTADA**.
- [ ] Mateo revisó la evidencia y Enrique tomó la decisión de anunciar; resolver antes todo pendiente legal, comercial o de servicio externo.

**Estado de esta sesión:** no se ejecutó onboarding ni se crearon reservas; no se probaron Mercado Pago sandbox, entrega de correo/SMTP ni la URL de ninguna tienda. Los códigos de éxito y rutas arriba son los definidos actualmente por el código; el checklist HTTP `200` queda pendiente de ejecución en QA.

## Referencias de implementación

- [Rutas del portal y panel](../frontend/src/presentation/routes/appRoutes.ts), [API SuperAdmin y altas](../backend/modules/superadmin/router.py), [schemas SuperAdmin](../backend/modules/superadmin/schemas.py) y [modelo de suscripción](../backend/modules/billing/model.py).
- [Defaults de flags](../backend/modules/stores/schemas.py), [horarios del local](../backend/modules/stores/model.py), [reglas de canal de seña](../backend/modules/payments/deposit_channels.py) y [rutas OAuth y cobros](../backend/modules/payments/router.py).
- [Configuración Mercado Pago](MERCADOPAGO_SETUP.md) y [procedimiento completo de publicación](ALTA_TIENDA_RUNBOOK.md).
