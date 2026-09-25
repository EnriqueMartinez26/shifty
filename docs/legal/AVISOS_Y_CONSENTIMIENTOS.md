> **BORRADOR: requiere revisión de un abogado matriculado antes de publicarse. No constituye asesoramiento legal.**

# Avisos y consentimientos: textos en pantalla y en los correos

Guía para el front (Enrique) y el backend. Cada bloque dice **cuándo** aparece, **dónde** va en el código y el **texto exacto**. Las variables van entre llaves: `{tienda}`, `{razon_social}`, `{cuit}`, `{domicilio}`, `{email_reclamos}`.

Los textos usan construcciones impersonales. Se pueden pasar al voseo del resto de la interfaz sin cambiar el contenido. Los enlaces abren en la misma pestaña, o avisan "(se abre en una pestaña nueva)" (L2, 3.1.2).

## 0. Bloques comunes

**Leyenda AAIP** (Res. AAIP 14/2018, art. 3, texto literal verificado). Va en la Política de privacidad, al pie de los formularios de reserva, lista de espera y validación, y en el pie de todos los correos:

> LA AGENCIA DE ACCESO A LA INFORMACIÓN PÚBLICA, en su carácter de Órgano de Control de la Ley N° 25.326, tiene la atribución de atender las denuncias y reclamos que interpongan quienes resulten afectados en sus derechos por incumplimiento de las normas vigentes en materia de protección de datos personales.

**Identidad de la Tienda** (`{identidad_tienda}`):

> {razon_social} · CUIT {cuit} · {domicilio} · Reclamos: {email_reclamos}

**Identidad de Shifty** (`{identidad_shifty}`):

> Shifty es un servicio de [[COMPLETAR: razón social o nombre del titular de Shifty]] · CUIT [[COMPLETAR: CUIT de Shifty]] · [[COMPLETAR: domicilio legal de Shifty]] · [[COMPLETAR: email de contacto de Shifty]]

## 1. Pie de página

| Dónde | Cuándo | Texto |
|---|---|---|
| Portal de la Tienda: `PublicBooking.tsx:231`, `ClientAppointments.tsx:52` (hoy con `LegalFooterLinks`) | Siempre, en todas las pantallas del portal | Primera línea: `{identidad_tienda}` y el logo Data Fiscal de la Tienda (ver 12). Segunda línea: "Reservas con Shifty. [Condiciones de uso] · [Privacidad] · [Cancelaciones y reembolsos]". Reemplaza "POWERED BY SHIFTY" (`PublicBooking.tsx:233`). |
| Panel: `AdminLayout.tsx:144` | Siempre | "[Términos para tiendas] · [Acuerdo de tratamiento] · [Privacidad] · {identidad_shifty}" |
| Login, recuperar y restablecer contraseña: `Login.tsx:175`, `ForgotPassword.tsx`, `ResetPassword.tsx` | Siempre | "{identidad_shifty} · [Privacidad] · [Términos para tiendas]", más el logo Data Fiscal de Shifty (ver 12). Reemplaza "Copyright 2026 Shifty SaaS". |
| Páginas legales `/legal/*` | Siempre | `{identidad_shifty}` y los enlaces a los demás documentos |

Los enlaces del pie tienen que medir como mínimo 44 px de alto, con `py-3` (L2, 2.5.5).

## 2. Aviso breve antes de pedir el código (validación por OTP)

**Cuándo:** en el formulario de datos del cliente, **antes** del botón "Enviar código" y antes de que se envíe cualquier dato. Va en `BookingStepConfirmation.tsx:407-446` y en `ClientOtpGate.tsx:100-146` ("Mis turnos"). Si la Tienda no exige código, va arriba del botón de reservar (sección 4). **Tipo:** aviso visible, sin casilla (Ley 25.326, art. 6; Res. AAIP 14/2018, art. 2).

