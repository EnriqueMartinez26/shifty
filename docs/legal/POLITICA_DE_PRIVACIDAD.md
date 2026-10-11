> **BORRADOR: requiere revisión de un abogado matriculado antes de publicarse. No constituye asesoramiento legal.**

# Política de privacidad

**Versión:** [[COMPLETAR: fecha de vigencia, AAAA-MM-DD]]
**Historial de versiones:** `/legal/privacidad/historial`

Este borrador reúne información para revisar el deber de informar del art. 6 de la Ley 25.326. **No se afirma que esté completo ni que cumpla ese deber:** contiene datos pendientes y requiere validación de un abogado matriculado antes de publicarse.

## 1. Quién responde por cada dato

Shifty es un software de turnos que usan comercios y profesionales (**las Tiendas**). Según el caso, el responsable de los datos cambia:

| Datos | Responsable | Rol de Shifty |
|---|---|---|
| De quien reserva un turno, se anota en una lista de espera o paga una seña en el portal de una Tienda (**Clientes**) | **La Tienda** del portal donde se reservó. Sus datos (nombre o razón social, CUIT, domicilio y correo de reclamos) figuran en su portal y en los correos del turno. | **Encargado del tratamiento** (Ley 25.326, art. 25): trata los datos por cuenta de la Tienda y según sus instrucciones, en los términos del Acuerdo de Tratamiento firmado con ella. |
| De la cuenta de acceso del personal y de los administradores de las Tiendas (**Usuarios del panel**) | **Shifty** | Responsable. |
| De las Tiendas como clientes de Shifty: contacto, plan y facturación | **Shifty** | Responsable. |
| Del pago con Mercado Pago (medio de pago, datos del pagador) | **Mercado Pago**, según sus propias políticas | Shifty no es parte de ese tratamiento. |
| Eventos opcionales de uso del portal de reserva enviados a GA4 tras aceptar analítica | La finalidad de medición la define Shifty; quién es jurídicamente responsable y el rol de Google deben confirmarse con asesoramiento profesional. | [[COMPLETAR: roles jurídicos de Shifty y Google para esta finalidad]] |

**Datos de Shifty:** [[COMPLETAR: razón social o nombre del titular de Shifty]], CUIT [[COMPLETAR: CUIT de Shifty]], domicilio en [[COMPLETAR: domicilio legal de Shifty]]. Correo para temas de datos personales: [[COMPLETAR: email de privacidad de Shifty]]. Inscripción en el Registro Nacional de Bases de Datos: [[COMPLETAR: número de inscripción AAIP]].

> **Nota para el abogado (NA-1):** L1 (riesgo 2, P-2) advierte que hay conductas que un encargado no tiene y que pueden hacer que Shifty sea tratado como responsable o cesionario:
> - el email del cliente único en toda la plataforma (PV-01). **Corregido** en la rama de integración: el email de un cliente es único por Tienda, y el del personal y los administradores sigue siendo único global (migración `4b6d8f0a2c13`, decisión de Mateo; checklist BE-06). El mismo email ya puede reservar en varias Tiendas;
> - los correos firmados "El equipo de Shifty". **Corregido en parte:** cada correo al Cliente dice que se envía en nombre de la Tienda a través de Shifty, por qué le llega y enlaza esta política. Siguen pendientes el remitente y la respuesta a la Tienda (checklist BE-07);
> - el correo promocional sin instrucción escrita de la Tienda. Ya tiene baja por Cliente y por Tienda (checklist BE-04, en parte);
> - la lectura de clientes por el superadmin sin rastro.
>
> Este borrador supone que las conductas que quedan se corrigen (checklist BE-04, BE-07, BE-11). Confirmar si con eso alcanza.

> **Nota para el abogado (NA-9):** confirmar qué bases de Shifty se inscriben (cuentas del panel, tiendas y facturación, auditoría) y cómo se declara el rol de encargado (L1 P-3).

## 2. Datos de los Clientes

