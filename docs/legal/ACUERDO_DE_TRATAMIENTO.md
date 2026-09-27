> **BORRADOR: requiere revisión de un abogado matriculado antes de publicarse. No constituye asesoramiento legal.**

# Acuerdo de Tratamiento de Datos Personales

**Versión:** [[COMPLETAR: fecha de vigencia, AAAA-MM-DD]]
**Historial de versiones:** `/legal/acuerdo-tratamiento/historial`

Este acuerdo forma parte de los **Términos y Condiciones para Tiendas** y se acepta junto con ellos. Regula el tratamiento que hace Shifty de los datos personales de los clientes y del personal de la Tienda, por cuenta de ella, según el art. 25 de la Ley 25.326 y el art. 25 del Decreto 1558/2001.

- **Responsable del tratamiento:** la Tienda.
- **Encargado del tratamiento:** [[COMPLETAR: razón social o nombre del titular de Shifty]], CUIT [[COMPLETAR: CUIT de Shifty]], domicilio en [[COMPLETAR: domicilio legal de Shifty]] (**Shifty**).

## 1. Objeto, duración y datos

1.1. **Objeto:** prestar el servicio de gestión de turnos descripto en los Términos para Tiendas.

1.2. **Duración:** la del contrato con la Tienda, más el plazo de devolución y borrado de la cláusula 9.

1.3. **Titulares:**

- los clientes de la Tienda (personas que reservan, se anotan en la lista de espera o pagan una seña);
- el personal de la Tienda, en cuanto a los datos de agenda y de publicación en el portal.

1.4. **Datos:**

- nombre, teléfono y correo electrónico;
- turnos: servicio, profesional, fecha, estado y seña;
- notas y respuestas a las preguntas de la Tienda;
- lista de espera;
- cuentas pendientes;
- estado de los pagos;
- registros técnicos.

**Datos sensibles:** solo si la Tienda está comprendida en el art. 8 de la Ley 25.326 y los carga bajo su responsabilidad, según la cláusula 6.2 de los Términos para Tiendas.

1.5. **Los datos de la cuenta de acceso de los usuarios del panel no forman parte de este encargo.** De ellos, Shifty es responsable (Política de privacidad, sección 4).

## 2. Instrucciones

2.1. Shifty trata los datos **solo para prestar el servicio y según las instrucciones documentadas de la Tienda**. La Tienda da esas instrucciones al aceptar este acuerdo y a través de la configuración de su panel. Son instrucciones expresas:

1. Publicar la agenda y recibir reservas y anotaciones en la lista de espera.
2. Validar el teléfono del cliente con un código enviado por correo, cuando la Tienda lo exige.
3. Enviar por correo, en nombre de la Tienda, los avisos que ella activa: registro, confirmación, recordatorios de 24 y 2 horas, reprogramación, cancelación y ofertas de la lista de espera.
4. **Enviar la invitación a volver a reservar, solo si la Tienda activa ese envío**, respetando las bajas de cada cliente.
5. Crear los links de pago de las señas en la cuenta de Mercado Pago de la Tienda y registrar su estado.
6. Calcular la seña según las reglas que configure la Tienda, incluido el recargo por historial de asistencia en esa Tienda.
7. Guardar copias de seguridad y registros técnicos para la seguridad y la continuidad del servicio.

2.2. Shifty **no usa los datos para fines propios**, no los cede, no los cruza con los de otras tiendas y no contacta a los clientes por su cuenta (Ley 25.326, art. 25, inc. 1).

2.3. Si Shifty entiende que una instrucción infringe la ley, se lo informa a la Tienda y puede suspender su ejecución hasta que se aclare.

> **Nota para el abogado (NA-1):** el email del cliente ya no es único en toda la plataforma: en la rama de integración es único por tienda, y el del personal y los administradores sigue siendo único global (PV-01, migración `4b6d8f0a2c13`, decisión de Mateo; checklist BE-06). Eso resuelve el choque con 2.2. Los correos ya no se firman "El equipo de Shifty": cada correo al cliente dice que se envía en nombre de la Tienda a través de Shifty. Pero siguen saliendo desde la dirección de Shifty y sin respuesta a la Tienda, y eso contradice el punto 3 de 2.1 hasta que se corrija (checklist BE-07, que depende de BE-08).

