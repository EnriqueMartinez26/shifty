# Load Tests (Locust)

Escenarios incluidos:

- `PublicAvailabilityUser`: carga sobre disponibilidad publica y reservas.
- `PaymentsWebhookUser`: carga sobre endpoint de webhook.

## Variables recomendadas

- `SHIFTY_STORE_PUBLIC_ID`
- `SHIFTY_SERVICE_PUBLIC_ID`
- `SHIFTY_STAFF_PUBLIC_ID`
- `SHIFTY_BOOKING_PHONE_PREFIX` (opcional, default `+54911`)

## Ejecucion local

Desde `backend`:

```bash
uv run locust -f loadtests/locustfile.py --host http://localhost:8000
```

Para prueba headless:

```bash
uv run locust -f loadtests/locustfile.py --host http://localhost:8000 --headless -u 50 -r 10 -t 5m
```