| Momento | Datos | ¿Obligatorio? | Si no se dan |
|---|---|---|---|
| Reserva | Nombre | Sí | No se puede reservar. |
| Reserva | Teléfono | Sí. Identifica al Cliente en esa Tienda. | No se puede reservar. |
| Reserva | Correo electrónico | Facultativo. Es obligatorio si la Tienda exige validar el teléfono con un código. | No llegan la confirmación, los recordatorios ni los avisos. Si la Tienda exige el código, no se puede reservar. |
| Reserva | Notas para la Tienda | Facultativo | Ninguna consecuencia. |
| Reserva | Respuestas a las preguntas que agrega la Tienda | Lo define la Tienda: el portal marca cuáles son obligatorias | Si la pregunta es obligatoria, no se puede reservar. |
| Reserva | Aceptación de las condiciones, con su fecha y la versión de los textos | Sí | No se puede reservar. |
| Validación por código | Teléfono, correo al que se envía el código y una huella cifrada (hash) del código | Sí, si la Tienda la exige | No se puede reservar ni entrar a "Mis turnos". |
| Lista de espera | Nombre, teléfono y correo | Nombre y teléfono, sí. Correo, facultativo. | Sin correo, **no llegan las ofertas de turno**, porque es el único canal. |
| Seña | Nombre y correo, que se envían a Mercado Pago para crear el link de pago; estado, importe e identificadores del pago que devuelve Mercado Pago | Sí, para pagar online | No se puede pagar la seña online. |
| Cancelación desde "Mis turnos" | Motivo | Facultativo | Ninguna consecuencia. |
| Uso del portal | Dirección IP, navegador y páginas pedidas, en los registros técnicos del servidor | Sí (técnico) | — |
| Uso del portal, solo si se acepta la analítica | Datos del dispositivo y del navegador, dirección IP, identificadores guardados en cookies y eventos genéricos del flujo de reserva, que recibe Google (ver 9.1) | Facultativo | Ninguna consecuencia: se puede reservar igual. |

Shifty **no recibe los datos completos de la tarjeta** ni del medio de pago: los trata Mercado Pago.

**No se deben incluir datos de salud** ni otros datos sensibles en las notas ni en las respuestas, salvo que la Tienda sea un profesional o establecimiento de salud y lo pida con un aviso específico (ver 10).

## 3. Para qué se usan los datos de los Clientes

| Finalidad | Base |
|---|---|
| Registrar y gestionar el turno: agenda de la Tienda, confirmación, reprogramación y cancelación | Relación contractual entre el Cliente y la Tienda (Ley 25.326, art. 5, inc. 2.d) |
| Enviar por correo el registro, la confirmación, los recordatorios (24 y 2 horas antes) y los avisos de cambios | Relación contractual |
| Validar que quien reserva o consulta "Mis turnos" es titular del teléfono | Relación contractual y seguridad |
| Ofrecer por correo un turno liberado, a quien se anotó en la lista de espera | Pedido del Cliente al anotarse |
| Crear el link de pago de la seña en Mercado Pago y registrar si se pagó | Relación contractual |
| Calcular la seña: **puede variar según el historial de asistencia del Cliente en esa Tienda**, si la Tienda configuró un recargo para clientes nuevos o para clientes que faltaron | Relación contractual; se informa acá |
| Invitar al Cliente a volver a reservar, en un correo posterior al turno, **solo si la Tienda activó ese envío** | [[COMPLETAR: consentimiento previo del Cliente / interés de la Tienda con baja en cada correo, según la decisión NA-8]] |
| Detectar errores del sistema y abusos del portal | Seguridad del servicio |
| Medir interacciones con el portal mediante GA4, solo después de aceptar la opción de analítica | La interfaz solicita una aceptación opcional. Confirmar con el abogado la base jurídica, el rol de cada parte y el alcance de la información previa antes de publicar. |

Los datos operativos del Cliente para la agenda de una Tienda **no se usan en otra Tienda ni se venden**. La analítica opcional de GA4 es una finalidad separada que mide el uso del portal para la plataforma, solo después de aceptar. La etiqueta desactiva Google Signals y envía desactivadas las señales de personalización publicitaria. En la propiedad revisada el 11 de octubre de 2026, Google Signals y Medición mejorada están desactivados, pero la personalización publicitaria está permitida en 307/307 regiones configurables; no hay vínculo con Google Ads. Esto no permite afirmar que esa capacidad esté desactivada globalmente. El rol legal de Shifty y Google, la base jurídica y los demás destinos quedan pendientes de revisión profesional.

