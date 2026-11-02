# Runbook de alta y publicación de una tienda

**Resultado:** una tienda queda configurada, comprobada con datos de prueba controlados y lista para que Enrique decida anunciarla. Crear la ficha no carga horarios, catálogo, personal ni suscripción; tampoco solicita la aceptación del contrato. **La tienda nace activa y su página pública puede resolver incluso sin suscripción:** aquí «publicar» significa compartir o anunciar el enlace, no mantenerlo oculto. Prepará todos los datos antes del alta productiva y hacela en una ventana controlada.

## Recorrido rápido

1. Resolver datos comerciales, reglas de agenda, canal de seña y revisión contractual.
2. En SuperAdmin, crear o elegir el plan, crear la tienda y su administrador, y asignar una suscripción con período explícito.
3. Completar identidad, horarios, políticas, servicios, personal, cobros y funciones aprobadas.
4. Recorrer el portal, una reserva de prueba, el email y el panel con una tienda y datos controlados.
5. Registrar evidencia. Mateo valida el recorrido; Enrique decide si se anuncia.

## 1. Preparar decisiones y datos

No uses los valores que propongan los formularios como decisiones comerciales. Reuní estos datos antes de crear una tienda productiva.

| Dato por confirmar | Responsable |
|---|---|
| Plan existente o por crear; importe, moneda, estado y fechas de inicio y fin del período | Enrique confirma el acuerdo comercial; el contador revisa impuestos y facturación. Este runbook no fija precios ni obligaciones tributarias. |
| Nombre público, slug, rubro, logo, descripción, contactos y enlaces que se publicarán | Enrique y el administrador designado por la tienda. |
| Horario por día, días cerrados, cancelación, anticipación mínima y buffer | Enrique y el administrador de la tienda. |
| Servicios, duración, precio, adicionales, tipo y monto de seña | Enrique confirma el acuerdo comercial; el administrador carga los datos. |
| Canal de cada seña obligatoria | Administrador de la tienda: Mercado Pago conectado a la cuenta del negocio con `payments` habilitado, o coordinación manual por un WhatsApp válido cuando el flujo lo permita. Para reservas a más de 30 días se requiere Mercado Pago utilizable; WhatsApp por sí solo no alcanza. |
| Funciones que se habilitarán | Enrique confirma que cada función está aprobada. `multi_service_booking` permanece apagado mientras siga pendiente D-20261016-02. |
| Contrato y aceptación | El abogado confirma el texto y el flujo aplicable; Enrique confirma su resolución antes de anunciar. La pantalla de alta no solicita esta aceptación y este runbook no la completa. |
| Tienda de QA, casilla y datos de prueba controlados; cuenta de prueba de Mercado Pago si se verifica ese canal | Mateo y el administrador designado. No uses datos de clientas ni credenciales reales en la evidencia. |

**Valores técnicos que requieren confirmación:** el formulario propone el color `#ff8c42`, pero el schema del backend usa `#000000` si se omite. El alta asigna cancelación de 24 h, buffer 0 y avisos por email activos. El horario nuevo empieza vacío (todos los días cerrados); al abrir un día, el editor propone 09:00–18:00. La API permite un solo tramo de apertura por día. La anticipación mínima también tiene un valor inicial en el editor. Reemplazá cada propuesta por el valor confirmado; no aceptes un default por omisión.

Si falta una decisión comercial, un canal necesario para las señas, una fecha de fin o la resolución contractual, no empieces el alta productiva. La API permite omitir algunos importes y fechas de suscripción, incluida `current_period_end`; si se omiten importe o moneda, la asignación puede tomar los valores del plan. Confirmá el resultado final en el resumen: la ausencia de validación técnica no convierte esos datos en opcionales para este procedimiento.

