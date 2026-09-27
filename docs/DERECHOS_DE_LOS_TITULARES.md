# Pedidos de acceso, rectificación y supresión de datos

Procedimiento para atender el pedido de un cliente final que quiere saber qué datos suyos hay, corregirlos o borrarlos (Ley 25.326, arts. 14 a 16). Es un procedimiento operativo, no asesoramiento legal: los textos y los plazos los valida el asesor del dueño.

## Quién responde

- **La tienda es la responsable** de los datos de sus clientes. Shifty los trata por cuenta de la tienda.
- Si el pedido llega a Shifty (por email o por cualquier canal), se deriva a la tienda que corresponda dentro de las 48 horas, con copia al titular. Shifty no decide por la tienda.
- Si el titular no sabe en qué tienda reservó, se le pide el nombre de la tienda o el link del portal (`/b/<tienda>`). No se busca a una persona en todas las tiendas.

## Plazos

- **Acceso:** 10 días corridos desde el pedido (art. 14).
- **Rectificación y supresión:** 5 días hábiles (art. 16).

## Verificar la identidad

Antes de entregar o borrar nada, la tienda confirma que quien pide es el titular. Por ejemplo, la respuesta sale al mismo email o teléfono con el que se reservó. No se entregan datos a un tercero, ni a otro email distinto del que figura en la ficha.

## Cómo lo hace la tienda en el panel

Lo hace un admin de la tienda. El id del cliente es el `public_id` de su ficha (lo muestran la agenda y el buscador de clientes).

1. **Acceso:** `GET /users/{client_id}/export` devuelve en JSON los datos del cliente y sus turnos, cobros, movimientos de fiado y lista de espera de esa tienda. Ese archivo se le envía al titular.
2. **Rectificación:** nombre y teléfono se corrigen desde la ficha del usuario (`PATCH /users/{id}`). El email todavía no se puede corregir por la API. Hasta que exista esa función, se deriva a soporte de Shifty y se corrige a mano, dejando constancia.
3. **Supresión:** `POST /users/{client_id}/anonymize`.
   - Reemplaza nombre, teléfono, email, notas y respuestas de la reserva por valores neutros, cierra sus entradas abiertas de la lista de espera y deja al cliente inactivo.
   - Conserva importes, fechas y estados de turnos, cobros y fiado, que la tienda necesita para su contabilidad.
   - **No se puede deshacer.**
   - Si responde 409 `CLIENT_HAS_LIVE_CHARGE`, primero hay que cobrar o cancelar el cobro abierto.
   - Si responde 409 `CLIENT_HAS_ACTIVE_APPOINTMENTS`, primero hay que cancelar los turnos que no empezaron.
   - Si responde 409 `CLIENT_HAS_DEBT`, el cliente tiene saldo en el fiado: primero hay que saldarlo.
   - Tambien neutraliza el texto de los avisos del panel ligados a sus turnos (el titulo de esos avisos es fijo y no nombra a nadie).

Cada exportación y cada anonimización quedan en la auditoría de la tienda con quién la hizo y cuándo, sin datos personales.

## Lo que la anonimización no alcanza

- **Una reserva que llega en el mismo momento:** la anonimización toma la fila del cliente con `FOR UPDATE` hasta el commit, pero la reserva pública busca al cliente por teléfono sin lock. Si esa reserva lee la ficha antes del commit, el turno nuevo queda ligado al cliente anonimizado con el nombre y el teléfono que tipeó en la reserva. Si llega después, el teléfono ya no está en la ficha y se crea un cliente nuevo. En los dos casos la persona volvió a dejar sus datos al reservar: es un tratamiento nuevo, no una falla de la supresión. Si el pedido lo exige, se vuelve a anonimizar después.

- **Copias de seguridad:** la base respaldada conserva los datos hasta que ese backup rota (alrededor de 28 días). No se restaura un backup sin volver a anonimizar a quienes lo pidieron.
- **Datos que se borran solos por retención:**
  - códigos de verificación: 7 días después de vencer;
  - cola de mails y eventos: 90 días;
  - avisos leídos del panel: 180 días (los no leídos se conservan).
- **Mercado Pago:** los datos del pagador que tiene Mercado Pago son de Mercado Pago. El titular se los pide directamente a Mercado Pago.

## Registro del pedido

Por cada pedido, la tienda (o Shifty, si lo derivó) anota:

- fecha de recepción;
- canal;
- tienda;
- tipo de pedido (acceso, rectificación o supresión);
- cómo se verificó la identidad;
- fecha y forma de la respuesta.

No se anotan los datos del titular más allá de lo necesario para identificar el pedido.