> **Nota para el abogado (NA-8):** el correo "Gracias por tu visita, reservá tu próximo turno" es publicitario (L1 O-8, P-16). El backend de la rama de integración ya tiene la baja por Cliente y por Tienda, con un enlace firmado en el correo, y el envío saltea a quien se dio de baja (checklist BE-04). Faltan la página de confirmación del front y los encabezados `List-Unsubscribe`. Hay que decidir si alcanza con eso (retiro o bloqueo en cada comunicación, Ley 25.326 art. 27, inc. 3, verificado) o si además hace falta una casilla opcional y desmarcada al reservar, como recomienda L1 §4.7. L1 no verificó el inc. 1 del art. 27.

> **Nota para el abogado (NA-15):** revisar si alcanza con informar el recargo por historial (L1 §7.5).

## 4. Datos de los Usuarios del panel y de las Tiendas

| Datos | Finalidad | Base |
|---|---|---|
| Nombre, apellido, correo, teléfono, rol y Tienda | Crear y administrar la cuenta de acceso | Relación contractual con la Tienda |
| Contraseña, guardada solo como hash | Autenticar | Relación contractual y seguridad |
| Sesiones: dirección IP, navegador, fecha de inicio y de vencimiento | Seguridad: ver y cerrar sesiones, detectar accesos indebidos | Seguridad |
| Registro de auditoría de cambios: quién cambió qué y cuándo | Seguridad y prueba ante reclamos | Interés legítimo en la seguridad |
| De la Tienda: nombre comercial, datos fiscales, plan, vencimientos, importes | Prestar el servicio y facturar | Relación contractual |
| Nombre de visualización del profesional | Mostrarlo en el portal de la Tienda para que el Cliente lo elija | Instrucción de la Tienda |

## 5. Quién recibe los datos

| Destinatario | Qué recibe | Para qué | País |
|---|---|---|---|
| **La Tienda** y su personal | Los datos de sus Clientes. El correo y el teléfono completo solo los ven los administradores. | Atender el turno | Argentina |
| **Mercado Pago** | Nombre y correo del pagador, servicio e importe de la seña | Procesar el pago | [[COMPLETAR: país de tratamiento que declara Mercado Pago]] |
| **[[COMPLETAR: proveedor de hosting efectivamente utilizado]]** | Datos alojados por el servicio | Alojamiento | [[COMPLETAR: país/región confirmados]] |
| **[[COMPLETAR: proveedor SMTP]]** (envío de correo) | Correo y nombre del destinatario, y el contenido del aviso (servicio, fecha, hora, Tienda, código de validación) | Enviar los correos | [[COMPLETAR: país/región del proveedor SMTP]] |
| **Sentry** (monitoreo de errores) | Informes de error sin los datos de la persona: se quitan el cuerpo de los pedidos, las cookies, los encabezados de autenticación, los parámetros de las direcciones y las variables del programa, y se enmascaran los teléfonos de las rutas. Desde el navegador, Sentry no recibe la IP del usuario. | Detectar y corregir fallas | [[COMPLETAR: región del proyecto de Sentry (EE. UU. o UE)]] |
| **[[COMPLETAR: proveedor de backups]]** (copias de seguridad) | Copia completa de la base de datos | Recuperar el servicio ante una falla | [[COMPLETAR: región del proveedor de backups]] |
| **Google Analytics (GA4)**, si está habilitado y el Cliente acepta | Eventos genéricos de uso, una página informada fija y datos técnicos de conexión del navegador. La integración no agrega campos del formulario, el identificador del turno ni la URL completa. En la propiedad revisada, Medición mejorada, Google Signals y recopilación de datos proporcionados por usuarios están desactivados; la personalización publicitaria se permite en 307/307 regiones, sin vínculo con Google Ads. | Medir el uso del portal de reserva | [[COMPLETAR: entidad contratante y país/región de tratamiento verificados en la cuenta y los términos de Google]] |
| Autoridades | Lo que exija una orden judicial o una norma | Cumplir la ley | Argentina |

