# Emulador de Mercado Pago y flujos de punta a punta

Sin credenciales de sandbox, todo Mercado Pago estaba reemplazado por
monkeypatch en los tests. Esta carpeta trae un emulador HTTP de la parte de la
API que usa Shifty y una suite que recorre los cobros reales contra el:
routers, services y jobs de verdad, y el cliente `httpx` del backend hablando
por un socket real.

| Archivo | Que es |
| --- | --- |
| `mp_emulator.py` | App FastAPI que emula MP. Un `EmulatorState` por instancia. |
| `conftest.py` | Levanta el emulador en un hilo por test y apunta el backend a el. |
| `test_mp_flujos.py` | Los flujos (a) a (l). |

## Correr los tests

Desde `backend/`:

```bash
pytest tests/e2e -p no:cacheprovider
```

Corre sobre la app de integracion (SQLite en memoria). Eso NO prueba RLS, el
trigger de estados, la exclusion GiST ni locks reales (seccion 4 de
`CLAUDE.md`). Tarda unos 20 s: el flujo (j) espera 3 s de latencia a proposito.

| Flujo | Test | Estado |
| --- | --- | --- |
| (a) Reserva con sena crea la preferencia (importe, cuenta, vencimiento, notification_url) | `test_a_*` | pasa |
| (b) Pago + webhook firmado: cobro acreditado, turno confirmado, avisos y mails | `test_b_*` | pasa |
| (c) Webhook duplicado (mismo evento): sin segundo efecto | `test_c_*` | pasa |
| (d) Importe o collector que no coinciden: rechazo sin 5xx, inbox sin sellar | `test_d_*` | pasa |
| (e) Firma alterada, otro secreto, ts viejo o futuro, sin headers: 400/401 y nada cambia | `test_e_*` | pasa |
| (f) Reembolso del panel: se registra (`manual: true`), nunca llama a MP (B2-05) | `test_f_*` | pasa |
| (g) Liberar: `payment.preference.expire` en el outbox y el job vence el link en MP | `test_g_*` | pasa |
| (h) OAuth: 401 una vez, refresh, reintento con el token nuevo | `test_h_*` | pasa |
| (i) Conciliacion: pago acreditado sin webhook | `test_i_*` | pasa |
| (j) MP a 3 s: la reserva corta dentro de un presupuesto de 2 s y compensa | `test_j_*` | pasa (F1-04; el test fija el presupuesto de MP en 1,5 s) |
| (k) Circuit breaker: se abre tras N fallas, la reserva compensa, se recupera | `test_k_*` | pasa |
| (l) La reserva llama a MP sin transaccion abierta | `test_l_*` | pasa (F1-05) |

Cada llamada que recibe el emulador anota `in_tx`: si la sesion de la app
tenia una transaccion abierta en ese momento (regla 5). El flujo (l) lo exige
para la reserva publica: hasta F1-05 la tenia abierta durante el POST a MP.

## API emulada

| Endpoint | Lo usa Shifty para |
| --- | --- |
| `POST /checkout/preferences` | crear el link de pago (devuelve `id`, `init_point`, `sandbox_init_point`) |
| `PUT /checkout/preferences/{id}` | vencer el link (outbox) |
| `GET /v1/payments/{id}` | enriquecer el webhook y conciliar |
| `GET /v1/payments/search?external_reference=` | conciliar sin id de pago |
| `POST /v1/payments/{id}/refunds` | nada: Shifty no ejecuta reembolsos (B2-05) |
| `POST /oauth/token` | `refresh_token` y `authorization_code` (rota el refresh token) |

Todo pide `Authorization: Bearer`, salvo `/oauth/token`. El pago emulado no
trae `preference_id`: Shifty lo encuentra por `external_reference` y
`metadata`. Los formatos siguen la documentacion publica de MP, no una
captura de la API real: lo que el emulador acepta no garantiza que MP lo
acepte (por ejemplo, el formato de `expiration_date_to`).

## Endpoints de control

| Endpoint | Hace |
| --- | --- |
| `POST /_emu/pay/{preference_id}` | Paga el link. Body opcional: `amount`, `collector_id`, `currency_id`, `status` (default `approved`). Un link vencido da 409. |
| `POST /_emu/payment/{id}/status` | Cambia el estado (`in_mediation`, `refunded`, `rejected`, `charged_back`...). |
| `POST /_emu/send_webhook` | Firma el webhook de un pago (`x-signature` con `ts` y `v1`, `x-request-id`) y lo manda al `notification_url` de la preferencia o a `target_url`. `deliver: false` solo lo devuelve. Opciones: `event_id`, `secret`, `ts_offset_seconds`, `tamper`. |
| `POST /_emu/fault` | `latency_ms`, `error_rate` (0 a 1), `error_status`, `unauthorized_once`, `down`. |
| `GET /_emu/state` | Preferencias, pagos, reembolsos, llamadas recibidas y fallas activas. |
| `POST /_emu/reset` | Vacia el estado. |

## Probar a mano con el stack de Docker (solo desarrollo)

1. En el host, desde `backend/`, con el mismo `webhook_secret` que se le va a
   cargar a la tienda:

   ```bash
   MP_EMU_WEBHOOK_SECRET=whsec-local uvicorn tests.e2e.mp_emulator:app --port 9999
   ```

2. Agregar a mano, sin commitear, en el bloque `x-app-environment` del compose
   (el mismo bloque para api, worker y beat: los jobs tambien llaman a MP):

   ```yaml
   MERCADOPAGO_API_BASE_URL: http://host.docker.internal:9999
   ```

   En Linux, ademas, `extra_hosts: ["host.docker.internal:host-gateway"]` en
   los tres servicios, y el emulador tiene que escuchar en todas las
   interfaces para que los contenedores lo alcancen por el host-gateway:
   `uvicorn tests.e2e.mp_emulator:app --host 0.0.0.0 --port 9999`.

   **Cuidado:** con `--host 0.0.0.0` el emulador queda expuesto a la red
   local, y los endpoints `/_emu` no tienen autenticacion: cualquiera en la
   LAN puede ver el estado (tokens de las tiendas incluidos), pagar links,
   mandar webhooks firmados o inyectar fallas. Usarlo solo en una red de
   confianza o con el puerto 9999 cerrado en el firewall salvo para la red
   de Docker, y bajarlo al terminar.

   Es solo variable de entorno: alcanza con recrear los contenedores
   (`docker-compose up -d`), sin rebuild.

3. En el panel, activar cobros y cargar el gateway con cualquier access token
   y el `webhook_secret` del paso 1 (`PUT /payments/gateway-config`; en
   produccion ese endpoint esta cerrado).

4. Reservar un servicio con sena desde el portal. Despues:

   ```bash
   curl -s localhost:9999/_emu/state                       # ver la preferencia
   curl -s -X POST localhost:9999/_emu/pay/<preference_id>  # el cliente paga
   curl -s -X POST localhost:9999/_emu/send_webhook \
     -H 'content-type: application/json' -d '{"payment_id": "<id del pago>"}'
   ```

   El webhook va al `notification_url` que armo Shifty con `PUBLIC_API_URL`
   (en el compose, `http://localhost/api/...`, alcanzable desde el host).

Fuera de desarrollo (staging y produccion) se rechaza cualquier
`MERCADOPAGO_API_BASE_URL` que no sea `https://api.mercadopago.com` (regla 17,
`core/config.py`): no se puede dejar apuntando al emulador por error.