> **Límite de publicación:** no hay un estado de borrador en la creación. El backend guarda la tienda activa y el portal filtra por actividad, no por existencia de una suscripción; por eso no cuentes con que una tienda incompleta quede oculta. Si el alta se interrumpe después de crearla, no compartas el enlace y avisá a Enrique y Mateo para que decidan cómo contener la exposición. `is_active=false` oculta la página, pero el acceso del administrador mientras la tienda está inactiva no tiene una prueba dedicada; no uses esa medida como paso automático del runbook.

## 2. Crear la tienda, el acceso y la suscripción

1. **Comprobá el entorno y el estado de la tienda.** La creación se hace desde `/control-global`, solo con una cuenta SuperAdmin. No existe registro público de tiendas. La ficha de tienda, la cuenta administradora y la suscripción se crean por separado. La ficha queda activa al crearla; la falta de suscripción no la mantiene privada.
2. **Prepará el plan.** En SuperAdmin, usá un plan existente aprobado o creá el plan acordado. Confirmá nombre, precio, moneda e intervalo de facturación antes de asignarlo.
3. **Creá la tienda.** En la sección de tiendas, cargá nombre y slug únicos. Revisá el color y los valores iniciales de cancelación, buffer y avisos. No asumas que esta pantalla completa identidad pública, horarios, servicios o personal.
4. **Creá la cuenta administradora.** En la tienda recién creada, ingresá nombre, apellido, email y contraseña inicial; el teléfono es opcional. Verificá el acceso y entregá la credencial solo por el canal seguro acordado. No la incluyas en notas, capturas ni evidencia.
5. **Asigná el plan y el período.** En el detalle de la tienda, cargá plan, estado acordado, importe base, moneda y fechas explícitas. Si el servicio comienza en este momento, Enrique debe confirmar el estado `active`; no lo selecciones por defecto. Volvé al resumen y verificá plan, estado, importe, moneda y fecha de fin. Si falta la fecha o no coincide con lo acordado, el alta queda incompleta.

## 3. Configurar agenda, catálogo, cobros y funciones

Desde `/dashboard/settings`, completá los datos de la tienda con la cuenta administradora:

1. **Identidad:** rubro, nombre y slug públicos, logo, color, portada, descripción, WhatsApp y enlaces/redes que correspondan. Revisá el resultado con el portal público.
2. **Horarios:** en hora argentina, para cada día elegí explícitamente un tramo de apertura o dejalo cerrado intencionalmente. No conserves por inercia la propuesta 09:00–18:00. El sistema acepta un solo tramo por día; si el negocio necesita horario partido, detené el alta y escalá a Mateo y Enrique porque el producto no lo soporta hoy.
3. **Políticas:** cargá los valores aprobados de cancelación, anticipación mínima, buffer, coordinación manual y texto de política de seña/cancelación. Revisá los campos personalizados del formulario de reserva y agregá solo los que el negocio realmente necesite. Para completar esta verificación, dejá habilitadas las confirmaciones por email; configurá los recordatorios según lo acordado. Si se decide apagar las confirmaciones, la checklist de email no queda aprobada y Enrique debe resolver esa excepción antes de anunciar.
4. **Servicios:** en `/dashboard/services`, creá cada servicio con nombre, duración, precio, estado activo y configuración de seña acordada. Cargá los adicionales que correspondan. Una seña obligatoria sin un canal disponible bloquea la creación o disponibilidad del servicio; corregí el canal antes de continuar.
5. **Personal y recursos:** en `/dashboard/staff`, agregá cada persona o recurso, asignale los servicios que atiende y verificá que esté activo. Una persona requiere nombre, apellido y email; la ficha no crea una contraseña utilizable. Si necesita iniciar sesión, resolvé su acceso por el flujo separado antes de contarla como usuaria del panel. Un recurso como sala o box no requiere email ni cuenta. Revisá los horarios propios desde “Horarios” por profesional. Si la lista de horarios propios queda vacía, ese profesional usa los horarios de la tienda (D-20260929-01); confirmá que ese resultado sea intencional.
6. **Canal de seña:** si se usa Mercado Pago, el administrador conecta por OAuth la cuenta de Mercado Pago del propio negocio desde Ajustes > Mercado Pago y se habilita `payments` según lo aprobado. Si se usa coordinación manual, verificá el número de WhatsApp publicado y que `allow_manual_coordination` esté habilitado. Para señas obligatorias en reservas a más de 30 días, verificá Mercado Pago utilizable; la coordinación por WhatsApp no cubre ese caso.
7. **Funciones:** en Ajustes > Funciones, revisá las flags de la tienda (`payments`, `ledger`, `advanced_reports`, `new_calendar`, `otp_booking` y `multi_service_booking`). Parten apagadas por defecto. Habilitá solo lo aprobado y necesario para la operación. Mantené `multi_service_booking` apagado mientras D-20261016-02 no tenga aprobación expresa.