> **Nota para el abogado (NA-13):** ¿Mercado Pago es un responsable propio frente al pagador o un subencargado? ¿Qué obligaciones tiene Shifty como integrador, según las cláusulas 6.2, 6.7 y 10 de los términos para desarrolladores (L1 P-10)?

**Dependencias de producto (no publicar la frase hasta que estén resueltas):**
- "Shifty no recibe los datos completos de la tarjeta" y la fila de Mercado Pago de la sección 2 suponen resuelto L3-01. **Resuelto en el backend** (checklist BE-05): de cada pago se guarda solo una lista de campos: los datos técnicos de la notificación (tipo, acción, recurso, fecha y cuenta de Mercado Pago) y, del pago, identificador, estado, referencia externa, fecha de aprobación, importe, moneda, cuenta cobradora, modo de prueba o real, identificador de la preferencia y los identificadores internos de Shifty; de la preferencia, su identificador y los links de pago. No se guardan el nombre, el correo ni la identificación del pagador, ni datos de la tarjeta. Las filas anteriores se recortaron con una migración. Se publica cuando esté en producción.
- "El correo y el teléfono completo solo los ven los administradores" supone resuelto L3-03. **Resuelto en las cuentas pendientes** (checklist BE-13): el personal ve el nombre y los últimos 3 dígitos del teléfono, sin correo, y busca solo por nombre. **Falta** BE-29: la búsqueda de turnos del personal compara el texto también con el correo del Cliente, y la agenda muestra el correo como nombre si el Cliente no tiene nombre. Hasta cerrar BE-29, la frase no se publica.
- "Aceptación de las condiciones, con su fecha y la versión de los textos" (sección 2) supone que el portal manda las versiones. El backend ya las guarda y rechaza una versión vieja (checklist BE-01), pero todavía las acepta vacías para no romper el front actual: hasta FE-04, el turno guarda la fecha de aceptación sin la versión.
- La **exportación** y la **anonimización** de la sección 8.2 existen en el backend (checklist BE-03), pero el panel todavía no tiene la pantalla (checklist FE-23). Hasta entonces, la Tienda las usa por la API, según `docs/DERECHOS_DE_LOS_TITULARES.md`.
- El **enlace de baja** de la sección 8.2 ya funciona en el backend (checklist BE-04). Faltan la página de confirmación del front (checklist FE-17) y que el enlace del correo apunte a ella (checklist BE-04): hoy el enlace abre directamente la API, y un escáner de correo que lo abra puede registrar la baja sin que el Cliente la haya pedido.

## 6. Transferencias internacionales

Los proveedores pueden tratar datos fuera de Argentina. **Faltan confirmar los proveedores y países/regiones realmente usados**, incluidos hosting, Google Analytics, SMTP, monitoreo y copias de seguridad. No se debe afirmar que hay una transferencia concreta ni publicar esta sección hasta verificar esas ubicaciones y determinar para cada una el mecanismo aplicable ([[COMPLETAR: mecanismo confirmado por proveedor]]; Ley 25.326, art. 12; Decreto 1558/2001, art. 12).

> **Nota para el abogado (NA-5):** falta confirmar las regiones efectivamente usadas y elegir el mecanismo para cada transferencia (L1 riesgo 1, O-11, P-4). Hostinger en Brasil fue una opción analizada en el informe del 8 de octubre, no un proveedor productivo confirmado. Las opciones que verificó L1 son:
> - las cláusulas modelo de la Disp. DNPDP 60-E/2016 o de la Res. AAIP 198/2023;
> - un contrato propio, notificado a la AAIP dentro de los 30 días;
> - normas corporativas vinculantes;
> - el consentimiento expreso del titular.
>
> Evaluar regiones con protección adecuada cuando estén disponibles para cada proveedor. No descartar alternativas antes de confirmar proveedor y región. Esta sección no se publica sin confirmar cada ubicación y su mecanismo aplicable.
>
> Desde el 2026-10-10 la lista incluye a **Google** por la analítica del portal (NA-18): definir también su mecanismo.

## 7. Cuánto tiempo se guardan

