# Mercado Pago en Shifty

Shifty usa **Checkout Pro** con OAuth por tienda. Las credenciales privadas pertenecen
al backend y nunca deben copiarse al navegador, al repositorio ni a la configuración
visible de una tienda.

## Aplicación de Mercado Pago

Configurar la aplicación del panel con:

- Solución: **Pagos online**.
- Plataforma de e-commerce: **No**.
- Producto: **Checkout Pro**.
- URL OAuth: `https://API_PUBLICA/payments/mercadopago/oauth/callback`.
- PKCE: **Sí**.
- Permisos mínimos: `read`, `write` y `offline_access`.

El número de aplicación y el User ID identifican la aplicación, pero no reemplazan al
client secret. No publicar el client secret, access tokens, refresh tokens ni el secreto
de webhooks.

## Variables del backend

```dotenv
FRONTEND_URL=https://app.example.com
PUBLIC_API_URL=https://api.example.com
MERCADOPAGO_OAUTH_CLIENT_ID=
MERCADOPAGO_OAUTH_CLIENT_SECRET=
MERCADOPAGO_OAUTH_REDIRECT_URI=https://api.example.com/payments/mercadopago/oauth/callback
MERCADOPAGO_WEBHOOK_SECRET=
MERCADOPAGO_OAUTH_STATE_TTL_SECONDS=900
MERCADOPAGO_WEBHOOK_MAX_AGE_SECONDS=300
PAYMENT_HOLD_MINUTES=30
FIELD_ENCRYPTION_KEY=
```

`MERCADOPAGO_OAUTH_REDIRECT_URI` debe coincidir exactamente con la URL registrada en
Mercado Pago. `MERCADOPAGO_WEBHOOK_SECRET` es el secreto de firma entregado por Mercado
Pago para las notificaciones.

## Flujo por tienda

0. La tienda publica su política de seña y reembolso. Sin ella el backend no deja
   activar los cobros online (`DEPOSIT_POLICY_REQUIRED`), y tampoco permite vaciarla
   mientras sigan activos.
1. Un administrador abre **Configuración > Mercado Pago** y autoriza su cuenta.
2. Shifty guarda access y refresh tokens cifrados, asociados exclusivamente a esa tienda.
3. La tienda define en la misma pantalla si acepta coordinar el pago por fuera
   (`allow_manual_coordination`) y publica su política de seña y reembolso.
4. En el booking público, el cliente acepta los términos y elige coordinar con la tienda
   o pagar la seña. Si el servicio tiene la seña marcada como obligatoria y la tienda no
   acepta coordinación manual, la única vía habilitada es Mercado Pago.
5. El backend vuelve a calcular la seña, crea la preferencia y entrega una URL HTTPS
   validada de Mercado Pago.
6. El regreso al frontend solamente inicia una consulta de estado. Nunca se confía en
   parámetros de estado enviados por el navegador.
7. Un webhook firmado consulta el pago a Mercado Pago, valida tienda, referencia,
   preferencia, importe, moneda y cuenta recaudadora antes de confirmar el turno.
   Si el evento no se puede resolver, queda pendiente y se reintenta; nunca se marca
   como procesado sin haberse aplicado.
8. Un turno esperando la seña retiene el slot solo por `PAYMENT_HOLD_MINUTES`. Al
   vencer, se libera. Antes de vencerlo se consulta a Mercado Pago por las dudas de
   que el cobro se haya acreditado sin webhook.
9. La tarea `reconcile_pending_payments` corre cada 5 minutos y recupera los cobros
   acreditados cuya notificación nunca llegó.
8. El dueño o administrador puede usar **Liberar** desde el calendario. Para reservas
   de Mercado Pago, Shifty vence primero la preferencia remota y sólo después libera el
   horario, registra la auditoría y marca el pago como vencido.

## Verificación antes de producción

- Aplicar las migraciones Alembic.
- Ejecutar backend, worker Celery y beat; el vencimiento automático depende del worker.
- Usar HTTPS real para frontend, API, OAuth y webhooks.
- Probar con credenciales de prueba una aprobación, rechazo, pago pendiente, webhook
  duplicado y webhook con firma inválida.
- Confirmar que dos tiendas distintas no puedan consultar ni acreditar pagos cruzados.
- Rotar inmediatamente cualquier secreto que haya sido pegado en logs, tickets o chats.