## 4. Verificación segura antes de anunciar

Hacé las pruebas que mutan datos (reserva, email, flujo del panel y canal de pago) con una tienda destinada a QA, una casilla controlada y datos sintéticos. En producción limitate a comprobaciones de lectura de página, disponibilidad, suscripción, configuración, flags y canal conectado; no crees reservas ni inicies cobros allí. No uses Jaziz Nails para probar pagos. No uses la tienda pública `ejemplo` hasta verificar que se desconectó su Mercado Pago real, se apagaron los cobros reales y se retiró el logo de LEGO.

- [ ] En la tienda de QA, `/booking/<slug>` o `/b/<slug>` muestra el negocio correcto, sus contactos y sus políticas, sin contenido ajeno. En la tienda productiva, revisá página y disponibilidad sin crear reservas.
- [ ] **Producción:** la suscripción de esta tienda coincide con el acuerdo: plan, estado, importe, moneda y período con fecha de fin explícita.
- [ ] **Producción:** cada día está abierto con el horario acordado o cerrado intencionalmente; la disponibilidad pública refleja la semana esperada.
- [ ] **Producción:** cada servicio activo muestra duración, precio, adicionales y seña acordados; el personal o recurso correcto puede atenderlo.
- [ ] **Producción:** para cada seña obligatoria, confirmá sin iniciar un cobro que el canal elegido está configurado: cuenta de Mercado Pago del negocio conectada y `payments` activo, o WhatsApp válido con `allow_manual_coordination` activo. Para reservas a más de 30 días, debe estar utilizable Mercado Pago.
- [ ] **QA:** para una seña obligatoria, el canal correspondiente aparece y funciona en el flujo de reserva. El código no garantiza un modo de prueba de Mercado Pago: confirmá que la cuenta y el checkout sean realmente de prueba antes de abrirlos y no completes un pago. Si no podés confirmar un entorno seguro, anotá el bloqueo y no anuncies un servicio que dependa de ese canal.
- [ ] **QA:** se completa una reserva de prueba con datos sintéticos. La confirmación llega a la casilla controlada y la reserva aparece en el panel con el servicio, profesional, horario y estado esperados. Si las confirmaciones se deshabilitaron, no marques esta prueba como aprobada; Enrique debe resolver la excepción antes de anunciar.
- [ ] **Producción:** las flags reflejan lo aprobado; `multi_service_booking` continúa apagado mientras D-20261016-02 no tenga aprobación expresa.
- [ ] El abogado confirmó por el flujo separado cómo quedan resueltos el contrato y su aceptación. La pantalla de alta no registra esa aceptación.

No hagas una captura, transferencia ni pago de producción como prueba. Si alguna comprobación falla o depende de una cuenta de prueba no disponible, marcá el alta **incompleta**, anotá quién lo resuelve y no anuncies ni compartas el enlace de reservas.

**Resolución de bloqueos:**

