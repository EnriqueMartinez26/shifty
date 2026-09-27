> **BORRADOR: requiere revisión de un abogado matriculado antes de publicarse. No constituye asesoramiento legal.**

# Documentos legales de Shifty

Borradores de los textos legales de Shifty para Argentina. Salen de tres auditorías del 2026-09-25 y de una anterior:

- **L1**: cumplimiento legal, con normas verificadas en fuentes primarias.
- **L2**: accesibilidad y uso en mobile y desktop.
- **L3**: datos, cookies y terceros.
- **PV**: `auditoria-privacidad.md`, la auditoría de privacidad del 2026-09-24.

Solo se citan normas que L1 marca como verificadas. Lo que L1 marca como "NO VERIFICADO" no está en los textos: figura en una **Nota para el abogado (NA-x)**.

## Qué es cada documento

| Documento | Para qué sirve | Quién lo acepta | Dónde y cuándo se muestra |
|---|---|---|---|
| [TERMINOS_TIENDAS.md](TERMINOS_TIENDAS.md) | El contrato entre Shifty y cada tienda: servicio, abono, suspensión, uso aceptable, Mercado Pago, responsabilidad y baja. | El administrador de la tienda, en nombre de la tienda. | Primer inicio de sesión del admin: una pantalla bloqueante con casilla. Se vuelve a pedir en cada versión con cambios materiales. Se publica en `/legal/terminos-tiendas` (L. 24.240 art. 38). |
| [ACUERDO_DE_TRATAMIENTO.md](ACUERDO_DE_TRATAMIENTO.md) | El encargo de tratamiento (L. 25.326 art. 25): Shifty trata los datos de los clientes de la tienda por cuenta de ella. | El administrador de la tienda, junto con los Términos para tiendas. | La misma pantalla y la misma casilla que los Términos para tiendas. Se publica en `/legal/acuerdo-tratamiento`. |
| [TERMINOS_CLIENTES.md](TERMINOS_CLIENTES.md) | Las condiciones de uso del portal de reservas: quién presta el servicio, seña, cancelación, revocación, menores y usos prohibidos. | La persona que reserva. | Enlace en el pie del portal y en la casilla del paso de confirmación, antes de reservar. Se publica en `/legal/condiciones`. |
| [POLITICA_DE_PRIVACIDAD.md](POLITICA_DE_PRIVACIDAD.md) | El deber de información del art. 6 de la L. 25.326: quién responde, qué datos, para qué, destinatarios, plazos, derechos, cookies y leyenda AAIP. | No se acepta, se informa. La casilla de la reserva deja constancia de que se leyó. | Pie de todas las páginas públicas y del panel, aviso breve antes del OTP y de la lista de espera, y pie de los mails. Se publica en `/legal/privacidad`. |
| [CANCELACIONES_Y_REEMBOLSOS.md](CANCELACIONES_Y_REEMBOLSOS.md) | Aclara que cada tienda fija su propia política, que Shifty no cobra ni guarda el dinero, y cómo se tramitan los reclamos. | No se acepta, se informa. | Junto a la política de la tienda, antes del botón de pago. Se publica en `/legal/cancelaciones`. |
| [AVISOS_Y_CONSENTIMIENTOS.md](AVISOS_Y_CONSENTIMIENTOS.md) | Los textos exactos que van en pantalla y en los mails, y en qué momento aparece cada uno. | Es una guía para el front y el backend. No se publica. | — |
| [CHECKLIST_LANZAMIENTO.md](CHECKLIST_LANZAMIENTO.md) | Todo lo que falta antes de publicar, con responsable, severidad, fuente y estado. | Es una guía interna. No se publica. | — |

## Versiones

- Cada documento publicable lleva en su encabezado una **versión, que es su fecha de entrada en vigencia** en formato `AAAA-MM-DD` (por ejemplo, `2026-10-15`). Mientras no se fije, figura como `[[COMPLETAR: fecha de vigencia]]`.
- Qué versión se guarda en cada aceptación. Los mecanismos ya están **mergeados en el backend** de `integration/aud2` (`4cc2300`); falta que el front los use:
  - **Reserva:** el turno guarda `terms_version`, la versión de las Condiciones del portal, y `privacy_version`, la versión de la Política de privacidad que se mostró, junto con la fecha de aceptación (`terms_accepted_at`). El portal lee las versiones vigentes de `GET /public/legal/versions` y las manda con la reserva. Una versión que no es la vigente se rechaza con 409 `LEGAL_VERSION_MISMATCH`, y mandar una sola de las dos, con 422. Mientras el front no las mande, el turno se crea con la fecha de aceptación y sin versión (checklist BE-01, FE-04). La lista de espera guarda lo mismo, pero lo exige solo con `LEGAL_WAITLIST_CONSENT_REQUIRED=true` (checklist BE-14, FE-06).
  - **Tiendas:** `POST /stores/me/terms-acceptance`, que solo puede usar el administrador de la tienda, guarda en `store_terms_acceptances` la versión (`STORE_TERMS_VERSION`), la fecha y hora, el usuario y un HMAC de la IP; la IP en claro no se guarda. `GET /stores/me/terms-acceptance` dice si la versión vigente está aceptada. El backend no bloquea el panel: la pantalla bloqueante es del front (checklist BE-02, FE-05).
  - **Una sola versión para los Términos para tiendas y el Acuerdo de tratamiento.** El backend guarda una única versión B2B y no tiene una propia para el Acuerdo. El Acuerdo queda cubierto porque forma parte de los Términos y se acepta junto con ellos: los dos documentos se publican siempre con la misma fecha de versión, y un cambio en cualquiera de los dos sube `STORE_TERMS_VERSION`.
