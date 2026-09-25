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

## Objetivo de producto

Lo que cada rol deberia poder hacer. No es el estado del codigo: ver la seccion
siguiente y, para las diferencias, la ultima.

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

## Lo que hace el codigo hoy

Verificado contra el codigo el `2026-09-19`. Los conjuntos de roles viven en
`backend/core/roles.py` (`STORE_MANAGERS`, `APPOINTMENT_MANAGERS`,
`REPORT_VIEWERS`, `REPORT_EXPORTERS`) y las dependencias en
`backend/modules/auth/dependencies.py`: `get_current_admin` exige
`STORE_MANAGERS` (`super_admin`, `store_admin`), `get_current_staff` exige
`APPOINTMENT_MANAGERS` (los cuatro roles de personal) y
`get_current_global_admin` exige `is_global_admin`. Algunos routers todavia
comparan el rol persistido (`user.role` en `admin`/`staff`): en esos
`receptionist` queda afuera.

- Agenda interna (`/appointments/*`):
  - listar, buscar y crear: `super_admin`, `store_admin`, `professional`, `receptionist`.
  - crear un turno para un cliente (`POST /appointments/` con `client_name` + `client_phone`, FF-04): los mismos cuatro; el `professional` solo en su propia agenda (`staff_id` igual a su usuario, o ninguno). Cargarlo fuera de la jornada del profesional (`allow_outside_schedule`): `super_admin`, `store_admin`.
  - cancelar y reprogramar: cualquier usuario autenticado de la tienda (el `client` no inicia sesion; cancela por el portal publico). Cancelar un turno con cobro vivo (`pending_payment` o un cobro en `pending`, como el link del panel) tambien: la cancelacion vence el cobro y manda a vencer el link de Mercado Pago en la misma transaccion, sin pasar por el admin (decision del dueno, `2026-09-25`, D2; `tests/integration/test_cancelar_desde_el_panel_vence_el_cobro.py`). Reprogramar desde el panel un `pending_payment` sigue dando 409.
  - confirmar, completar, ausente y notas internas: rol persistido `admin` o `staff` (`store_admin`, `professional`).
  - liberar un turno pendiente: `super_admin`, `store_admin`.
- Bloqueos (`/appointment-blocks/*`): `super_admin`, `store_admin`, `professional`. Cancelar en bloque los turnos afectados: `super_admin`, `store_admin`. Leer la lista (`GET /appointment-blocks/`): ademas `receptionist` (FF-14, `2026-09-24`), solo lectura; todos ven los bloqueos de toda la tienda (el `professional` no se acota a su agenda, igual que en `GET /appointments/`).
- Pagos operativos (`POST /payments/preferences/{appointment_id}`, `POST /payments/{appointment_id}/manual-confirm`, `GET /payments/gateway-config`): `super_admin`, `store_admin`, `professional`.
- Pagos administrativos (`PUT /payments/gateway-config`, OAuth de Mercado Pago, `POST /payments/{payment_id}/refund`, conciliacion y outbox): `super_admin`, `store_admin`.
- Deuda (`/ledger/*`): `super_admin`, `store_admin`, `professional` (ver, cargar y revertir movimientos; `receptionist` no: `_require_financial_access` compara el rol persistido `admin`/`staff`). El buscador de clientes del fiado (`GET /ledger/clients`, decision del dueno `2026-09-25`, D3) tiene la misma puerta y devuelve solo clientes activos de la tienda, con el rol fijado por el servidor: el `professional` busca clientes sin `/users/*`, que sigue siendo solo de admins (`tests/integration/test_fiado_del_profesional.py`, `tests/security/test_idor_entre_tiendas.py`).
- Promociones (`/promotions/*`, salvo `/promotions/preview`): `super_admin`, `store_admin`.
- Usuarios (`/users/*`): `super_admin`, `store_admin`, con estos limites para el admin de tienda:
  - no da de alta ni asciende a `admin`: el alta de admins es del superadmin (`core/roles.py::assert_can_grant_role`; `tests/integration/test_alta_de_admin_solo_superadmin.py`).
  - una cuenta con `is_global_admin` no existe para el (404 en detalle, edicion y baja; no aparece en el listado), y no cambia clave, estado, rol ni email de login de OTRO admin de tienda (`assert_can_change_access`). La misma regla vale por `/staff/*` (`tests/integration/test_panel_no_toca_superadmin.py`, `tests/integration/test_staff_no_toca_cuentas_admin.py`).
- Reportes:
  - lectura (`/reports/summary`, `/reports/professionals`, `/reports/trend`): `super_admin`, `store_admin`, `professional`. El `professional` recibe solo sus turnos y sin resumen de deuda.
  - export (`POST /reports/export`): `super_admin`, `store_admin` (`REPORT_EXPORTERS`; `tests/integration/test_reportes_export_solo_admins.py`).
  - auditoria (`/reports/audit-logs`): `super_admin`, `store_admin`.
- Panel (`/dashboard/summary`): los cuatro roles de personal.
- Reportes y panel del `super_admin`: ve SU tienda, como cualquier usuario; no hay consolidado de todas las tiendas (`core/roles.py::store_scope_for`; `tests/integration/test_superadmin_reportes_de_su_tienda.py`). La consolidacion espera el ok explicito del dueno.
- Soporte global (`/superadmin/*`): solo `is_global_admin`.

## Diferencias entre el objetivo y el codigo

Pendientes de decision del dueno; no se corrigen desde la documentacion.

- `receptionist` no puede cobrar (pagos operativos), ni tocar deuda, ni gestionar bloqueos (solo los lee, FF-14), ni confirmar, completar o marcar ausente un turno, aunque el objetivo le da cobros operativos/manuales y gestion de turnos. Tampoco ve reportes (403).
- `professional` no exporta reportes: la decision del `2026-09-18` (B5-06) lo dejo solo con la lectura de los propios.