> **Datos personales.** Los datos de este formulario los usa **{tienda}** ({razon_social}, CUIT {cuit}, {domicilio}), responsable de la base de datos, para gestionar el turno y enviar los avisos por correo. Shifty los procesa por cuenta de {tienda} como proveedor tecnológico.
> El nombre y el teléfono son obligatorios para reservar. El correo es necesario para recibir el código de validación y los avisos del turno. Las notas son opcionales.
> El acceso, la rectificación y la supresión de los datos se piden a {tienda} ({email_reclamos}). [Política de privacidad]
> {leyenda AAIP, en texto de 12 px como mínimo}

## 3. Resumen antes de pagar o confirmar

**Cuándo:** en el paso de confirmación, junto al resumen del turno e **inmediatamente antes** del botón de pago o de reserva (`BookingStepConfirmation.tsx:882-947`). **Tipo:** texto visible. El aviso de revocación va en caracteres destacados (CCyC, art. 1111).

```
{tienda}
{identidad_tienda}

Servicio: {servicio}
Profesional: {profesional}
Fecha y hora: {día de la semana} {d} de {mes}, {HH:mm} (hora de Argentina)

Precio final: $ {precio_final}
PRECIO SIN IMPUESTOS NACIONALES: $ {precio_sin_impuestos}      ← solo si la Tienda lo configuró (ver 11)
Seña a pagar ahora: $ {seña}
{Si la Tienda lo indica: "La seña es a cuenta del precio final."}
{Si hay recargo por historial: "La seña puede variar según el historial de asistencia en {tienda}."}

Política de seña y cancelación de {tienda}:
{texto de deposit_policy}
```

Debajo, el texto fijo de Shifty:

> El servicio lo presta {tienda}. La seña se paga con Mercado Pago y se acredita en la cuenta de {tienda}: Shifty es el proveedor tecnológico y no recibe ni administra ese dinero. Los pedidos de devolución se hacen a {tienda} ({email_reclamos}), y las disputas sobre el pago se tramitan ante Mercado Pago. [Cancelaciones y reembolsos]

Y el aviso de revocación, destacado:

> **Derecho de revocación:** se puede revocar esta contratación dentro de los 10 días corridos, sin responsabilidad alguna (Ley 24.240, art. 34; Código Civil y Comercial, art. 1110). Se pide a {tienda} [[COMPLETAR: por el Botón de arrepentimiento / a {email_reclamos}]].

> **Nota para el abogado (NA-4):** la redacción definitiva del aviso de revocación y la existencia del botón dependen del dictamen L1 P-7 y de la decisión DU-06.

Si la Tienda no cargó una política de seña, en lugar del texto de la política se muestra: "{tienda} no publicó una política de seña y cancelación. Antes de pagar, se le puede consultar a {email_reclamos}." Hoy el portal no muestra nada en ese caso (L1 A-2).

## 4. Casillas de la reserva

**Cuándo:** en el mismo paso, debajo del resumen y antes del botón. Son **casillas separadas**. Ninguna viene marcada. Reemplazan a la casilla única actual (`BookingStepConfirmation.tsx:914-947`).

| # | Obligatoria | Texto | Qué se guarda |
|---|---|---|---|
| A | Sí | "Acepto las [Condiciones de uso del portal] y leí la [Política de privacidad]." | `terms_accepted_at`, `terms_version`, `privacy_version` (BE-01) |
| B | Sí, **solo si hay seña o la Tienda publicó una política** | "Leí la política de seña y cancelación de {tienda}." | Fecha y copia o hash de la `deposit_policy` vigente (BE-09) |
| C | No. **Solo si la Tienda activó la invitación a volver a reservar y se decide pedir consentimiento previo (NA-8)** | "Quiero que {tienda} me invite por correo a reservar de nuevo después de mi turno. (Opcional)" | Consentimiento con fecha, o su ausencia |
| D | Sí para responder. **Solo en Tiendas del rubro "Salud" con preguntas marcadas como sensibles (DU-05)** | "Entiendo que mis respuestas pueden incluir datos de salud y consiento que {tienda} los trate para atender este turno. Puedo no responder las preguntas opcionales." | Consentimiento separado con fecha (Ley 25.326, art. 7) |

El botón de reservar queda habilitado siempre. Si falta una casilla obligatoria, al enviar se muestra junto a ella "Falta aceptar las condiciones" o "Falta confirmar la lectura de la política de {tienda}", con `aria-invalid` y el foco puesto en esa casilla (L2, 3.3.1).