| Bloqueo | Quién lo resuelve |
|---|---|
| Plan, precio, moneda, período o política comercial sin confirmar | Enrique; el contador resuelve impuestos y facturación. |
| Identidad, horario, catálogo, personal o contacto incompleto | Administrador de la tienda, con Enrique para las decisiones del negocio. |
| Mercado Pago/WhatsApp no conectado o sin entorno de prueba seguro | Administrador de la tienda prepara el canal; Mateo valida el procedimiento. Hasta entonces no se anuncia la seña dependiente de ese canal. |
| Contrato o aceptación sin resolver | Abogado y Enrique; el runbook no reemplaza esa revisión. |
| Requisito pendiente después de crear la ficha activa | Avisar a Enrique y Mateo. La tienda puede ser pública; ellos resuelven cómo contenerla antes de continuar. |

## 5. Decisión de publicar y registro

Enrique decide si se anuncia solo después de que se cumpla la checklist y se resuelvan los puntos comerciales y contractuales. Mateo debe recorrer el procedimiento completo con una tienda de prueba segura y confirmar que los pasos coinciden con la operación actual. Hasta entonces, el runbook y la tienda no se consideran validados para venta.

Registrá fecha, entorno, slug de prueba, plan/estado/fecha de fin, resultado de cada verificación, canal de seña probado, alias de la casilla controlada, responsable de cada bloqueo y referencia a evidencia saneada. No guardes contraseñas, tokens OAuth, datos de clientas ni comprobantes con datos personales. Si queda un requisito pendiente, dejá constancia de **alta incompleta**, su responsable y la acción para resolverlo.

## Referencias

- [Pantallas y permisos de SuperAdmin](../frontend/src/presentation/routes/appRoutes.ts), [`SuperAdmin.tsx`](../frontend/src/presentation/pages/SuperAdmin.tsx), [formularios de tienda y administrador](../frontend/src/presentation/pages/superadmin/StoreModals.tsx), [modal de plan y suscripción](../frontend/src/presentation/pages/superadmin/PlanModals.tsx), [API de SuperAdmin](../backend/modules/superadmin/router.py) y [schemas de alta y suscripción](../backend/modules/superadmin/schemas.py).
- [Defaults de actividad](../backend/core/models.py), [filtro de la vitrina pública](../backend/modules/public_api/repository.py), [bloqueo por suspensión](../backend/modules/billing/service.py) y [pruebas de visibilidad](../backend/tests/integration/test_referencia_publica_de_tienda.py). La visibilidad de una tienda nueva sin suscripción se deduce de esas guardas; no encontré un test dedicado a ese caso.
- [Configuración del gateway y enlace de pago](../backend/modules/payments/model.py), [selección de URL de checkout](../backend/modules/payments/service.py): el código no ofrece una garantía general de sandbox.
- [Configuración del negocio](../frontend/src/presentation/pages/Settings.tsx), [editor de horarios](../frontend/src/presentation/components/organisms/settings/SettingsScheduleTab.tsx), [editor de políticas](../frontend/src/presentation/components/organisms/settings/SettingsPoliciesTab.tsx), [schema de tienda y horarios](../backend/modules/stores/schemas.py), [modelo de tienda y horario vacío](../backend/modules/stores/model.py).
- [Catálogo y canal de seña](../backend/modules/services/service.py), [`deposit_channels.py`](../backend/modules/payments/deposit_channels.py), [conexión de Mercado Pago](../frontend/src/presentation/components/organisms/settings/SettingsPaymentsTab.tsx), [alta de fichas de personal](../backend/modules/staff/repository.py).
- [Personal y horarios](../frontend/src/application/services/StaffService.ts), [`StaffScheduleModal.tsx`](../frontend/src/presentation/components/organisms/StaffScheduleModal.tsx), [flujo separado de aceptación legal](../backend/modules/legal/router.py) y [decisiones del proyecto](DECISIONES.md): D-20260909-01 (alta solo desde SuperAdmin), D-20260929-01 (sin horario propio se usa el de la tienda) y D-20261016-02 (multi-servicio apagado mientras no se apruebe).