## 3. Confidencialidad

3.1. Shifty guarda secreto sobre los datos (Ley 25.326, art. 10), y lo exige por escrito a toda persona que trabaje para él con acceso a ellos. El deber subsiste después de terminado el contrato.

3.2. El acceso del personal de Shifty a los datos de una Tienda desde la consola de administración se limita a soporte, alta, seguridad y cumplimiento de este acuerdo. **Cada acceso se registra** (checklist BE-11).

## 4. Seguridad

Shifty aplica medidas técnicas y organizativas, tomando como referencia las medidas recomendadas por la Res. AAIP 47/2018 (Ley 25.326, art. 9; Decreto 1558/2001, art. 25). Hoy son estas:

| Área | Medida |
|---|---|
| Aislamiento | Cada tienda accede solo a sus datos. El aislamiento se aplica en la base de datos con políticas por fila, con un rol de aplicación que no puede saltarlas, y además en cada consulta. |
| Acceso | Contraseñas guardadas como hash (bcrypt). Sesiones revocables. Bloqueo por intentos fallidos. Límite de pedidos. Roles con permisos distintos: el correo y el teléfono completo del cliente solo los ven los administradores (checklist BE-13, BE-29). |
| Credenciales | Las credenciales de Mercado Pago de la Tienda se guardan cifradas. La configuración de producción no arranca con claves de ejemplo. |
| Tránsito | HTTPS con TLS 1.2 o 1.3 y HSTS. Envío de correo con verificación del certificado del servidor. |
| Registro | Auditoría de cambios. Los informes de errores se depuran de datos personales antes de salir al proveedor de monitoreo. |
| Continuidad | Copias de seguridad diarias con rotación de 28 días (checklist DU-09). [[COMPLETAR: cifrado de las copias, cuando se implemente (PV-07, checklist DU-10)]]. |

Las medidas pueden cambiar por otras de nivel equivalente o superior.

## 5. Subencargados

5.1. La Tienda **autoriza en forma general** a Shifty a usar los siguientes subencargados:

| Subencargado | Servicio | País o región |
|---|---|---|
| Hostinger | Servidor donde se aloja el servicio | Brasil |
| [[COMPLETAR: proveedor SMTP]] | Envío de correos | [[COMPLETAR: país/región del proveedor SMTP]] |
| Sentry ([[COMPLETAR: razón social del proveedor según su contrato]]) | Monitoreo de errores, con datos depurados | [[COMPLETAR: región del proyecto de Sentry (EE. UU. o UE)]] |
| [[COMPLETAR: proveedor de backups]] | Almacenamiento de copias de seguridad | [[COMPLETAR: región del proveedor de backups]] |

5.2. Mercado Pago **no es subencargado de Shifty**. La Tienda contrata con él directamente y le envía los datos del pagador para cobrar su seña.

5.3. Shifty le exige a cada subencargado, por contrato, obligaciones de confidencialidad y seguridad no menores que las de este acuerdo.

5.4. Antes de agregar o reemplazar un subencargado, Shifty avisa a la Tienda con [[COMPLETAR: plazo, sugerido: 30 días]] de anticipación. Si la Tienda tiene un motivo razonable vinculado a la protección de datos, puede oponerse. Si no se llega a una solución, puede terminar el contrato sin costo.

> **Nota para el abogado (NA-13):** confirmar que Mercado Pago es un responsable propio y no un subencargado (L1 P-10).

## 6. Transferencias internacionales

Los subencargados ubicados en países sin protección adecuada según la AAIP (entre ellos Brasil y Estados Unidos) reciben los datos bajo [[COMPLETAR: mecanismo por proveedor: cláusulas contractuales modelo de la AAIP / contrato propio notificado a la AAIP / región adecuada]] (Ley 25.326, art. 12; Decreto 1558/2001, art. 12). Al aceptar este acuerdo, la Tienda, como exportadora, instruye esas transferencias.

> **Nota para el abogado (NA-5):** ver la Política de privacidad, sección 6. Si se usan las cláusulas modelo responsable→encargado, pueden incorporarse como anexo de este acuerdo.

## 7. Asistencia con los derechos de los titulares