> **Nota para el abogado (NA-17):** el pedido fue "leí la política de cancelación". Como esa política rige el contrato entre la Tienda y el cliente, evaluar si hace falta "Leí y acepto", sabiendo que no puede desplazar la revocación.

## 5. Lista de espera

**Cuándo:** en el formulario "Avisame si se libera un turno", **antes** del botón de enviar (`WaitlistJoinForm.tsx:103-151`). **Tipo:** aviso y casilla obligatoria. El servidor también tiene que exigirla (PV-09).

> Los datos los usa **{tienda}** ({razon_social}, CUIT {cuit}), responsable de la base de datos, para avisar por correo si se libera un turno. Shifty los procesa por su cuenta. Sin correo no es posible recibir el aviso. Cada oferta dura 10 minutos. Se puede salir de la lista en cualquier momento desde "Mis turnos". Derechos de acceso, rectificación y supresión: {email_reclamos}. [Política de privacidad]
> {leyenda AAIP}

Casilla: "Acepto que {tienda} me avise por correo cuando se libere un turno, y leí la [Política de privacidad]."

## 6. Aviso para las cuentas del personal

**Cuándo:** en la pantalla de login, bajo el formulario (`Login.tsx`), y en el correo de alta de la cuenta. **Tipo:** aviso.

> Shifty ([[COMPLETAR: razón social o nombre del titular de Shifty]]) es responsable de los datos de la cuenta de acceso: nombre, correo, teléfono, contraseña guardada como hash y, por seguridad, la IP y el navegador de cada sesión. Se usan para dar acceso y proteger la cuenta. Consultas y derechos: [[COMPLETAR: email de privacidad de Shifty]]. [Política de privacidad]

Al cargar personal (`StaffFormModal.tsx`) se muestra además este aviso a la Tienda:

> El nombre de visualización del profesional se publica en el portal de la Tienda. Se recomienda informar a la persona que su nombre será visible para quienes reservan.

## 7. Aceptación de las Tiendas (B2B)

**Cuándo:** en el primer inicio de sesión de un administrador de la Tienda, y otra vez en cada versión con cambios materiales. Es una **pantalla bloqueante**: el panel no se usa hasta aceptar. Los demás roles ven "La tienda tiene que aceptar los términos actualizados. Un administrador debe ingresar para hacerlo." **Qué se guarda:** versión, fecha y hora, usuario y un HMAC de la IP, no la IP en claro (BE-02, FE-05). Es una sola versión para los Términos para tiendas y el Acuerdo de tratamiento (README, "Versiones").

```
Términos para usar Shifty

Antes de empezar, {nombre_admin} tiene que aceptar, en nombre de {tienda}:

• Términos y Condiciones para Tiendas — versión {fecha}   [Leer]
• Acuerdo de Tratamiento de Datos Personales — versión {fecha}   [Leer]

Resumen:
– Shifty es la herramienta: {tienda} presta el servicio, fija sus precios y su política
  de seña y cancelación, y cobra en su propia cuenta de Mercado Pago.
– {tienda} es responsable de los datos de sus clientes; Shifty los trata por su cuenta.
– No cargar datos de salud en notas ni preguntas, salvo profesionales de la salud (cláusula 6.2).
– Baja en cualquier momento; los datos se devuelven y se borran según el Acuerdo.

[ ] Leí y acepto los Términos y Condiciones para Tiendas y el Acuerdo de Tratamiento
    de Datos Personales, en nombre de {tienda}, y declaro tener facultades para hacerlo.

[Aceptar y continuar]        [Salir]
```

Si hay una versión nueva, se agrega arriba: "Cambios desde la versión {fecha_anterior}: {resumen}. Rigen desde {fecha}. Si no se aceptan, la Tienda puede dar de baja el servicio sin costo."

## 8. Avisos en el panel de la Tienda