| Dato | Plazo |
|---|---|
| Código de validación (hash), teléfono y correo del envío | Se borran 7 días después de vencido el código |
| Copia técnica de la respuesta de una reserva, para evitar duplicados | 24 horas |
| Mensajes internos de avisos pendientes y avisos de Mercado Pago ya procesados | 90 días |
| Envíos fallidos, para su diagnóstico | 365 días |
| Notificaciones del panel ya leídas | 180 días |
| Sesiones del panel | 30 días después de vencidas |
| Turnos, fichas de Clientes, lista de espera y cobros | [[COMPLETAR: plazo mientras la Tienda tenga el servicio activo]]. Al terminar el servicio con la Tienda, se le devuelven y se destruyen o anonimizan como indica el Acuerdo de Tratamiento. |
| Registro de auditoría | [[COMPLETAR: plazo]] |
| Datos de facturación de las Tiendas | [[COMPLETAR: plazo que exigen las normas fiscales]] |
| Registros técnicos del servidor (IP y rutas) | [[COMPLETAR: plazo]] |
| Copias de seguridad | Se renuevan por rotación: un dato borrado desaparece de todas las copias dentro de los 28 días |
| Preferencia de analítica (`shifty:analytics-consent:v1`) | Se conserva en el almacenamiento local hasta que se cambie o se borren los datos del sitio; el código no fija vencimiento. Si el navegador bloquea el almacenamiento, dura esa visita. |
| Cookies de GA4 de esta integración (`shifty_ga*`) | Solo después de aceptar analítica; el código configura una duración de 30 días. |
| Datos de eventos de GA4 | 2 meses, según la configuración observada en la propiedad el 11 de octubre de 2026 |
| Datos de usuario de GA4 | 14 meses; está activada la opción de borrar los datos ante nueva actividad, según la configuración observada el 11 de octubre de 2026 |

> **Nota para el abogado (NA-14):** los plazos de turnos, fichas, auditoría y facturación son decisión de Mateo y Enrique (L1 P-5). La ley pide destruir los datos cuando dejan de ser necesarios (Ley 25.326, art. 4, inc. 7).

## 8. Derechos y cómo ejercerlos

8.1. El titular de los datos tiene derecho a:

- **acceder** a sus datos;
- **rectificarlos, actualizarlos o suprimirlos**;
- pedir que **no se le envíen comunicaciones publicitarias** (Ley 25.326, arts. 14, 16 y 27).

8.2. **Clientes.** Los pedidos sobre los datos de agenda se hacen **a la Tienda**, que es la responsable según este borrador, por el correo de reclamos de su portal. También se pueden enviar a Shifty, a [[COMPLETAR: email de privacidad de Shifty]]: el procedimiento de derivación debe definirse en el Acuerdo de Tratamiento. Los pedidos sobre eventos de analítica se dirigen además a Shifty; su rol y el de Google deben validarse antes de publicar. Hay además estas vías directas:

- **"Mis turnos"**, en el portal de la Tienda, muestra los turnos del Cliente y permite cancelarlos, después de validar el teléfono;
- el enlace de **baja** que trae el correo de invitación a volver a reservar corta esos envíos;
- la preferencia de **analítica** se puede cambiar desde el portal de reserva: rechazarla o retirarla detiene nuevos envíos de esta integración y elimina sus cookies accesibles en ese navegador. No borra automáticamente información que Google ya haya recibido; confirmar el procedimiento aplicable para cualquier pedido de supresión de esos datos;
- a pedido del titular, la Tienda puede **exportar** sus datos en un archivo o **anonimizarlos**, con la herramienta que Shifty pone a su disposición (checklist BE-03).

> **Dependencia de producto:** el procedimiento para atender estos pedidos está en `docs/DERECHOS_DE_LOS_TITULARES.md`. La exportación y la anonimización se hacen por el identificador del Cliente, no por el teléfono. La anonimización se niega mientras el Cliente tenga un cobro abierto, turnos activos a futuro o saldo en las cuentas pendientes, a favor o en contra: primero se cierra eso. Falta la pantalla del panel (checklist FE-23).

8.3. **Usuarios del panel.** El pedido se envía a Shifty, a [[COMPLETAR: email de privacidad de Shifty]].

8.4. **Verificación de identidad.** Para proteger al titular, se le puede pedir que confirme un código enviado al teléfono o al correo registrados, o que acredite su identidad de otra forma razonable.