- Las versiones vigentes se configuran en el backend: `LEGAL_TERMS_VERSION` (Condiciones del portal), `LEGAL_PRIVACY_VERSION` (Política de privacidad) y `STORE_TERMS_VERSION` (Términos para tiendas y Acuerdo), en `backend/core/config.py`. Hoy valen `2026-09-25` por defecto. **Al publicar, cada una tiene que coincidir con la fecha de versión del documento publicado.**
- **Cambio material** es el que amplía obligaciones, reduce derechos o agrega una finalidad o un destinatario de datos. En ese caso:
  - se publica una versión nueva con otra fecha;
  - a las tiendas se les vuelve a pedir la aceptación, con el preaviso de la cláusula de cambios de los Términos para tiendas;
  - a los clientes, la versión nueva se les aplica desde la siguiente reserva.
- **Cambio de redacción:** una corrección que no cambia el alcance se publica con otra fecha y no pide nueva aceptación.
- **Historial:** todas las versiones publicadas quedan accesibles, con su fecha, en `/legal/<documento>/historial`, y versionadas en este directorio. Hace falta para probar qué texto rigió en cada reserva (CCyC art. 985; Res. SCI 270/2020, Anexo art. 3).

## Marcadores

Los datos que todavía no se conocen figuran como `[[COMPLETAR: ...]]`. Antes de publicar, **no puede quedar ninguno**. Para listarlos:

```
rg -n "\[\[COMPLETAR" docs/legal
```

## Qué debe estar hecho antes de publicar cada afirmación

Algunos textos describen mecanismos que el producto todavía no tiene. **No se publican hasta que el mecanismo esté en producción**, porque si no el texto promete algo que no existe (L1 §6). Cada fila remite a su ítem del checklist. "Backend hecho" significa mergeado en `integration/aud2` (`4cc2300`), no desplegado: **todas las filas dependen además de que esa versión llegue a producción.**

| Afirmación en los documentos | Depende de | Estado al `4cc2300` | Checklist |
|---|---|---|---|
| Se guarda qué versión de términos y privacidad se aceptó | Versionado del consentimiento | **Backend hecho.** Falta que el portal mande las versiones. | BE-01, FE-04 |
| La tienda acepta los Términos y el Acuerdo en el panel | Registro de la aceptación B2B y pantalla bloqueante | **Backend hecho** (registro). Falta la pantalla bloqueante del front. | BE-02, FE-05 |
| El cliente puede pedir la exportación o la anonimización de sus datos | Exportación y anonimización por cliente | **Backend hecho**, por el id del cliente y solo para administradores; procedimiento en `docs/DERECHOS_DE_LOS_TITULARES.md`. Falta la pantalla del panel. | BE-03, FE-23 |
| El mail de "volvé a reservar" tiene baja con un clic | Baja por cliente y tienda | **Backend en parte:** enlace firmado y envío que saltea las bajas. Faltan la página de confirmación del front, que el enlace apunte a ella y los encabezados `List-Unsubscribe`. | BE-04, FE-17 |
| Shifty no guarda los datos de la tarjeta ni la identificación del pagador | Lista blanca en `payments.raw_payload` (L3-01) | **Backend hecho**, con recorte de las filas existentes. | BE-05 |
| Una tienda no ve los clientes de otra; el email es único por tienda | PV-01 | **Backend hecho** (merge `9fc2903`). | BE-06 |
| Los mails salen en nombre de la tienda, con respuesta a la tienda | Pie, `From` y `Reply-To` (L3-05) | **Backend en parte:** el pie ya dice en nombre de qué tienda se escribe, por qué llega y enlaza la privacidad. Faltan el remitente y la respuesta a la tienda (necesitan el correo de la tienda, BE-08), la identidad de la tienda y la leyenda AAIP en el pie. | BE-07, BE-08 |
| El portal muestra la identidad legal de la tienda | Campos de identidad en `Store` y su vista en el portal (L1 O-14) | Pendiente. | BE-08, FE-07 |
| Se guarda la política de seña vigente al reservar | Copia o hash con historial de `deposit_policy` (L1 O-4) | Pendiente. | BE-09 |
| Los datos se devuelven y se borran al terminar el contrato | Procedimiento de baja de tienda (L1 O-10) | Pendiente. | BE-10 |
| El correo y el teléfono completo del Cliente solo los ven los administradores | Datos de contacto restringidos al personal (L3-03) | **Backend en parte:** las cuentas pendientes ya cumplen. Falta la búsqueda y la agenda de turnos. | BE-13, BE-29 |
| Se hacen copias de seguridad diarias | Backup activo en el VPS (`docs/DEPLOY_RUNBOOK.md` §1) | Pendiente (producción). | DU-09 |
| Aviso y consentimiento separado para datos de salud | Decisión sobre el rubro "Salud" y su implementación (L1 O-5) | Decisión pendiente. | DU-05, BE-12, FE-12 |
| Proveedores con país y mecanismo de transferencia | Elección de proveedores y regiones, y contratos (L1 O-11) | Decisión pendiente. | DU-03, DU-04 |