| Dónde | Cuándo | Texto |
|---|---|---|
| Editor de preguntas personalizadas (`Settings.tsx`, `custom_client_fields`) | Siempre visible, arriba del editor | "No se deben pedir datos de salud (diagnósticos, medicación, alergias, embarazo) ni otros datos sensibles. Solo pueden hacerlo los profesionales y establecimientos de salud, bajo su responsabilidad (Términos, cláusula 6.2). Conviene pedir solo lo necesario para el turno." |
| Editor de la política de seña (`Settings.tsx`, `deposit_policy`) | Siempre visible | "Esta política se muestra antes del pago y se guarda con cada reserva. No puede excluir el derecho del consumidor a revocar la compra dentro de los 10 días (Ley 24.240, art. 34)." |
| Recargo de seña por historial | Al activarlo | "El portal va a informar que la seña puede variar según el historial de asistencia en la tienda." |
| Invitación a volver a reservar (`send_email_*`) | Al activarla | "Es un correo promocional: sale en nombre de la tienda, con un enlace de baja, y no llega a quien se dio de baja." |
| Notas del turno: placeholder de `BookingStepConfirmation.tsx:400` y `NewAppointmentModal.tsx:415` | Siempre | En la reserva: "¿Algo que el negocio deba saber? (No incluyas datos de salud)". En el panel: "Notas del turno (sin datos de salud)" |
| Identidad legal de la Tienda (campos nuevos, BE-08) | Mientras estén vacíos | "Faltan la razón social, el CUIT, el domicilio y el correo de reclamos: la ley exige mostrarlos a los clientes." |

## 9. Pie de los correos

Los correos a clientes salen con remitente visible "{tienda} vía Shifty" y responden a `{email_reclamos}` (`Reply-To`) (BE-07). Se reemplaza la firma "El equipo de Shifty" por "{tienda}".

**Correos del turno** (registro, confirmación, recordatorios, reprogramación, cancelación, oferta de la lista de espera):

```
—
Este correo se envía por una reserva en {tienda} (o por una inscripción en su lista de espera).
{identidad_tienda}
Enviado por Shifty por cuenta de {tienda}. Privacidad: {url}/legal/privacidad
{leyenda AAIP}
```

El correo de **registro de la reserva** agrega, antes del pie, la copia de lo aceptado (Res. SCI 270/2020, Anexo art. 3):

```
Condiciones aceptadas el {fecha y hora}: Condiciones de uso v{terms_version} ({url}),
Política de privacidad v{privacy_version} ({url}).
Política de seña y cancelación de {tienda} vigente al reservar:
{texto de deposit_policy}
Derecho de revocación: 10 días corridos (Ley 24.240, art. 34). Se pide a {tienda}: [[COMPLETAR: medio]].
```

La **oferta de la lista de espera** agrega: "Para salir de la lista: {url}/b/{slug}/mis-turnos".

**Correo de invitación a volver a reservar** (promocional; Ley 25.326, art. 27, inc. 3, y Decreto 1558/2001, art. 27). El aviso de baja va **destacado y antes del pie**:

```
Para dejar de recibir invitaciones de {tienda}: {link de baja firmado}
—
Este correo se envía por una reserva anterior en {tienda}.
{identidad_tienda}
Enviado por Shifty por cuenta de {tienda}. Privacidad: {url}/legal/privacidad
{leyenda AAIP}
```

Además lleva los encabezados `List-Unsubscribe` y `List-Unsubscribe-Post` (BE-04).

**Correo del código de validación:**

```
—
Este código se pidió para reservar en {tienda}. Si el pedido no fue propio, se puede ignorar este correo.
Enviado por Shifty por cuenta de {tienda}. Privacidad: {url}/legal/privacidad
{leyenda AAIP}
```

**Correos del personal** (restablecer y cambiar contraseña):

```
—
Shifty · {identidad_shifty}
Privacidad: {url}/legal/privacidad
{leyenda AAIP}
```

Reemplaza el "contactanos" sin contacto (`auth/service.py:244`).

**Asuntos** (L3-07): sin el nombre del servicio, porque puede revelar datos de salud. Por ejemplo, "Turno confirmado en {tienda}" o "Recordatorio: turno en {tienda} el {fecha}".

## 10. Confirmación de baja