8.5. **Plazos legales:** 10 días corridos para el acceso y 5 días hábiles para la rectificación y la supresión, contados desde el pedido (Ley 25.326, arts. 14 y 16).

8.6. **LA AGENCIA DE ACCESO A LA INFORMACIÓN PÚBLICA, en su carácter de Órgano de Control de la Ley N° 25.326, tiene la atribución de atender las denuncias y reclamos que interpongan quienes resulten afectados en sus derechos por incumplimiento de las normas vigentes en materia de protección de datos personales.**

## 9. Cookies y almacenamiento en el navegador

En el portal de reserva, Shifty ofrece una opción de analítica cuando el tag está habilitado. **Solo después de aceptar** se carga Google Analytics (GA4). La recopilación se activa únicamente en el portal mientras la aceptación siga vigente. Al salir del portal o retirar la aceptación, el código bloquea la medición; si el script ya se descargó puede permanecer en la página hasta recargarla. La integración propia envía una lista cerrada de eventos del recorrido (`booking_started`, `service_selected`, `slot_selected`, `availability_empty`, `booking_error` y `booking_created`), informa una página canónica sin el slug, deja vacío el referrer y no agrega respuestas del formulario, códigos de verificación ni identificadores del turno. Google recibe además datos técnicos de conexión del navegador. En la propiedad revisada, Medición mejorada está desactivada y la retención configurada es de 2 meses para eventos y 14 meses para datos de usuario; otros destinos y la entidad/región de tratamiento siguen por confirmar.

| Elemento | Quién lo recibe | Para qué | Duración |
|---|---|---|---|
| Cookie `refresh_token`: `HttpOnly`, `Secure`, `SameSite=Lax` | Solo los Usuarios del panel, al iniciar sesión | Mantener la sesión iniciada. Es estrictamente necesaria. | 30 días, o hasta cerrar sesión |
| Almacenamiento local `shifty_user` | Solo los Usuarios del panel | Mostrar el nombre y el rol del usuario mientras se valida la sesión | Hasta cerrar sesión |
| Almacenamiento de sesión `shifty:otp:{tienda}` | Clientes que validaron su teléfono | No pedir el código otra vez durante 30 minutos | Hasta cerrar la pestaña |
| Almacenamiento local `shifty:analytics-consent:v1` | Quien elige aceptar o rechazar la analítica en el portal de reservas | Recordar esa elección | Hasta que la persona la cambie o borre los datos del sitio. Si el navegador bloquea el almacenamiento, solo durante esa visita. |
| Cookies `shifty_ga*` de Google Analytics | Clientes del portal de reserva que aceptaron analítica | Medir el recorrido de reserva | 30 días configurados por esta integración; confirmar la retención adicional en GA4 |

Sin aceptar analítica no se carga el script de GA4 ni se crean sus cookies. Al retirar la preferencia se bloquean nuevos envíos y se eliminan las cookies de esta integración accesibles desde este navegador. Si el script ya se había descargado, puede permanecer presente hasta recargar la página, pero el código deja bloqueada la medición. Al pagar en Mercado Pago o al abrir WhatsApp, el navegador pasa a un sitio de un tercero, que aplica sus propias políticas.

El portal conserva además los almacenamientos locales y de sesión descritos en la tabla; la integración no usa cookies de Google antes de aceptar analítica.

### 9.1. Analítica del portal de reservas (Google Analytics 4)

**Qué es y dónde funciona.** Shifty usa Google Analytics 4, un servicio de Google, para medir cómo se usa el portal público de reservas. La recopilación solo se activa en las páginas del portal de reserva con una aceptación vigente. Si la persona navega a otra sección de la SPA después de aceptar, el código bloquea la medición aunque el script ya descargado pueda permanecer en la página hasta recargar.

**Cuándo se activa.** Únicamente después de que la persona elige "Aceptar analítica" en el aviso del portal. Antes de esa elección, o si la rechaza, no se carga ningún script de Google ni se le envía ningún dato. La analítica es facultativa: se puede reservar sin aceptarla.

**Qué recibe Google si se acepta:**