## Notas para el abogado

Cada documento marca en el lugar exacto los puntos que necesitan dictamen, como **NA-x**. El índice:

| NA | Tema | Documento |
|---|---|---|
| NA-1 | Rol de Shifty (encargado o responsable) con el diseño actual | ACUERDO, PRIVACIDAD |
| NA-2 | Validez de la limitación de responsabilidad y de la indemnidad en un contrato de adhesión (CCyC 988) | TERMINOS_TIENDAS |
| NA-3 | ¿La tienda monotributista unipersonal puede ser consumidora del abono? Botón de baja | TERMINOS_TIENDAS |
| NA-4 | Revocación de 10 días frente a una seña de un servicio con fecha; botón de arrepentimiento; OTP como "trámite adicional" | TERMINOS_CLIENTES, CANCELACIONES, AVISOS |
| NA-5 | Transferencias a Brasil y EE. UU.: mecanismo elegido y notificación a la AAIP | PRIVACIDAD, ACUERDO |
| NA-6 | Datos de salud: rubro "Salud", art. 8 y Ley 26.529 | TERMINOS_TIENDAS, PRIVACIDAD |
| NA-7 | Menores: edad mínima y consentimiento | TERMINOS_CLIENTES, PRIVACIDAD |
| NA-8 | Mail promocional "volvé a reservar": ¿alcanza la baja o hace falta consentimiento previo? | PRIVACIDAD, AVISOS |
| NA-9 | Inscripción en el Registro Nacional de Bases de Datos: qué bases, de quién | PRIVACIDAD, ACUERDO |
| NA-10 | Aviso de incidentes: sin obligación legal verificada; plazo contractual | ACUERDO |
| NA-11 | ¿Shifty integra la cadena del art. 40 de la L. 24.240 frente al cliente? | TERMINOS_CLIENTES |
| NA-12 | "PRECIO SIN IMPUESTOS NACIONALES" y Data Fiscal: quién lo muestra según la condición fiscal | AVISOS |
| NA-13 | Mercado Pago: ¿responsable propio o subencargado? Obligaciones como integrador | PRIVACIDAD, ACUERDO |
| NA-14 | Conservación hasta 2 años al terminar (art. 25.2) y plazos de retención | ACUERDO, PRIVACIDAD |
| NA-15 | Recargo de seña según el historial de asistencia: información y trato equitativo | PRIVACIDAD, TERMINOS_CLIENTES |
| NA-16 | Normas provinciales (Córdoba, Ley 10.247) y mención de la autoridad de consumo | TERMINOS_CLIENTES |
| NA-17 | Casilla de la política de la tienda: ¿"leí" o "leí y acepto"? | AVISOS |

## Criterios de redacción

- Español neutro y profesional. Los documentos van en tercera persona. Los textos de pantalla usan construcciones impersonales: el front puede pasarlos al voseo del resto de la interfaz sin cambiar el contenido.
- Nada de promesas que el producto no sostiene (L1 §6). No se usan "datos cifrados" en general, "garantizado", "100 %", "obligados contractualmente" (mientras no haya contratos) ni "Shifty no recibe datos de pago" (mientras siga abierto L3-01).
- Shifty es una plataforma tecnológica: no presta el servicio reservado, no cobra la seña ni guarda el dinero, no fija la política de cancelación ni resuelve reembolsos. La política es de cada tienda y las disputas de pago se tramitan ante Mercado Pago. Es una decisión de Mateo y Enrique y los textos la informan sin que Shifty asuma esas obligaciones.