7.1. Si un titular le pide a Shifty acceso, rectificación, supresión o baja de comunicaciones sobre datos de la Tienda, Shifty **le reenvía el pedido a la Tienda dentro de las 48 horas** y no lo responde por su cuenta, salvo que la Tienda se lo indique.

7.2. Para que la Tienda cumpla los plazos legales (10 días corridos para el acceso y 5 días hábiles para la rectificación y la supresión, Ley 25.326, arts. 14 y 16), Shifty pone a su disposición:

- la **exportación** de los datos de un cliente en un archivo;
- la **anonimización** de un cliente: se reemplazan su nombre, teléfono, correo, notas y respuestas a las preguntas de la Tienda, y se conservan los importes, las fechas y los estados. No se anonimiza a un cliente con un cobro abierto, turnos activos a futuro o saldo en las cuentas pendientes: primero se cierra eso (checklist BE-03);
- la edición de nombre y teléfono desde el panel;
- la baja por cliente del correo de invitación a volver a reservar (checklist BE-04).

> **Dependencia de producto:** el procedimiento operativo está en `docs/DERECHOS_DE_LOS_TITULARES.md`. La exportación y la anonimización existen en el backend, por el identificador del cliente, y solo para administradores; falta la pantalla del panel (checklist FE-23). La baja existe en el backend; faltan la página de confirmación y los encabezados `List-Unsubscribe` (checklist BE-04, FE-17).

## 8. Incidentes de seguridad

8.1. Si Shifty detecta un incidente que compromete la confidencialidad, integridad o disponibilidad de datos de la Tienda, **se lo avisa dentro de las [[COMPLETAR: plazo, sugerido: 72 horas]]** de haberlo confirmado. El aviso incluye lo que se sepa hasta ese momento:

- la naturaleza del incidente;
- los datos y los titulares afectados, en forma aproximada;
- las consecuencias probables;
- las medidas que se tomaron y las que se proponen.

8.2. Shifty documenta cada incidente y colabora con la Tienda en las comunicaciones que ella decida hacer a los titulares o a la autoridad.

> **Nota para el abogado (NA-10):** L1 no encontró una obligación legal vigente de notificar incidentes a la AAIP ni a los titulares (Res. AAIP 47/2018: medidas recomendadas). La exigibilidad de la Ley 27.699 (Convenio 108+) está NO VERIFICADA. El aviso a la Tienda se asume como obligación contractual.

## 9. Fin del encargo: devolución y borrado

9.1. Al terminar el contrato, la Tienda tiene [[COMPLETAR: plazo, sugerido: 30 días]] para descargar o pedir la exportación de sus datos.

9.2. Vencido ese plazo, Shifty **destruye o anonimiza** los datos de la Tienda (Ley 25.326, art. 25, inc. 2). Las copias de seguridad se borran por rotación dentro de los 28 días siguientes.

9.3. **Conservación:** si la Tienda lo autoriza expresamente al dar la baja, Shifty puede conservar los datos **hasta dos años**, bloqueados y sin otro uso, para una eventual reactivación. Pasado ese plazo, los destruye.

9.4. A pedido de la Tienda, Shifty le entrega una constancia del borrado.

> **Nota para el abogado (NA-14):** hoy el sistema no puede cumplir 9.1 a 9.3: no hay exportación completa ni borrado de tienda (L1 O-10, checklist BE-10). Además, el registro de auditoría hoy no tiene plazo de conservación: definirlo (L1 P-5).

## 10. Información y control

Shifty entrega a la Tienda, a su pedido y como mucho una vez por año, la información razonable para acreditar el cumplimiento de este acuerdo: medidas de seguridad vigentes, lista de subencargados e incidentes registrados. Si una autoridad le pide información sobre el tratamiento, Shifty colabora con la Tienda.

## 11. Responsabilidad

Cada parte responde por el tratamiento que le corresponde según la ley y este acuerdo. Si Shifty trata los datos para una finalidad distinta de la instruida, o los cede, responde como responsable de ese tratamiento.

## 12. Registro Nacional de Bases de Datos

Shifty inscribe sus propias bases en el Registro Nacional de Bases de Datos (inscripción n.° [[COMPLETAR: número de inscripción AAIP]]). La inscripción de la base de clientes de la Tienda es obligación de la Tienda, si le corresponde.

> **Nota para el abogado (NA-9):** L1 P-3.