- datos técnicos de la conexión, del dispositivo y del navegador, incluida la dirección IP, a partir de la cual Google puede estimar una ubicación aproximada;
- los identificadores que guardan las cookies de la tabla anterior;
- eventos genéricos del flujo de reserva: inicio de la reserva, elección de un servicio, elección de un horario, falta de horarios disponibles, reserva completada y error al reservar.

GA4 puede generar eventos técnicos propios, como `first_visit` y `session_start`, según la primera visita o la sesión; ambos se observaron en la prueba controlada del 11 de octubre de 2026. No corresponden a una cuenta de autenticación de Shifty.

La página se informa siempre con la misma dirección y el mismo título, sin el nombre de la Tienda, sin parámetros de la dirección y sin la página de origen.

**Qué no recibe.** Los datos que se completan al reservar (nombre, teléfono, correo, notas o respuestas) ni los identificadores de turnos, Tiendas, servicios o profesionales.

**Señales y configuración de la propiedad.** El código configura `ad_storage`, `ad_user_data` y `ad_personalization` como `denied`, desactiva Google Signals y las señales de personalización, y no envía el `page_view` inicial. En la propiedad observada el 11 de octubre de 2026, Medición mejorada, Google Signals y recopilación de datos proporcionados por usuarios están desactivados; la recopilación granular de ubicación/dispositivo está activada. La propiedad permite personalización publicitaria en 307/307 regiones configurables, pero no hay vínculo con Google Ads ni etiquetas de sitio conectadas. La ocultación de correo está activa y la de parámetros de URL está inactiva; la integración informa una ruta canónica sin query. Por eso no se debe describir la capacidad de personalización de la propiedad como desactivada globalmente. Las demás vinculaciones y la ubicación/entidad de tratamiento siguen pendientes de confirmar.

> **Pendiente de decisión y revisión profesional:** la configuración regional permite personalización publicitaria aunque el código niega las señales publicitarias y no hay vínculo con Google Ads. El responsable y su asesor deben resolver cómo describirla y si modificar la propiedad antes de aprobar este texto.

**Transferencia.** Google puede tratar estos datos fuera de Argentina (ver 6).

**Cómo retirar el consentimiento.** Desde el botón "Preferencias de analítica" del portal de reservas, eligiendo "Rechazar analítica". Desde ese momento no se envían nuevas mediciones y se borran las cookies de esta integración que sean accesibles en este navegador. Si el script ya se había descargado, puede permanecer hasta recargar la página, pero la medición queda bloqueada. Retirar el consentimiento no borra los datos que Google ya recibió. Borrar los datos del sitio en el navegador también elimina la elección, y el portal vuelve a preguntar.

> **Nota para el abogado (NA-18):** Google Analytics 4 está en producción en el portal de reservas con consentimiento previo. Revisar:
> - el rol de Shifty y de las Tiendas frente a esta medición, que responde a un fin de Shifty y no a una instrucción de la Tienda (comparar con la sección 1 y con NA-1), y el de Google (encargado o responsable propio, según sus condiciones de tratamiento de datos);
> - si el aviso actual del portal alcanza como consentimiento informado y si la IP, las cookies y los datos del dispositivo deben tratarse como datos personales a estos efectos;
> - el mecanismo de la transferencia internacional a Google (NA-5);
> - el plazo de conservación configurado en la propiedad (sección 7) y cómo se atienden los derechos del titular sobre los datos que ya recibió Google.

## 10. Datos sensibles y menores

10.1. Shifty no está pensado para tratar datos sensibles. Las Tiendas tienen prohibido pedir datos de salud en sus preguntas y notas, salvo los profesionales y establecimientos de salud comprendidos en el art. 8 de la Ley 25.326, que lo hacen bajo su responsabilidad y con secreto profesional. En ese caso, el portal muestra un aviso específico y pide un consentimiento separado antes de responder. **Nadie está obligado a dar datos sensibles** (Ley 25.326, art. 7).

> **Nota para el abogado (NA-6):** depende de la decisión sobre el rubro "Salud" (L1 P-6). Mientras no se implemente el aviso con consentimiento separado (checklist BE-12, FE-12), la frase sobre ese aviso no se publica.

10.2. [[COMPLETAR: política sobre menores, en línea con las Condiciones del portal, cláusula 6]].

> **Nota para el abogado (NA-7):** ver las Condiciones del portal, cláusula 6.

