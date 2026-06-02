# Role Matrix (Shifty)

Roles canonicos:

- `super_admin`
- `store_admin`
- `professional`
- `receptionist`
- `client`

Compatibilidad legacy:

- `admin` -> `store_admin`
- `staff` -> `professional`

## Permisos operativos

- `super_admin`
  - acceso global, revocacion masiva de sesiones, soporte multi-tenant.
- `store_admin`
  - configuracion de tienda, usuarios, servicios, personal, agenda, pagos, deuda, reportes y exportes.
- `professional`
  - su agenda, estados de turnos, notas, reportes propios, registro de cobros operativos.
- `receptionist`
  - crear/gestionar turnos, cobros operativos/manuales, agenda, clientes.
  - sin exportes financieros ni administracion global de tienda.
- `client`
  - flujo publico de reservas y gestion de sus turnos.

## Endpoints clave

- Agenda interna (`/appointments/*`): `super_admin`, `store_admin`, `professional`, `receptionist`
- Bloqueos (`/appointment-blocks/*`): `super_admin`, `store_admin`, `professional`, `receptionist`
- Pagos operativos (`/payments/preferences`, `/payments/{id}/manual-confirm`): `super_admin`, `store_admin`, `professional`, `receptionist`
- Pagos administrativos (`/payments/gateway-config`, `/payments/{id}/refund`, conciliacion): `super_admin`, `store_admin`
- Deuda (`/ledger/*`): `super_admin`, `store_admin`, `professional`, `receptionist`
- Reportes:
  - lectura (`/reports/summary`, `/reports/professionals`): `super_admin`, `store_admin`, `professional`
  - export (`/reports/export`, `/reports/store`): `super_admin`, `store_admin`
