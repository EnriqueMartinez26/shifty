# Load Tests (Locust)

Escenarios incluidos:

- `locust_aceptacion.py`: prueba de aceptacion de capacidad (150 clientes + 45 duenos + 5 superadmin, rampa de 5 min y 20 de meseta, rafaga sobre el mismo slot). Se juzga con `scripts/perf_acceptance_check.py`; como correrla y leerla: `docs/PERF_ACCEPTANCE.md`.

- `locustfile.py` (los tres usuarios de abajo) es una herramienta MANUAL (D-20260930-19): no entra en `perf-acceptance.yml`. Es el unico que firma el webhook de Mercado Pago, y sus escenarios de abuso dan 429 a proposito, asi que no sirve como compuerta.
- `PublicAvailabilityUser`: carga sobre disponibilidad publica y reservas (la reserva manda `accepts_terms: true`, obligatorio en el servidor desde PV-09).
- `PublicAbuseUser`: spam controlado sobre OTP y autogestion sin OTP.
- `PaymentsWebhookUser`: carga sobre endpoint de webhook.

## Variables recomendadas

- `SHIFTY_STORE_PUBLIC_ID`
- `SHIFTY_SERVICE_PUBLIC_ID`
- `SHIFTY_STAFF_PUBLIC_ID`
- `SHIFTY_STORE_PUBLIC_IDS` (opcional, lista separada por comas para multi-tenant)
- `SHIFTY_SERVICE_PUBLIC_IDS` (opcional, misma posicion que tiendas)
- `SHIFTY_STAFF_PUBLIC_IDS` (opcional, misma posicion que servicios)
- `SHIFTY_BOOKING_PHONE_PREFIX` (opcional, default `+54911`)
- `SHIFTY_MERCADOPAGO_WEBHOOK_SECRET` (opcional, firma webhooks de prueba)

## Ejecucion local

Desde `backend`:

```bash
uv run locust -f loadtests/locustfile.py --host http://localhost:8000
```

Para prueba headless:

```bash
uv run locust -f loadtests/locustfile.py --host http://localhost:8000 --headless -u 50 -r 10 -t 5m
```