## 11. Seguridad

Shifty aplica medidas técnicas y organizativas para proteger los datos (Ley 25.326, art. 9):

- cada Tienda accede solo a sus datos, con aislamiento aplicado en la propia base de datos;
- las contraseñas se guardan como hash, y las credenciales de Mercado Pago de las Tiendas, cifradas;
- las conexiones con el sitio están cifradas;
- los accesos al panel se registran por sesión y los cambios quedan en un registro de auditoría;
- se hacen copias de seguridad diarias.

> **Dependencia de producto:** la copia diaria existe en el repositorio, pero no corre en el servidor hasta que se haga la preparación de `docs/DEPLOY_RUNBOOK.md` §1 (checklist DU-09). Hasta entonces, esa línea no se publica.

Ningún sistema es infalible. Si se produce un incidente que afecte datos de Clientes, Shifty avisa a las Tiendas afectadas según el Acuerdo de Tratamiento.

## 12. Cambios en esta política

Cada versión se publica con su fecha, y las anteriores quedan accesibles en el historial. Si un cambio agrega una finalidad o un destinatario:

- se avisa a las Tiendas antes de que rija;
- se aplica a los Clientes desde su siguiente reserva.

## 13. Contacto

Datos personales: [[COMPLETAR: email de privacidad de Shifty]]. Otras consultas: [[COMPLETAR: email de contacto de Shifty]]. Domicilio: [[COMPLETAR: domicilio legal de Shifty]].

## Estado de pre-revisión interna (2026-10-11)

Se corrigieron contradicciones del borrador sobre la existencia de analítica y
cookies de GA4. El 11 de octubre, Production mostró el aviso en `/b/ejemplo`;
antes de aceptar no se observaron solicitudes a Google. Tras la aceptación
autorizada, una petición explícita `booking_started` recibió HTTP 204; por
separado, el evento apareció una vez en Tiempo real. GA4 registró además `first_visit` y
`session_start` automáticos. El flujo de Production coincide con el dominio y
el ID de medición del bundle, cuyo valor se omite.

La evidencia de esta corrida y de los ajustes de la propiedad no se adjunta al
repositorio como HAR, captura o export. Este registro interno resume la
observación de la sesión controlada autorizada y no sustituye el archivo de
evidencia que debe validar el responsable.

En la propiedad: Medición mejorada, Google Signals y recopilación de datos
proporcionados por usuarios desactivados; recopilación granular de
ubicación/dispositivo activada; personalización publicitaria permitida en
307/307 regiones, sin vínculo con Google Ads ni etiquetas de sitio conectadas;
retención de eventos de 2 meses y de datos de usuario de 14 meses, con borrado
ante nueva actividad activado. La fuente exacta de la variable de Vercel y las
demás vinculaciones no se confirmaron. La página de privacidad que sirve
Production aún es la versión resumida anterior; los cambios locales no están
desplegados. Este trabajo es una revisión técnica de consistencia, no una
revisión ni aprobación legal profesional. Siguen pendientes la identidad y
contacto del responsable, roles y base jurídica de GA4, entidad y región de
tratamiento, mecanismos de transferencia, dependencias de producto y
aprobación de un abogado matriculado antes de publicar. La interfaz de GA4
también muestra pendiente una declaración del administrador sobre la entrega
de avisos y la obtención de consentimiento; no se aceptó porque requiere una
confirmación factual del responsable.

### Fuentes oficiales para la revisión legal

- [Ley 25.326, texto actualizado](https://www.argentina.gob.ar/normativa/nacional/64790/actualizacion).
- [Decreto reglamentario 1558/2001](https://www.argentina.gob.ar/normativa/nacional/decreto-1558-2001-70368/texto).
- [AAIP: responsables de bases de datos personales](https://www.argentina.gob.ar/aaip/datospersonales/responsables).
- [AAIP: transferencias internacionales](https://www.argentina.gob.ar/transferencias-internacionales) y [Resolución AAIP 198/2023](https://www.argentina.gob.ar/normativa/nacional/resoluci%C3%B3n-198-2023-391538/texto).
- [Google Analytics: configuración de Medición mejorada](https://support.google.com/analytics/answer/9216061).