**Cuándo:** al abrir el enlace de baja del correo de invitación. Es una página pública que no pide login ni código (BE-04, FE-17). La baja se registra con `POST /public/unsubscribe`, con el token en el cuerpo, y no al cargar la página: los escáneres de correo abren los enlaces y darían de baja a quien no lo pidió.

```
Baja registrada

{tienda} no va a enviar más invitaciones para volver a reservar a {email enmascarado, p. ej. j***@gmail.com}.

Los avisos de los turnos que se reserven (registro, confirmación, recordatorios y cambios)
se siguen enviando porque son parte de la reserva.

[Volver al portal de {tienda}]   [Política de privacidad]
```

Si el enlace venció o no es válido: "El enlace no es válido. Para pedir la baja, escribir a {email_reclamos}."

## 11. Precios

**Regla** (Res. SIyC 4/2025, arts. 1-2, verificada; exigible desde el 01-04-2025): a destinatarios finales, el precio se muestra **en pesos** y como **importe total y final**. Además, en caracteres menores, se muestra el importe neto sin IVA ni impuestos nacionales indirectos, con la leyenda **"PRECIO SIN IMPUESTOS NACIONALES"**.

| Dónde | Texto |
|---|---|
| Tarjeta del servicio (paso 1) y resumen (paso 3) | "Precio final: $ {precio}", con formato `es-AR` (`Price.ts:28-30`) |
| Debajo, en tamaño menor (12 px como mínimo), **solo si la Tienda cargó el importe según su condición fiscal** | "PRECIO SIN IMPUESTOS NACIONALES: $ {neto}" |
| Seña | "Seña a pagar ahora: $ {seña}" y, si la política de la Tienda lo dice, "a cuenta del precio final" |

Si Mercado Pago ofrece cuotas, las muestra Mercado Pago en su propio checkout: el portal no ofrece financiación.

Si el abono de las Tiendas quedara alcanzado (NA-3), la misma regla aplica al precio del plan en el panel.

> **Nota para el abogado (NA-12):** ¿quién debe mostrar la leyenda según la condición fiscal de la Tienda (monotributo o responsable inscripto)? L1 dejó sin verificar el tratamiento de los monotributistas y los cambios posteriores a la norma (P-14). Hace falta un campo en la configuración de la Tienda para cargar el neto o su condición fiscal.

## 12. Data Fiscal

**Regla** (RG AFIP 1415, art. 25, texto de la RG 4042/2017, verificada): los sitios web de quienes venden o prestan servicios, por cuenta propia o de terceros, colocan en un lugar visible de su página principal el logo "Formulario N° 960/D - Data Fiscal", con su hipervínculo.

| De quién | Dónde |
|---|---|
| Shifty | En la página principal pública de Shifty. Hoy no existe, porque `/` redirige al login (`App.tsx:247`). Mientras no haya una landing, va en el pie del login (`Login.tsx`). Enlace: [[COMPLETAR: URL del formulario 960/D de Shifty]]. |
| Cada Tienda | En el pie de su portal, junto a `{identidad_tienda}`. La Tienda pega en su configuración la URL o el código de su propio 960/D (BE-08). Si no lo carga, no se muestra nada: no se inventa un logo. |

> **Nota para el abogado (NA-12):** L1 no verificó si alguna RG de ARCA de 2024 a 2026 modificó el art. 25 (P-14).

## 13. Botón de arrepentimiento (pendiente de decisión)

Si el dictamen y la decisión de Mateo y Enrique (NA-4, DU-06) lo confirman, el botón debe cumplir la Disp. SSDCyLC 954/2025, arts. 1 y 5:

- aparece **a simple vista, en un lugar destacado y en el primer acceso** del portal de cada Tienda, sin registración previa ni ningún otro trámite adicional;
- genera una constancia con código, que llega **dentro de las 24 horas** por el mismo medio;
- avisa a la Tienda, que hace la devolución desde su cuenta de Mercado Pago.

Texto del botón: "Botón de arrepentimiento". Formulario mínimo: número de reserva o teléfono, correo para recibir la constancia y un botón "Enviar solicitud". Confirmación: "Solicitud de arrepentimiento recibida para {tienda}. Código: {codigo}. {tienda} gestiona la devolución de lo pagado. La constancia se envió a {email}."
