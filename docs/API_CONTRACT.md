# API Contract

Generado automaticamente desde `app.openapi()` del backend (FastAPI); no editar a mano. Regenerar con `backend/scripts/gen_api_contract.py` (el comando esta en su docstring).

- OpenAPI: 3.1.0
- Paths: 116 — Operaciones: 145

## /

### GET /

- Summary: Root
- operationId: `root__get`

Responses:

- `200` Successful Response — `application/json`: `object<string, string>`

## Appointment Blocks

### GET /appointment-blocks/

- Summary: List Blocks
- operationId: `list_blocks_appointment_blocks__get`

Parameters:

| in | name | required | type | constraints |
|---|---|---|---|---|
| query | `from_date` | no | string \| null | format="date" |
| query | `to_date` | no | string \| null | format="date" |
| query | `include_inactive` | no | boolean \| null |  |

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_list_AppointmentBlockResponse__`
- `422` Validation Error — `application/json`: `HTTPValidationError`

### POST /appointment-blocks/

- Summary: Create Block
- operationId: `create_block_appointment_blocks__post`

Request body (required):

- `application/json`: `AppointmentBlockCreate`

Responses:

- `201` Successful Response — `application/json`: `ApiSuccess_AppointmentBlockResponse_`
- `422` Validation Error — `application/json`: `HTTPValidationError`

### POST /appointment-blocks/batch

- Summary: Create Block Batch
- operationId: `create_block_batch_appointment_blocks_batch_post`

Request body (required):

- `application/json`: `RecurringAppointmentBlockCreate`

Responses:

- `201` Successful Response — `application/json`: `ApiSuccess_AppointmentBlockBatchResponse_`
- `422` Validation Error — `application/json`: `HTTPValidationError`

### POST /appointment-blocks/preview

- Summary: Preview Block
- operationId: `preview_block_appointment_blocks_preview_post`

Request body (required):

- `application/json`: `BlockPreviewRequest`

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_BlockPreviewResponse_`
- `422` Validation Error — `application/json`: `HTTPValidationError`

### POST /appointment-blocks/store-wide

- Summary: Create Store Wide Block
- operationId: `create_store_wide_block_appointment_blocks_store_wide_post`

Request body (required):

- `application/json`: `StoreWideBlockCreate`

Responses:

- `201` Successful Response — `application/json`: `ApiSuccess_StoreWideBlockResponse_`
- `422` Validation Error — `application/json`: `HTTPValidationError`

### GET /appointment-blocks/templates

- Summary: List Block Templates
- operationId: `list_block_templates_appointment_blocks_templates_get`

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_list_BlockTemplateResponse__`

### PATCH /appointment-blocks/{public_id}

- Summary: Update Block
- operationId: `update_block_appointment_blocks__public_id__patch`

Parameters:

| in | name | required | type | constraints |
|---|---|---|---|---|
| path | `public_id` | yes | string | minLength=1, maxLength=64, pattern="^[A-Za-z0-9_-]{1,64}$" |

Request body (required):

- `application/json`: `AppointmentBlockUpdate`

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_AppointmentBlockResponse_`
- `422` Validation Error — `application/json`: `HTTPValidationError`

### DELETE /appointment-blocks/{public_id}

- Summary: Delete Block
- operationId: `delete_block_appointment_blocks__public_id__delete`

Parameters:

| in | name | required | type | constraints |
|---|---|---|---|---|
| path | `public_id` | yes | string | minLength=1, maxLength=64, pattern="^[A-Za-z0-9_-]{1,64}$" |

Responses:

- `204` Successful Response
- `422` Validation Error — `application/json`: `HTTPValidationError`

## Appointments

### GET /appointments/

- Summary: List Appointments By Date
- operationId: `list_appointments_by_date_appointments__get`

Parameters:

| in | name | required | type | constraints |
|---|---|---|---|---|
| query | `date` | yes | string | format="date" |

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_list_AppointmentListItem__`
- `422` Validation Error — `application/json`: `HTTPValidationError`

### POST /appointments/

- Summary: Book Appointment
- operationId: `book_appointment_appointments__post`

Request body (required):

- `application/json`: `AppointmentCreate`

Responses:

- `201` Successful Response — `application/json`: `ApiSuccess_AppointmentResponse_`
- `422` Validation Error — `application/json`: `HTTPValidationError`

### GET /appointments/availability

- Summary: Get Availability
- operationId: `get_availability_appointments_availability_get`

Parameters:

| in | name | required | type | constraints |
|---|---|---|---|---|
| query | `service_id` | yes | string | minLength=1, maxLength=64, pattern="^[A-Za-z0-9_-]{1,64}$" |
| query | `date` | yes | string | format="date" |

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_list_object__`
- `422` Validation Error — `application/json`: `HTTPValidationError`

### GET /appointments/search

- Summary: Search Appointments
- operationId: `search_appointments_appointments_search_get`

Parameters:

| in | name | required | type | constraints |
|---|---|---|---|---|
| query | `client_name` | no | string \| null | maxLength=100 |
| query | `staff_id` | no | string \| null | maxLength=64, pattern="^[A-Za-z0-9_-]{1,64}$" |
| query | `service_id` | no | string \| null | maxLength=64, pattern="^[A-Za-z0-9_-]{1,64}$" |
| query | `statuses` | no | array<string> \| null | maxItems=10 |
| query | `from_date` | no | string \| null | format="date" |
| query | `to_date` | no | string \| null | format="date" |
| query | `page` | no | integer | minimum=1, maximum=10000, default=1 |
| query | `page_size` | no | integer | minimum=1, maximum=100, default=20 |
| query | `include_total` | no | boolean | default=true |
| query | `after` | no | string \| null | maxLength=200 |

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_AppointmentSearchResponse_`
- `422` Validation Error — `application/json`: `HTTPValidationError`

### PATCH /appointments/{public_id}/absent

- Summary: Mark Absent
- operationId: `mark_absent_appointments__public_id__absent_patch`

Parameters:

| in | name | required | type | constraints |
|---|---|---|---|---|
| path | `public_id` | yes | string | minLength=1, maxLength=64, pattern="^[A-Za-z0-9_-]{1,64}$" |

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_AppointmentResponse_`
- `422` Validation Error — `application/json`: `HTTPValidationError`

### PATCH /appointments/{public_id}/cancel

- Summary: Cancel Appointment
- operationId: `cancel_appointment_appointments__public_id__cancel_patch`

Parameters:

| in | name | required | type | constraints |
|---|---|---|---|---|
| path | `public_id` | yes | string | minLength=1, maxLength=64, pattern="^[A-Za-z0-9_-]{1,64}$" |

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_AppointmentResponse_`
- `422` Validation Error — `application/json`: `HTTPValidationError`

### PATCH /appointments/{public_id}/complete

- Summary: Complete Appointment
- operationId: `complete_appointment_appointments__public_id__complete_patch`

Parameters:

| in | name | required | type | constraints |
|---|---|---|---|---|
| path | `public_id` | yes | string | minLength=1, maxLength=64, pattern="^[A-Za-z0-9_-]{1,64}$" |

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_AppointmentResponse_`
- `422` Validation Error — `application/json`: `HTTPValidationError`

### PATCH /appointments/{public_id}/confirm

- Summary: Confirm Appointment
- operationId: `confirm_appointment_appointments__public_id__confirm_patch`

Parameters:

| in | name | required | type | constraints |
|---|---|---|---|---|
| path | `public_id` | yes | string | minLength=1, maxLength=64, pattern="^[A-Za-z0-9_-]{1,64}$" |

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_AppointmentResponse_`
- `422` Validation Error — `application/json`: `HTTPValidationError`

### PATCH /appointments/{public_id}/notes-staff

- Summary: Update Staff Notes
- operationId: `update_staff_notes_appointments__public_id__notes_staff_patch`

Parameters:

| in | name | required | type | constraints |
|---|---|---|---|---|
| path | `public_id` | yes | string | minLength=1, maxLength=64, pattern="^[A-Za-z0-9_-]{1,64}$" |

Request body (required):

- `application/json`: `AppointmentNotesStaffUpdate`

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_AppointmentResponse_`
- `422` Validation Error — `application/json`: `HTTPValidationError`

### PATCH /appointments/{public_id}/release

- Summary: Release Pending Appointment
- operationId: `release_pending_appointment_appointments__public_id__release_patch`

Parameters:

| in | name | required | type | constraints |
|---|---|---|---|---|
| path | `public_id` | yes | string | minLength=1, maxLength=64, pattern="^[A-Za-z0-9_-]{1,64}$" |

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_AppointmentResponse_`
- `422` Validation Error — `application/json`: `HTTPValidationError`

### PATCH /appointments/{public_id}/reschedule

- Summary: Reschedule Appointment
- operationId: `reschedule_appointment_appointments__public_id__reschedule_patch`

Parameters:

| in | name | required | type | constraints |
|---|---|---|---|---|
| path | `public_id` | yes | string | minLength=1, maxLength=64, pattern="^[A-Za-z0-9_-]{1,64}$" |

Request body (required):

- `application/json`: `AppointmentReschedule`

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_AppointmentResponse_`
- `422` Validation Error — `application/json`: `HTTPValidationError`

## Authentication

### PUT /auth/change-password

- Summary: Change Password
- operationId: `change_password_auth_change_password_put`

Request body (required):

- `application/json`: `ChangePasswordRequest`

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_ResetPasswordResponse_`
- `422` Validation Error — `application/json`: `HTTPValidationError`

### POST /auth/forgot-password

- Summary: Forgot Password
- operationId: `forgot_password_auth_forgot_password_post`

Request body (required):

- `application/json`: `ForgotPasswordRequest`

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_ForgotPasswordResponse_`
- `422` Validation Error — `application/json`: `HTTPValidationError`

### POST /auth/login

- Summary: Login
- operationId: `login_auth_login_post`

Request body (required):

- `application/json`: `LoginRequest`

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_TokenResponse_`
- `422` Validation Error — `application/json`: `HTTPValidationError`

### POST /auth/logout

- Summary: Logout
- operationId: `logout_auth_logout_post`

Request body (optional):

- `application/json`: `LogoutRequest | null`

Responses:

- `204` Successful Response
- `422` Validation Error — `application/json`: `HTTPValidationError`

### POST /auth/refresh

- Summary: Refresh Session
- operationId: `refresh_session_auth_refresh_post`

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_TokenResponse_`

### POST /auth/reset-password

- Summary: Reset Password
- operationId: `reset_password_auth_reset_password_post`

Request body (required):

- `application/json`: `ResetPasswordRequest`

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_ResetPasswordResponse_`
- `422` Validation Error — `application/json`: `HTTPValidationError`

### GET /auth/sessions

- Summary: List My Sessions
- operationId: `list_my_sessions_auth_sessions_get`

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_SessionListResponse_`

### POST /auth/sessions/revoke-all

- Summary: Revoke All Sessions
- operationId: `revoke_all_sessions_auth_sessions_revoke_all_post`

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_RevokedSessionsResult_`

### POST /auth/sessions/revoke-store

- Summary: Revoke Store Sessions
- operationId: `revoke_store_sessions_auth_sessions_revoke_store_post`

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_RevokedSessionsResult_`

### POST /auth/sessions/revoke-user/{user_public_id}

- Summary: Revoke User Sessions
- operationId: `revoke_user_sessions_auth_sessions_revoke_user__user_public_id__post`

Parameters:

| in | name | required | type | constraints |
|---|---|---|---|---|
| path | `user_public_id` | yes | string | minLength=1, maxLength=64, pattern="^[A-Za-z0-9_-]{1,64}$" |

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_RevokedSessionsResult_`
- `422` Validation Error — `application/json`: `HTTPValidationError`

### DELETE /auth/sessions/{session_id}

- Summary: Revoke My Session
- operationId: `revoke_my_session_auth_sessions__session_id__delete`

Parameters:

| in | name | required | type | constraints |
|---|---|---|---|---|
| path | `session_id` | yes | string | minLength=1, maxLength=64, pattern="^[A-Za-z0-9_-]{1,64}$" |

Responses:

- `204` Successful Response
- `422` Validation Error — `application/json`: `HTTPValidationError`

## Customer Ledger

### GET /ledger/clients

- Summary: Buscador de clientes del fiado
- operationId: `search_ledger_clients_ledger_clients_get`

Parameters:

| in | name | required | type | constraints |
|---|---|---|---|---|
| query | `q` | no | string \| null | minLength=2, maxLength=80 |
| query | `limit` | no | integer | minimum=1, maximum=100, default=50 |

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_list_LedgerClientItem__`
- `422` Validation Error — `application/json`: `HTTPValidationError`

### GET /ledger/customers/{client_id}

- Summary: Historial de fiado de un cliente (paginado)
- operationId: `get_customer_ledger_ledger_customers__client_id__get`

Parameters:

| in | name | required | type | constraints |
|---|---|---|---|---|
| path | `client_id` | yes | string | minLength=1, maxLength=64, pattern="^[A-Za-z0-9_-]{1,64}$" |
| query | `limit` | no | integer | minimum=1, maximum=200, default=50 |
| query | `offset` | no | integer | minimum=0, maximum=100000, default=0 |
| query | `after` | no | string \| null | maxLength=200 |

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_CustomerLedgerResponse_`
- `422` Validation Error — `application/json`: `HTTPValidationError`

### POST /ledger/customers/{client_id}/movements

- Summary: Add Customer Ledger Movement
- operationId: `add_customer_ledger_movement_ledger_customers__client_id__movements_post`

Parameters:

| in | name | required | type | constraints |
|---|---|---|---|---|
| path | `client_id` | yes | string | minLength=1, maxLength=64, pattern="^[A-Za-z0-9_-]{1,64}$" |

Request body (required):

- `application/json`: `LedgerMovementCreate`

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_LedgerMovementResponse_`
- `422` Validation Error — `application/json`: `HTTPValidationError`

### POST /ledger/customers/{client_id}/movements/{movement_id}/reverse

- Summary: Reverse Customer Ledger Movement
- operationId: `reverse_customer_ledger_movement_ledger_customers__client_id__movements__movement_id__reverse_post`

Parameters:

| in | name | required | type | constraints |
|---|---|---|---|---|
| path | `client_id` | yes | string | minLength=1, maxLength=64, pattern="^[A-Za-z0-9_-]{1,64}$" |
| path | `movement_id` | yes | string | minLength=1, maxLength=64, pattern="^[A-Za-z0-9_-]{1,64}$" |

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_LedgerMovementResponse_`
- `422` Validation Error — `application/json`: `HTTPValidationError`

### GET /ledger/summary

- Summary: Get Ledger Summary
- operationId: `get_ledger_summary_ledger_summary_get`

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_LedgerSummaryResponse_`

## Dashboard

### GET /dashboard/summary

- Summary: Get Dashboard Summary
- operationId: `get_dashboard_summary_dashboard_summary_get`

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_DashboardSummaryResponse_`

## Data Subject Rights

### POST /users/{client_id}/anonymize

- Summary: Anonymize Client
- operationId: `anonymize_client_users__client_id__anonymize_post`

Parameters:

| in | name | required | type | constraints |
|---|---|---|---|---|
| path | `client_id` | yes | string | minLength=1, maxLength=64, pattern="^[A-Za-z0-9_-]{1,64}$" |

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_AnonymizeResponse_`
- `422` Validation Error — `application/json`: `HTTPValidationError`

### GET /users/{client_id}/export

- Summary: Export Client Data
- operationId: `export_client_data_users__client_id__export_get`

Parameters:

| in | name | required | type | constraints |
|---|---|---|---|---|
| path | `client_id` | yes | string | minLength=1, maxLength=64, pattern="^[A-Za-z0-9_-]{1,64}$" |

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_ClientDataExport_`
- `422` Validation Error — `application/json`: `HTTPValidationError`

## Notifications

### GET /notifications

- Summary: List Notifications
- operationId: `list_notifications_notifications_get`

Parameters:

| in | name | required | type | constraints |
|---|---|---|---|---|
| query | `limit` | no | integer | minimum=1, maximum=100, default=20 |
| query | `unread_only` | no | boolean | default=false |

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_NotificationListResponse_`
- `422` Validation Error — `application/json`: `HTTPValidationError`

### POST /notifications/read-all

- Summary: Mark All Notifications Read
- operationId: `mark_all_notifications_read_notifications_read_all_post`

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_NotificationMarkReadResponse_`

### POST /notifications/{notification_id}/read

- Summary: Mark Notification Read
- operationId: `mark_notification_read_notifications__notification_id__read_post`

Parameters:

| in | name | required | type | constraints |
|---|---|---|---|---|
| path | `notification_id` | yes | string | minLength=1, maxLength=64, pattern="^[A-Za-z0-9_-]{1,64}$" |

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_NotificationMarkReadResponse_`
- `422` Validation Error — `application/json`: `HTTPValidationError`

## Operations

### GET /ops/health/live

- Summary: Liveness
- operationId: `liveness_ops_health_live_get`

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_dict_str__str__`

### GET /ops/health/ready

- Summary: Readiness
- operationId: `readiness_ops_health_ready_get`

Responses:

- `200` Successful Response — `application/json`: _(sin esquema)_

### GET /ops/slo

- Summary: Slo Status
- operationId: `slo_status_ops_slo_get`

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_dict_str__Any__`

## Payments

### GET /payments/gateway-config

- Summary: Get Gateway Config
- operationId: `get_gateway_config_payments_gateway_config_get`

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_GatewayConfigResponse_`

### PUT /payments/gateway-config

- Summary: Upsert Gateway Config
- operationId: `upsert_gateway_config_payments_gateway_config_put`

Request body (required):

- `application/json`: `GatewayConfigUpsert`

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_GatewayConfigResponse_`
- `422` Validation Error — `application/json`: `HTTPValidationError`

### GET /payments/mercadopago/oauth/callback

- Summary: Mercadopago Oauth Callback
- operationId: `mercadopago_oauth_callback_payments_mercadopago_oauth_callback_get`

Parameters:

| in | name | required | type | constraints |
|---|---|---|---|---|
| query | `code` | no | string \| null | minLength=3, maxLength=500 |
| query | `state` | no | string \| null | minLength=10, maxLength=4000 |
| query | `error` | no | string \| null | maxLength=120 |
| query | `error_description` | no | string \| null | maxLength=500 |

Responses:

- `307` Successful Response
- `422` Validation Error — `application/json`: `HTTPValidationError`

### DELETE /payments/mercadopago/oauth/connection

- Summary: Disconnect Mercadopago Oauth
- operationId: `disconnect_mercadopago_oauth_payments_mercadopago_oauth_connection_delete`

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_OAuthDisconnectResponse_`

### POST /payments/mercadopago/oauth/refresh

- Summary: Refresh Mercadopago Oauth
- operationId: `refresh_mercadopago_oauth_payments_mercadopago_oauth_refresh_post`

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_GatewayConfigResponse_`

### POST /payments/mercadopago/oauth/start

- Summary: Start Mercadopago Oauth
- operationId: `start_mercadopago_oauth_payments_mercadopago_oauth_start_post`

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_MercadoPagoOAuthStartResponse_`

### POST /payments/outbox/process

- Summary: Process Outbox
- operationId: `process_outbox_payments_outbox_process_post`

Parameters:

| in | name | required | type | constraints |
|---|---|---|---|---|
| query | `limit` | no | integer | minimum=1, maximum=100, default=100 |

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_OutboxProcessResponse_`
- `422` Validation Error — `application/json`: `HTTPValidationError`

### GET /payments/outbox/stats

- Summary: Outbox Stats
- operationId: `outbox_stats_payments_outbox_stats_get`

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_OutboxStatsResponse_`

### POST /payments/preferences/{appointment_id}

- Summary: Create Payment Preference
- operationId: `create_payment_preference_payments_preferences__appointment_id__post`

Parameters:

| in | name | required | type | constraints |
|---|---|---|---|---|
| path | `appointment_id` | yes | string | minLength=1, maxLength=64, pattern="^[A-Za-z0-9_-]{1,64}$" |

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_PaymentPreferenceResponse_`
- `422` Validation Error — `application/json`: `HTTPValidationError`

### GET /payments/reconciliation/summary

- Summary: Reconciliation Summary
- operationId: `reconciliation_summary_payments_reconciliation_summary_get`

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_ReconciliationSummaryResponse_`

### POST /payments/webhooks/mercadopago

- Summary: Mercadopago Webhook
- operationId: `mercadopago_webhook_payments_webhooks_mercadopago_post`

Parameters:

| in | name | required | type | constraints |
|---|---|---|---|---|
| query | `store_id` | no | string \| null | maxLength=64 |

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_dict_str__Any__`
- `422` Validation Error — `application/json`: `HTTPValidationError`

### POST /payments/{appointment_id}/manual-confirm

- Summary: Manual Confirm Payment
- operationId: `manual_confirm_payment_payments__appointment_id__manual_confirm_post`

Parameters:

| in | name | required | type | constraints |
|---|---|---|---|---|
| path | `appointment_id` | yes | string | minLength=1, maxLength=64, pattern="^[A-Za-z0-9_-]{1,64}$" |

Request body (required):

- `application/json`: `ManualPaymentRequest`

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_PaymentResponse_`
- `422` Validation Error — `application/json`: `HTTPValidationError`

### POST /payments/{payment_id}/refund

- Summary: Registro de reembolso hecho fuera de Shifty
- operationId: `refund_payment_payments__payment_id__refund_post`

Parameters:

| in | name | required | type | constraints |
|---|---|---|---|---|
| path | `payment_id` | yes | string | minLength=1, maxLength=64, pattern="^[A-Za-z0-9_-]{1,64}$" |

Request body (required):

- `application/json`: `RefundRequest`

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_PaymentResponse_`
- `422` Validation Error — `application/json`: `HTTPValidationError`

## Promotions

### GET /promotions/

- Summary: List Promotions
- operationId: `list_promotions_promotions__get`

Parameters:

| in | name | required | type | constraints |
|---|---|---|---|---|
| query | `include_inactive` | no | boolean | default=true |

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_list_PromotionResponse__`
- `422` Validation Error — `application/json`: `HTTPValidationError`

### POST /promotions/

- Summary: Create Promotion
- operationId: `create_promotion_promotions__post`

Request body (required):

- `application/json`: `PromotionCreate`

Responses:

- `201` Successful Response — `application/json`: `ApiSuccess_PromotionResponse_`
- `422` Validation Error — `application/json`: `HTTPValidationError`

### GET /promotions/preview

- Summary: Preview Promotion
- operationId: `preview_promotion_promotions_preview_get`

Parameters:

| in | name | required | type | constraints |
|---|---|---|---|---|
| query | `service_id` | yes | string | minLength=1, maxLength=64, pattern="^[A-Za-z0-9_-]{1,64}$" |
| query | `code` | yes | string | minLength=3, maxLength=30 |

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_PromotionQuoteResponse_`
- `422` Validation Error — `application/json`: `HTTPValidationError`

### PATCH /promotions/{promotion_public_id}

- Summary: Update Promotion
- operationId: `update_promotion_promotions__promotion_public_id__patch`

Parameters:

| in | name | required | type | constraints |
|---|---|---|---|---|
| path | `promotion_public_id` | yes | string | minLength=1, maxLength=64, pattern="^[A-Za-z0-9_-]{1,64}$" |

Request body (required):

- `application/json`: `PromotionUpdate`

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_PromotionResponse_`
- `422` Validation Error — `application/json`: `HTTPValidationError`

### DELETE /promotions/{promotion_public_id}

- Summary: Delete Promotion
- operationId: `delete_promotion_promotions__promotion_public_id__delete`

Parameters:

| in | name | required | type | constraints |
|---|---|---|---|---|
| path | `promotion_public_id` | yes | string | minLength=1, maxLength=64, pattern="^[A-Za-z0-9_-]{1,64}$" |

Responses:

- `204` Successful Response
- `422` Validation Error — `application/json`: `HTTPValidationError`

## Public Booking

### POST /public/appointments

- Summary: Create Public Booking
- operationId: `create_public_booking_public_appointments_post`

Request body (required):

- `application/json`: `PublicBookingCreate`

Responses:

- `201` Successful Response — `application/json`: `ApiSuccess_PublicBookingResponse_`
- `422` Validation Error — `application/json`: `HTTPValidationError`

### GET /public/availability

- Summary: Get Public Availability
- operationId: `get_public_availability_public_availability_get`

Parameters:

| in | name | required | type | constraints |
|---|---|---|---|---|
| query | `store_public_id` | yes | string | minLength=1, maxLength=64, pattern="^[A-Za-z0-9_-]{1,64}$" |
| query | `service_id` | yes | string | minLength=1, maxLength=64, pattern="^[A-Za-z0-9_-]{1,64}$" |
| query | `date` | yes | string | pattern="^\\d{4}-\\d{2}-\\d{2}$" |
| query | `force_all` | no | boolean | default=false |

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_list_object__`
- `422` Validation Error — `application/json`: `HTTPValidationError`

### PATCH /public/client/appointments/{public_id}/cancel

- Summary: Client Cancel Appointment
- operationId: `client_cancel_appointment_public_client_appointments__public_id__cancel_patch`

Parameters:

| in | name | required | type | constraints |
|---|---|---|---|---|
| path | `public_id` | yes | string | minLength=1, maxLength=64, pattern="^[A-Za-z0-9_-]{1,64}$" |

Request body (required):

- `application/json`: `ClientCancelRequest`

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_PublicBookingResponse_`
- `422` Validation Error — `application/json`: `HTTPValidationError`

### PATCH /public/client/appointments/{public_id}/reschedule

- Summary: Client Reschedule Appointment
- operationId: `client_reschedule_appointment_public_client_appointments__public_id__reschedule_patch`

Parameters:

| in | name | required | type | constraints |
|---|---|---|---|---|
| path | `public_id` | yes | string | minLength=1, maxLength=64, pattern="^[A-Za-z0-9_-]{1,64}$" |

Request body (required):

- `application/json`: `ClientRescheduleRequest`

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_PublicBookingResponse_`
- `422` Validation Error — `application/json`: `HTTPValidationError`

### GET /public/client/{store_public_id}/{phone}/appointments

- Summary: Get Client Appointments
- operationId: `get_client_appointments_public_client__store_public_id___phone__appointments_get`

Parameters:

| in | name | required | type | constraints |
|---|---|---|---|---|
| path | `store_public_id` | yes | string | minLength=1, maxLength=64, pattern="^[A-Za-z0-9_-]{1,64}$" |
| path | `phone` | yes | string | minLength=6, maxLength=30 |
| query | `limit` | no | integer | minimum=1, maximum=200, default=50 |

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_ClientAppointmentsResponse_`
- `422` Validation Error — `application/json`: `HTTPValidationError`

### GET /public/deposit/preview

- Summary: Preview Public Deposit
- operationId: `preview_public_deposit_public_deposit_preview_get`

Parameters:

| in | name | required | type | constraints |
|---|---|---|---|---|
| query | `store_public_id` | yes | string | minLength=1, maxLength=64, pattern="^[A-Za-z0-9_-]{1,64}$" |
| query | `service_id` | yes | string | minLength=1, maxLength=64, pattern="^[A-Za-z0-9_-]{1,64}$" |
| query | `starts_at` | yes | string | format="date-time" |
| query | `client_phone` | no | string \| null | minLength=6, maxLength=30 |
| query | `promotion_code` | no | string \| null | minLength=3, maxLength=30 |

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_PublicDepositPreviewResponse_`
- `422` Validation Error — `application/json`: `HTTPValidationError`

### POST /public/otp/request

- Summary: Request Public Otp
- operationId: `request_public_otp_public_otp_request_post`

Request body (required):

- `application/json`: `OtpRequestPayload`

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_dict_str__object__`
- `422` Validation Error — `application/json`: `HTTPValidationError`

### POST /public/otp/verify

- Summary: Verify Public Otp
- operationId: `verify_public_otp_public_otp_verify_post`

Request body (required):

- `application/json`: `OtpVerifyPayload`

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_dict_str__object__`
- `422` Validation Error — `application/json`: `HTTPValidationError`

### GET /public/payments/{payment_public_id}/status

- Summary: Get Public Payment Status
- operationId: `get_public_payment_status_public_payments__payment_public_id__status_get`

Parameters:

| in | name | required | type | constraints |
|---|---|---|---|---|
| path | `payment_public_id` | yes | string | minLength=1, maxLength=64, pattern="^[A-Za-z0-9_-]{1,64}$" |
| query | `store_public_id` | yes | string | minLength=1, maxLength=64, pattern="^[A-Za-z0-9_-]{1,64}$" |

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_PublicPaymentStatusResponse_`
- `422` Validation Error — `application/json`: `HTTPValidationError`

### GET /public/promotions/preview

- Summary: Preview Public Promotion
- operationId: `preview_public_promotion_public_promotions_preview_get`

Parameters:

| in | name | required | type | constraints |
|---|---|---|---|---|
| query | `store_public_id` | yes | string | minLength=1, maxLength=64, pattern="^[A-Za-z0-9_-]{1,64}$" |
| query | `service_id` | yes | string | minLength=1, maxLength=64, pattern="^[A-Za-z0-9_-]{1,64}$" |
| query | `code` | yes | string | minLength=3, maxLength=30 |

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_PublicPromotionPreviewResponse_`
- `422` Validation Error — `application/json`: `HTTPValidationError`

### GET /public/services

- Summary: Get Public Services
- operationId: `get_public_services_public_services_get`

Parameters:

| in | name | required | type | constraints |
|---|---|---|---|---|
| query | `store_public_id` | yes | string | minLength=1, maxLength=64, pattern="^[A-Za-z0-9_-]{1,64}$" |

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_list_PublicServiceResponse__`
- `422` Validation Error — `application/json`: `HTTPValidationError`

### GET /public/staff

- Summary: Get Public Staff
- operationId: `get_public_staff_public_staff_get`

Parameters:

| in | name | required | type | constraints |
|---|---|---|---|---|
| query | `store_public_id` | no | string \| null | maxLength=64, pattern="^[A-Za-z0-9_-]{1,64}$" |
| query | `service_id` | no | string \| null | maxLength=64, pattern="^[A-Za-z0-9_-]{1,64}$" |

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_list_PublicStaffResponse__`
- `422` Validation Error — `application/json`: `HTTPValidationError`

### GET /public/stores/{slug}

- Summary: Get Store By Slug
- operationId: `get_store_by_slug_public_stores__slug__get`

Parameters:

| in | name | required | type | constraints |
|---|---|---|---|---|
| path | `slug` | yes | string | minLength=2, maxLength=100, pattern="^[A-Za-z0-9][A-Za-z0-9-]{0,98}$" |

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_PublicStoreResponse_`
- `422` Validation Error — `application/json`: `HTTPValidationError`

### GET /public/stores/{slug}/ref

- Summary: Get Store Ref By Slug
- operationId: `get_store_ref_by_slug_public_stores__slug__ref_get`

Parameters:

| in | name | required | type | constraints |
|---|---|---|---|---|
| path | `slug` | yes | string | minLength=2, maxLength=100, pattern="^[A-Za-z0-9][A-Za-z0-9-]{0,98}$" |

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_PublicStoreRefResponse_`
- `422` Validation Error — `application/json`: `HTTPValidationError`

## Public Legal

### GET /public/legal/versions

- Summary: Get Legal Versions
- operationId: `get_legal_versions_public_legal_versions_get`

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_LegalVersionsResponse_`

### GET /public/unsubscribe

- Summary: Unsubscribe From Marketing
- operationId: `unsubscribe_from_marketing_public_unsubscribe_get`

Parameters:

| in | name | required | type | constraints |
|---|---|---|---|---|
| query | `token` | yes | string | minLength=1, maxLength=256 |

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_UnsubscribeResponse_`
- `422` Validation Error — `application/json`: `HTTPValidationError`

### POST /public/unsubscribe

- Summary: Unsubscribe From Marketing Post
- operationId: `unsubscribe_from_marketing_post_public_unsubscribe_post`

Request body (required):

- `application/json`: `UnsubscribeRequest`

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_UnsubscribeResponse_`
- `422` Validation Error — `application/json`: `HTTPValidationError`

## Public Waitlist

### POST /public/waitlist

- Summary: Join Waitlist
- operationId: `join_waitlist_public_waitlist_post`

Request body (required):

- `application/json`: `WaitlistJoinRequest`

Responses:

- `201` Successful Response — `application/json`: `ApiSuccess_WaitlistEntryResponse_`
- `422` Validation Error — `application/json`: `HTTPValidationError`

### POST /public/waitlist/mine

- Summary: My Waitlist Entries
- operationId: `my_waitlist_entries_public_waitlist_mine_post`

Request body (required):

- `application/json`: `WaitlistClientQuery`

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_list_WaitlistEntryResponse__`
- `422` Validation Error — `application/json`: `HTTPValidationError`

### POST /public/waitlist/{entry_id}/leave

- Summary: Leave Waitlist
- operationId: `leave_waitlist_public_waitlist__entry_id__leave_post`

Parameters:

| in | name | required | type | constraints |
|---|---|---|---|---|
| path | `entry_id` | yes | string | minLength=1, maxLength=64, pattern="^[A-Za-z0-9_-]{1,64}$" |

Request body (required):

- `application/json`: `WaitlistClientQuery`

Responses:

- `204` Successful Response
- `422` Validation Error — `application/json`: `HTTPValidationError`

## Reports

### GET /reports/audit-logs

- Summary: List Audit Logs
- operationId: `list_audit_logs_reports_audit_logs_get`

Parameters:

| in | name | required | type | constraints |
|---|---|---|---|---|
| query | `limit` | no | integer | minimum=1, maximum=100, default=50 |
| query | `offset` | no | integer | minimum=0, maximum=10000, default=0 |
| query | `resource_id` | no | string \| null | maxLength=64, pattern="^[A-Za-z0-9_-]{1,64}$" |

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_list_AuditLogItem__`
- `422` Validation Error — `application/json`: `HTTPValidationError`

### POST /reports/export

- Summary: Export Report
- operationId: `export_report_reports_export_post`

Request body (required):

- `application/json`: `ReportExportRequest`

Responses:

- `200` Successful Response — `application/json`: _(sin esquema)_
- `422` Validation Error — `application/json`: `HTTPValidationError`

### GET /reports/professionals

- Summary: Get Professional Reports
- operationId: `get_professional_reports_reports_professionals_get`

Parameters:

| in | name | required | type | constraints |
|---|---|---|---|---|
| query | `from_date` | no | string \| null | format="date" |
| query | `to_date` | no | string \| null | format="date" |

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_ProfessionalReportsResponse_`
- `422` Validation Error — `application/json`: `HTTPValidationError`

### GET /reports/summary

- Summary: Get Report Summary
- operationId: `get_report_summary_reports_summary_get`

Parameters:

| in | name | required | type | constraints |
|---|---|---|---|---|
| query | `from_date` | no | string \| null | format="date" |
| query | `to_date` | no | string \| null | format="date" |
| query | `limit` | no | integer | minimum=1, maximum=5000, default=2000 |
| query | `offset` | no | integer | minimum=0, maximum=100000, default=0 |
| query | `order` | no | enum("asc", "desc") | default="asc" |

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_ReportSummaryResponse_`
- `422` Validation Error — `application/json`: `HTTPValidationError`

### GET /reports/trend

- Summary: Get Report Trend
- operationId: `get_report_trend_reports_trend_get`

Parameters:

| in | name | required | type | constraints |
|---|---|---|---|---|
| query | `months` | no | integer | minimum=1, maximum=24, default=6 |

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_ReportTrendResponse_`
- `422` Validation Error — `application/json`: `HTTPValidationError`

## Services

### GET /services/

- Summary: List Services
- operationId: `list_services_services__get`

Parameters:

| in | name | required | type | constraints |
|---|---|---|---|---|
| query | `include_inactive` | no | boolean | default=false |
| query | `limit` | no | integer | minimum=1, maximum=500, default=500 |
| query | `offset` | no | integer | minimum=0, maximum=1000000, default=0 |

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_list_ServiceResponse__`
- `422` Validation Error — `application/json`: `HTTPValidationError`

### POST /services/

- Summary: Create Service
- operationId: `create_service_services__post`

Request body (required):

- `application/json`: `ServiceCreate`

Responses:

- `201` Successful Response — `application/json`: `ApiSuccess_ServiceResponse_`
- `422` Validation Error — `application/json`: `HTTPValidationError`

### GET /services/{public_id}

- Summary: Get Service
- operationId: `get_service_services__public_id__get`

Parameters:

| in | name | required | type | constraints |
|---|---|---|---|---|
| path | `public_id` | yes | string | minLength=1, maxLength=64, pattern="^[A-Za-z0-9_-]{1,64}$" |

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_ServiceResponse_`
- `422` Validation Error — `application/json`: `HTTPValidationError`

### PATCH /services/{public_id}

- Summary: Update Service
- operationId: `update_service_services__public_id__patch`

Parameters:

| in | name | required | type | constraints |
|---|---|---|---|---|
| path | `public_id` | yes | string | minLength=1, maxLength=64, pattern="^[A-Za-z0-9_-]{1,64}$" |

Request body (required):

- `application/json`: `ServiceUpdate`

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_ServiceResponse_`
- `422` Validation Error — `application/json`: `HTTPValidationError`

### DELETE /services/{public_id}

- Summary: Delete Service
- operationId: `delete_service_services__public_id__delete`

Parameters:

| in | name | required | type | constraints |
|---|---|---|---|---|
| path | `public_id` | yes | string | minLength=1, maxLength=64, pattern="^[A-Za-z0-9_-]{1,64}$" |

Responses:

- `204` Successful Response
- `422` Validation Error — `application/json`: `HTTPValidationError`

### POST /services/{public_id}/image

- Summary: Upload Service Image
- operationId: `upload_service_image_services__public_id__image_post`

Parameters:

| in | name | required | type | constraints |
|---|---|---|---|---|
| path | `public_id` | yes | string | minLength=1, maxLength=64, pattern="^[A-Za-z0-9_-]{1,64}$" |

Request body (required):

- `multipart/form-data`: `Body_upload_service_image_services__public_id__image_post`

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_ServiceResponse_`
- `422` Validation Error — `application/json`: `HTTPValidationError`

### DELETE /services/{public_id}/image

- Summary: Delete Service Image
- operationId: `delete_service_image_services__public_id__image_delete`

Parameters:

| in | name | required | type | constraints |
|---|---|---|---|---|
| path | `public_id` | yes | string | minLength=1, maxLength=64, pattern="^[A-Za-z0-9_-]{1,64}$" |

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_ServiceResponse_`
- `422` Validation Error — `application/json`: `HTTPValidationError`

## Staff

### GET /staff/

- Summary: List Staff
- operationId: `list_staff_staff__get`

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_list_StaffResponse__`

### POST /staff/

- Summary: Create Staff
- operationId: `create_staff_staff__post`

Request body (required):

- `application/json`: `StaffCreate`

Responses:

- `201` Successful Response — `application/json`: `ApiSuccess_StaffResponse_`
- `422` Validation Error — `application/json`: `HTTPValidationError`

### GET /staff/{public_id}

- Summary: Get Staff
- operationId: `get_staff_staff__public_id__get`

Parameters:

| in | name | required | type | constraints |
|---|---|---|---|---|
| path | `public_id` | yes | string | minLength=1, maxLength=64, pattern="^[A-Za-z0-9_-]{1,64}$" |

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_StaffResponse_`
- `422` Validation Error — `application/json`: `HTTPValidationError`

### PUT /staff/{public_id}

- Summary: Update Staff
- operationId: `update_staff_staff__public_id__put`

Parameters:

| in | name | required | type | constraints |
|---|---|---|---|---|
| path | `public_id` | yes | string | minLength=1, maxLength=64, pattern="^[A-Za-z0-9_-]{1,64}$" |

Request body (required):

- `application/json`: `StaffUpdate`

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_StaffResponse_`
- `422` Validation Error — `application/json`: `HTTPValidationError`

### PATCH /staff/{public_id}

- Summary: Update Staff
- operationId: `update_staff_staff__public_id__patch`

Parameters:

| in | name | required | type | constraints |
|---|---|---|---|---|
| path | `public_id` | yes | string | minLength=1, maxLength=64, pattern="^[A-Za-z0-9_-]{1,64}$" |

Request body (required):

- `application/json`: `StaffUpdate`

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_StaffResponse_`
- `422` Validation Error — `application/json`: `HTTPValidationError`

### DELETE /staff/{public_id}

- Summary: Delete Staff
- operationId: `delete_staff_staff__public_id__delete`

Parameters:

| in | name | required | type | constraints |
|---|---|---|---|---|
| path | `public_id` | yes | string | minLength=1, maxLength=64, pattern="^[A-Za-z0-9_-]{1,64}$" |

Responses:

- `204` Successful Response
- `422` Validation Error — `application/json`: `HTTPValidationError`

### POST /staff/{public_id}/schedules

- Summary: Add Staff Schedule
- operationId: `add_staff_schedule_staff__public_id__schedules_post`

Parameters:

| in | name | required | type | constraints |
|---|---|---|---|---|
| path | `public_id` | yes | string | minLength=1, maxLength=64, pattern="^[A-Za-z0-9_-]{1,64}$" |

Request body (required):

- `application/json`: `ScheduleCreate`

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_ScheduleResponse_`
- `422` Validation Error — `application/json`: `HTTPValidationError`

### PATCH /staff/{public_id}/schedules/{schedule_id}

- Summary: Update Staff Schedule
- operationId: `update_staff_schedule_staff__public_id__schedules__schedule_id__patch`

Parameters:

| in | name | required | type | constraints |
|---|---|---|---|---|
| path | `public_id` | yes | string | minLength=1, maxLength=64, pattern="^[A-Za-z0-9_-]{1,64}$" |
| path | `schedule_id` | yes | string | minLength=1, maxLength=64, pattern="^[A-Za-z0-9_-]{1,64}$" |

Request body (required):

- `application/json`: `ScheduleUpdate`

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_ScheduleResponse_`
- `422` Validation Error — `application/json`: `HTTPValidationError`

### DELETE /staff/{public_id}/schedules/{schedule_id}

- Summary: Delete Staff Schedule
- operationId: `delete_staff_schedule_staff__public_id__schedules__schedule_id__delete`

Parameters:

| in | name | required | type | constraints |
|---|---|---|---|---|
| path | `public_id` | yes | string | minLength=1, maxLength=64, pattern="^[A-Za-z0-9_-]{1,64}$" |
| path | `schedule_id` | yes | string | minLength=1, maxLength=64, pattern="^[A-Za-z0-9_-]{1,64}$" |

Responses:

- `204` Successful Response
- `422` Validation Error — `application/json`: `HTTPValidationError`

### PATCH /staff/{public_id}/services

- Summary: Update Staff Services
- operationId: `update_staff_services_staff__public_id__services_patch`

Parameters:

| in | name | required | type | constraints |
|---|---|---|---|---|
| path | `public_id` | yes | string | minLength=1, maxLength=64, pattern="^[A-Za-z0-9_-]{1,64}$" |

Request body (required):

- `application/json`: `array<string>`

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_dict_str__str__`
- `422` Validation Error — `application/json`: `HTTPValidationError`

## Store Terms

### GET /stores/me/terms-acceptance

- Summary: Get Store Terms Status
- operationId: `get_store_terms_status_stores_me_terms_acceptance_get`

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_StoreTermsStatusResponse_`

### POST /stores/me/terms-acceptance

- Summary: Accept Store Terms
- operationId: `accept_store_terms_stores_me_terms_acceptance_post`

Responses:

- `201` Successful Response — `application/json`: `ApiSuccess_StoreTermsAcceptanceResponse_`

## Stores

### GET /stores/me

- Summary: Get My Store
- operationId: `get_my_store_stores_me_get`

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_StoreResponse_`

### PATCH /stores/me

- Summary: Update My Store
- operationId: `update_my_store_stores_me_patch`

Request body (required):

- `application/json`: `StoreUpdate`

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_StoreResponse_`
- `422` Validation Error — `application/json`: `HTTPValidationError`

### GET /stores/me/feature-flags

- Summary: Get My Store Feature Flags
- operationId: `get_my_store_feature_flags_stores_me_feature_flags_get`

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_StoreFeatureFlagsResponse_`

### PUT /stores/me/feature-flags

- Summary: Update My Store Feature Flags
- operationId: `update_my_store_feature_flags_stores_me_feature_flags_put`

Request body (required):

- `application/json`: `StoreFeatureFlagsUpdate`

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_StoreFeatureFlagsResponse_`
- `422` Validation Error — `application/json`: `HTTPValidationError`

### POST /stores/me/media

- Summary: Upload Store Media
- operationId: `upload_store_media_stores_me_media_post`

Request body (required):

- `multipart/form-data`: `Body_upload_store_media_stores_me_media_post`

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_StoreMediaUploadResponse_`
- `422` Validation Error — `application/json`: `HTTPValidationError`

### GET /stores/me/subscription

- Summary: Get My Subscription
- operationId: `get_my_subscription_stores_me_subscription_get`

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_StoreSubscriptionStatusResponse_`

### GET /stores/media/{media_id}

- Summary: Serve Store Media
- operationId: `serve_store_media`

Parameters:

| in | name | required | type | constraints |
|---|---|---|---|---|
| path | `media_id` | yes | string | minLength=1, maxLength=64, pattern="^[A-Za-z0-9_-]{1,64}$" |

Responses:

- `200` Successful Response — `application/json`: _(sin esquema)_
- `422` Validation Error — `application/json`: `HTTPValidationError`

### HEAD /stores/media/{media_id}

- Summary: Serve Store Media
- operationId: `head_store_media`

Parameters:

| in | name | required | type | constraints |
|---|---|---|---|---|
| path | `media_id` | yes | string | minLength=1, maxLength=64, pattern="^[A-Za-z0-9_-]{1,64}$" |

Responses:

- `200` Successful Response — `application/json`: _(sin esquema)_
- `422` Validation Error — `application/json`: `HTTPValidationError`

## SuperAdmin

### GET /superadmin/coupons

- Summary: List Coupons
- operationId: `list_coupons_superadmin_coupons_get`

Parameters:

| in | name | required | type | constraints |
|---|---|---|---|---|
| query | `include_inactive` | no | boolean | default=false |

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_list_CouponResponse__`
- `422` Validation Error — `application/json`: `HTTPValidationError`

### POST /superadmin/coupons

- Summary: Create Coupon
- operationId: `create_coupon_superadmin_coupons_post`

Request body (required):

- `application/json`: `CouponCreate`

Responses:

- `201` Successful Response — `application/json`: `ApiSuccess_CouponResponse_`
- `422` Validation Error — `application/json`: `HTTPValidationError`

### GET /superadmin/coupons/{coupon_public_id}

- Summary: Get Coupon
- operationId: `get_coupon_superadmin_coupons__coupon_public_id__get`

Parameters:

| in | name | required | type | constraints |
|---|---|---|---|---|
| path | `coupon_public_id` | yes | string | minLength=1, maxLength=64, pattern="^[A-Za-z0-9_-]{1,64}$" |

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_CouponResponse_`
- `422` Validation Error — `application/json`: `HTTPValidationError`

### PATCH /superadmin/coupons/{coupon_public_id}

- Summary: Update Coupon
- operationId: `update_coupon_superadmin_coupons__coupon_public_id__patch`

Parameters:

| in | name | required | type | constraints |
|---|---|---|---|---|
| path | `coupon_public_id` | yes | string | minLength=1, maxLength=64, pattern="^[A-Za-z0-9_-]{1,64}$" |

Request body (required):

- `application/json`: `CouponUpdate`

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_CouponResponse_`
- `422` Validation Error — `application/json`: `HTTPValidationError`

### GET /superadmin/plans

- Summary: List Plans
- operationId: `list_plans_superadmin_plans_get`

Parameters:

| in | name | required | type | constraints |
|---|---|---|---|---|
| query | `include_inactive` | no | boolean | default=false |

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_list_PlanResponse__`
- `422` Validation Error — `application/json`: `HTTPValidationError`

### POST /superadmin/plans

- Summary: Create Plan
- operationId: `create_plan_superadmin_plans_post`

Request body (required):

- `application/json`: `PlanCreate`

Responses:

- `201` Successful Response — `application/json`: `ApiSuccess_PlanResponse_`
- `422` Validation Error — `application/json`: `HTTPValidationError`

### PATCH /superadmin/plans/{plan_public_id}

- Summary: Update Plan
- operationId: `update_plan_superadmin_plans__plan_public_id__patch`

Parameters:

| in | name | required | type | constraints |
|---|---|---|---|---|
| path | `plan_public_id` | yes | string | minLength=1, maxLength=64, pattern="^[A-Za-z0-9_-]{1,64}$" |

Request body (required):

- `application/json`: `PlanUpdate`

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_PlanResponse_`
- `422` Validation Error — `application/json`: `HTTPValidationError`

### GET /superadmin/stores

- Summary: List Stores
- operationId: `list_stores_superadmin_stores_get`

Parameters:

| in | name | required | type | constraints |
|---|---|---|---|---|
| query | `search` | no | string \| null | maxLength=100 |
| query | `is_active` | no | boolean \| const "all" | default=true |
| query | `has_subscription` | no | boolean \| null |  |
| query | `limit` | no | integer | minimum=1, maximum=200, default=50 |
| query | `offset` | no | integer | minimum=0, maximum=1000000, default=0 |

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_list_StoreTableResponse__`
- `422` Validation Error — `application/json`: `HTTPValidationError`

### POST /superadmin/stores

- Summary: Create Store
- operationId: `create_store_superadmin_stores_post`

Request body (required):

- `application/json`: `StoreCreate`

Responses:

- `201` Successful Response — `application/json`: `ApiSuccess_StoreGlobalResponse_`
- `422` Validation Error — `application/json`: `HTTPValidationError`

### GET /superadmin/stores/{store_public_id}

- Summary: Get Store
- operationId: `get_store_superadmin_stores__store_public_id__get`

Parameters:

| in | name | required | type | constraints |
|---|---|---|---|---|
| path | `store_public_id` | yes | string | minLength=1, maxLength=64, pattern="^[A-Za-z0-9_-]{1,64}$" |

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_StoreGlobalResponse_`
- `422` Validation Error — `application/json`: `HTTPValidationError`

### PATCH /superadmin/stores/{store_public_id}

- Summary: Update Store
- operationId: `update_store_superadmin_stores__store_public_id__patch`

Parameters:

| in | name | required | type | constraints |
|---|---|---|---|---|
| path | `store_public_id` | yes | string | minLength=1, maxLength=64, pattern="^[A-Za-z0-9_-]{1,64}$" |

Request body (required):

- `application/json`: `StoreGlobalUpdate`

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_StoreGlobalResponse_`
- `422` Validation Error — `application/json`: `HTTPValidationError`

### POST /superadmin/stores/{store_public_id}/admins

- Summary: Create Store Admin
- operationId: `create_store_admin_superadmin_stores__store_public_id__admins_post`

Parameters:

| in | name | required | type | constraints |
|---|---|---|---|---|
| path | `store_public_id` | yes | string | minLength=1, maxLength=64, pattern="^[A-Za-z0-9_-]{1,64}$" |

Request body (required):

- `application/json`: `StoreAdminCreate`

Responses:

- `201` Successful Response — `application/json`: `ApiSuccess_UserGlobalResponse_`
- `422` Validation Error — `application/json`: `HTTPValidationError`

### GET /superadmin/stores/{store_public_id}/audit-logs

- Summary: List Store Audit Logs
- operationId: `list_store_audit_logs_superadmin_stores__store_public_id__audit_logs_get`

Parameters:

| in | name | required | type | constraints |
|---|---|---|---|---|
| path | `store_public_id` | yes | string | minLength=1, maxLength=64, pattern="^[A-Za-z0-9_-]{1,64}$" |
| query | `limit` | no | integer | minimum=1, maximum=50, default=15 |

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_list_AuditLogResponse__`
- `422` Validation Error — `application/json`: `HTTPValidationError`

### GET /superadmin/stores/{store_public_id}/coupon-redemptions

- Summary: List Store Redemptions
- operationId: `list_store_redemptions_superadmin_stores__store_public_id__coupon_redemptions_get`

Parameters:

| in | name | required | type | constraints |
|---|---|---|---|---|
| path | `store_public_id` | yes | string | minLength=1, maxLength=64, pattern="^[A-Za-z0-9_-]{1,64}$" |
| query | `limit` | no | integer | minimum=1, maximum=200, default=50 |

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_list_CouponRedemptionResponse__`
- `422` Validation Error — `application/json`: `HTTPValidationError`

### POST /superadmin/stores/{store_public_id}/coupons/redeem

- Summary: Redeem Store Coupon
- operationId: `redeem_store_coupon_superadmin_stores__store_public_id__coupons_redeem_post`

Parameters:

| in | name | required | type | constraints |
|---|---|---|---|---|
| path | `store_public_id` | yes | string | minLength=1, maxLength=64, pattern="^[A-Za-z0-9_-]{1,64}$" |

Request body (required):

- `application/json`: `CouponRedeemRequest`

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_CouponRedemptionResponse_`
- `422` Validation Error — `application/json`: `HTTPValidationError`

### GET /superadmin/stores/{store_public_id}/overview

- Summary: Get Store Overview
- operationId: `get_store_overview_superadmin_stores__store_public_id__overview_get`

Parameters:

| in | name | required | type | constraints |
|---|---|---|---|---|
| path | `store_public_id` | yes | string | minLength=1, maxLength=64, pattern="^[A-Za-z0-9_-]{1,64}$" |

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_StoreOverviewResponse_`
- `422` Validation Error — `application/json`: `HTTPValidationError`

### GET /superadmin/stores/{store_public_id}/subscription

- Summary: Get Store Subscription
- operationId: `get_store_subscription_superadmin_stores__store_public_id__subscription_get`

Parameters:

| in | name | required | type | constraints |
|---|---|---|---|---|
| path | `store_public_id` | yes | string | minLength=1, maxLength=64, pattern="^[A-Za-z0-9_-]{1,64}$" |

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_StoreSubscriptionResponse_`
- `422` Validation Error — `application/json`: `HTTPValidationError`

### POST /superadmin/stores/{store_public_id}/subscription

- Summary: Set Store Subscription
- operationId: `set_store_subscription_superadmin_stores__store_public_id__subscription_post`

Parameters:

| in | name | required | type | constraints |
|---|---|---|---|---|
| path | `store_public_id` | yes | string | minLength=1, maxLength=64, pattern="^[A-Za-z0-9_-]{1,64}$" |

Request body (required):

- `application/json`: `StoreSubscriptionCreate`

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_StoreSubscriptionResponse_`
- `422` Validation Error — `application/json`: `HTTPValidationError`

### GET /superadmin/stores/{store_public_id}/users

- Summary: List Store Users
- operationId: `list_store_users_superadmin_stores__store_public_id__users_get`

Parameters:

| in | name | required | type | constraints |
|---|---|---|---|---|
| path | `store_public_id` | yes | string | minLength=1, maxLength=64, pattern="^[A-Za-z0-9_-]{1,64}$" |
| query | `include_inactive` | no | boolean | default=false |
| query | `limit` | no | integer | minimum=1, maximum=200, default=50 |
| query | `offset` | no | integer | minimum=0, maximum=1000000, default=0 |

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_list_UserGlobalResponse__`
- `422` Validation Error — `application/json`: `HTTPValidationError`

### PATCH /superadmin/users/{user_public_id}

- Summary: Update User
- operationId: `update_user_superadmin_users__user_public_id__patch`

Parameters:

| in | name | required | type | constraints |
|---|---|---|---|---|
| path | `user_public_id` | yes | string | minLength=1, maxLength=64, pattern="^[A-Za-z0-9_-]{1,64}$" |

Request body (required):

- `application/json`: `UserGlobalUpdate`

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_UserGlobalResponse_`
- `422` Validation Error — `application/json`: `HTTPValidationError`

### PATCH /superadmin/users/{user_public_id}/global-admin

- Summary: Set Global Admin
- operationId: `set_global_admin_superadmin_users__user_public_id__global_admin_patch`

Parameters:

| in | name | required | type | constraints |
|---|---|---|---|---|
| path | `user_public_id` | yes | string | minLength=1, maxLength=64, pattern="^[A-Za-z0-9_-]{1,64}$" |

Request body (required):

- `application/json`: `GlobalAdminUpdate`

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_UserGlobalResponse_`
- `422` Validation Error — `application/json`: `HTTPValidationError`

## Users

### GET /me

- Summary: Get Me
- operationId: `get_me_me_get`

Responses:

- `200` Successful Response — `application/json`: `object`

## Users Management

### GET /users/

- Summary: List Users
- operationId: `list_users_users__get`

Parameters:

| in | name | required | type | constraints |
|---|---|---|---|---|
| query | `include_inactive` | no | boolean | default=false |
| query | `email` | no | string \| null | maxLength=255 |
| query | `role` | no | string \| null | maxLength=50 |
| query | `q` | no | string \| null | minLength=2, maxLength=80 |
| query | `limit` | no | integer | minimum=1, maximum=500, default=200 |
| query | `offset` | no | integer | minimum=0, maximum=1000000, default=0 |

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_list_UserResponse__`
- `422` Validation Error — `application/json`: `HTTPValidationError`

### POST /users/

- Summary: Create User
- operationId: `create_user_users__post`

Request body (required):

- `application/json`: `UserCreate`

Responses:

- `201` Successful Response — `application/json`: `ApiSuccess_UserResponse_`
- `422` Validation Error — `application/json`: `HTTPValidationError`

### GET /users/{public_id}

- Summary: Get User
- operationId: `get_user_users__public_id__get`

Parameters:

| in | name | required | type | constraints |
|---|---|---|---|---|
| path | `public_id` | yes | string | minLength=1, maxLength=64, pattern="^[A-Za-z0-9_-]{1,64}$" |

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_UserResponse_`
- `422` Validation Error — `application/json`: `HTTPValidationError`

### PATCH /users/{public_id}

- Summary: Update User
- operationId: `update_user_users__public_id__patch`

Parameters:

| in | name | required | type | constraints |
|---|---|---|---|---|
| path | `public_id` | yes | string | minLength=1, maxLength=64, pattern="^[A-Za-z0-9_-]{1,64}$" |

Request body (required):

- `application/json`: `UserUpdate`

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_UserResponse_`
- `422` Validation Error — `application/json`: `HTTPValidationError`

### DELETE /users/{public_id}

- Summary: Delete User
- operationId: `delete_user_users__public_id__delete`

Parameters:

| in | name | required | type | constraints |
|---|---|---|---|---|
| path | `public_id` | yes | string | minLength=1, maxLength=64, pattern="^[A-Za-z0-9_-]{1,64}$" |

Responses:

- `204` Successful Response
- `422` Validation Error — `application/json`: `HTTPValidationError`

## Waitlist

### GET /waitlist/

- Summary: List Waitlist
- operationId: `list_waitlist_waitlist__get`

Responses:

- `200` Successful Response — `application/json`: `ApiSuccess_list_WaitlistEntryResponse__`

### DELETE /waitlist/{entry_id}

- Summary: Remove Waitlist Entry
- operationId: `remove_waitlist_entry_waitlist__entry_id__delete`

Parameters:

| in | name | required | type | constraints |
|---|---|---|---|---|
| path | `entry_id` | yes | string | minLength=1, maxLength=64, pattern="^[A-Za-z0-9_-]{1,64}$" |

Responses:

- `204` Successful Response
- `422` Validation Error — `application/json`: `HTTPValidationError`

### POST /waitlist/{entry_id}/book

- Summary: Book From Waitlist
- operationId: `book_from_waitlist_waitlist__entry_id__book_post`

Parameters:

| in | name | required | type | constraints |
|---|---|---|---|---|
| path | `entry_id` | yes | string | minLength=1, maxLength=64, pattern="^[A-Za-z0-9_-]{1,64}$" |

Request body (required):

- `application/json`: `WaitlistBookRequest`

Responses:

- `201` Successful Response — `application/json`: `ApiSuccess_AppointmentResponse_`
- `422` Validation Error — `application/json`: `HTTPValidationError`

## Schemas

### AffectedAppointmentResponse

| field | type | required | constraints |
|---|---|---|---|
| `public_id` | string | yes |  |
| `client_name` | string | yes |  |
| `client_phone` | string \| null | no |  |
| `service_name` | string | yes |  |
| `staff_name` | string | yes |  |
| `starts_at` | string | yes | format="date-time" |
| `ends_at` | string | yes | format="date-time" |
| `status` | string | yes |  |
| `blocker` | string \| null | no |  |
| `cancellable` | boolean | yes |  |

### AnonymizeResponse

| field | type | required | constraints |
|---|---|---|---|
| `status` | string | yes |  |

### ApiSuccess_AnonymizeResponse_

| field | type | required | constraints |
|---|---|---|---|
| `success` | boolean | no | default=true |
| `data` | AnonymizeResponse | yes |  |
| `meta` | object \| null | no |  |

### ApiSuccess_AppointmentBlockBatchResponse_

| field | type | required | constraints |
|---|---|---|---|
| `success` | boolean | no | default=true |
| `data` | AppointmentBlockBatchResponse | yes |  |
| `meta` | object \| null | no |  |

### ApiSuccess_AppointmentBlockResponse_

| field | type | required | constraints |
|---|---|---|---|
| `success` | boolean | no | default=true |
| `data` | AppointmentBlockResponse | yes |  |
| `meta` | object \| null | no |  |

### ApiSuccess_AppointmentResponse_

| field | type | required | constraints |
|---|---|---|---|
| `success` | boolean | no | default=true |
| `data` | AppointmentResponse | yes |  |
| `meta` | object \| null | no |  |

### ApiSuccess_AppointmentSearchResponse_

| field | type | required | constraints |
|---|---|---|---|
| `success` | boolean | no | default=true |
| `data` | AppointmentSearchResponse | yes |  |
| `meta` | object \| null | no |  |

### ApiSuccess_BlockPreviewResponse_

| field | type | required | constraints |
|---|---|---|---|
| `success` | boolean | no | default=true |
| `data` | BlockPreviewResponse | yes |  |
| `meta` | object \| null | no |  |

### ApiSuccess_ClientAppointmentsResponse_

| field | type | required | constraints |
|---|---|---|---|
| `success` | boolean | no | default=true |
| `data` | ClientAppointmentsResponse | yes |  |
| `meta` | object \| null | no |  |

### ApiSuccess_ClientDataExport_

| field | type | required | constraints |
|---|---|---|---|
| `success` | boolean | no | default=true |
| `data` | ClientDataExport | yes |  |
| `meta` | object \| null | no |  |

### ApiSuccess_CouponRedemptionResponse_

| field | type | required | constraints |
|---|---|---|---|
| `success` | boolean | no | default=true |
| `data` | CouponRedemptionResponse | yes |  |
| `meta` | object \| null | no |  |

### ApiSuccess_CouponResponse_

| field | type | required | constraints |
|---|---|---|---|
| `success` | boolean | no | default=true |
| `data` | CouponResponse | yes |  |
| `meta` | object \| null | no |  |

### ApiSuccess_CustomerLedgerResponse_

| field | type | required | constraints |
|---|---|---|---|
| `success` | boolean | no | default=true |
| `data` | CustomerLedgerResponse | yes |  |
| `meta` | object \| null | no |  |

### ApiSuccess_DashboardSummaryResponse_

| field | type | required | constraints |
|---|---|---|---|
| `success` | boolean | no | default=true |
| `data` | DashboardSummaryResponse | yes |  |
| `meta` | object \| null | no |  |

### ApiSuccess_dict_str__Any__

| field | type | required | constraints |
|---|---|---|---|
| `success` | boolean | no | default=true |
| `data` | object | yes |  |
| `meta` | object \| null | no |  |

### ApiSuccess_dict_str__object__

| field | type | required | constraints |
|---|---|---|---|
| `success` | boolean | no | default=true |
| `data` | object | yes |  |
| `meta` | object \| null | no |  |

### ApiSuccess_dict_str__str__

| field | type | required | constraints |
|---|---|---|---|
| `success` | boolean | no | default=true |
| `data` | object<string, string> | yes |  |
| `meta` | object \| null | no |  |

### ApiSuccess_ForgotPasswordResponse_

| field | type | required | constraints |
|---|---|---|---|
| `success` | boolean | no | default=true |
| `data` | ForgotPasswordResponse | yes |  |
| `meta` | object \| null | no |  |

### ApiSuccess_GatewayConfigResponse_

| field | type | required | constraints |
|---|---|---|---|
| `success` | boolean | no | default=true |
| `data` | GatewayConfigResponse | yes |  |
| `meta` | object \| null | no |  |

### ApiSuccess_LedgerMovementResponse_

| field | type | required | constraints |
|---|---|---|---|
| `success` | boolean | no | default=true |
| `data` | LedgerMovementResponse | yes |  |
| `meta` | object \| null | no |  |

### ApiSuccess_LedgerSummaryResponse_

| field | type | required | constraints |
|---|---|---|---|
| `success` | boolean | no | default=true |
| `data` | LedgerSummaryResponse | yes |  |
| `meta` | object \| null | no |  |

### ApiSuccess_LegalVersionsResponse_

| field | type | required | constraints |
|---|---|---|---|
| `success` | boolean | no | default=true |
| `data` | LegalVersionsResponse | yes |  |
| `meta` | object \| null | no |  |

### ApiSuccess_list_AppointmentBlockResponse__

| field | type | required | constraints |
|---|---|---|---|
| `success` | boolean | no | default=true |
| `data` | array<AppointmentBlockResponse> | yes |  |
| `meta` | object \| null | no |  |

### ApiSuccess_list_AppointmentListItem__

| field | type | required | constraints |
|---|---|---|---|
| `success` | boolean | no | default=true |
| `data` | array<AppointmentListItem> | yes |  |
| `meta` | object \| null | no |  |

### ApiSuccess_list_AuditLogItem__

| field | type | required | constraints |
|---|---|---|---|
| `success` | boolean | no | default=true |
| `data` | array<AuditLogItem> | yes |  |
| `meta` | object \| null | no |  |

### ApiSuccess_list_AuditLogResponse__

| field | type | required | constraints |
|---|---|---|---|
| `success` | boolean | no | default=true |
| `data` | array<AuditLogResponse> | yes |  |
| `meta` | object \| null | no |  |

### ApiSuccess_list_BlockTemplateResponse__

| field | type | required | constraints |
|---|---|---|---|
| `success` | boolean | no | default=true |
| `data` | array<BlockTemplateResponse> | yes |  |
| `meta` | object \| null | no |  |

### ApiSuccess_list_CouponRedemptionResponse__

| field | type | required | constraints |
|---|---|---|---|
| `success` | boolean | no | default=true |
| `data` | array<CouponRedemptionResponse> | yes |  |
| `meta` | object \| null | no |  |

### ApiSuccess_list_CouponResponse__

| field | type | required | constraints |
|---|---|---|---|
| `success` | boolean | no | default=true |
| `data` | array<CouponResponse> | yes |  |
| `meta` | object \| null | no |  |

### ApiSuccess_list_LedgerClientItem__

| field | type | required | constraints |
|---|---|---|---|
| `success` | boolean | no | default=true |
| `data` | array<LedgerClientItem> | yes |  |
| `meta` | object \| null | no |  |

### ApiSuccess_list_object__

| field | type | required | constraints |
|---|---|---|---|
| `success` | boolean | no | default=true |
| `data` | array<any> | yes |  |
| `meta` | object \| null | no |  |

### ApiSuccess_list_PlanResponse__

| field | type | required | constraints |
|---|---|---|---|
| `success` | boolean | no | default=true |
| `data` | array<PlanResponse> | yes |  |
| `meta` | object \| null | no |  |

### ApiSuccess_list_PromotionResponse__

| field | type | required | constraints |
|---|---|---|---|
| `success` | boolean | no | default=true |
| `data` | array<PromotionResponse> | yes |  |
| `meta` | object \| null | no |  |

### ApiSuccess_list_PublicServiceResponse__

| field | type | required | constraints |
|---|---|---|---|
| `success` | boolean | no | default=true |
| `data` | array<PublicServiceResponse> | yes |  |
| `meta` | object \| null | no |  |

### ApiSuccess_list_PublicStaffResponse__

| field | type | required | constraints |
|---|---|---|---|
| `success` | boolean | no | default=true |
| `data` | array<PublicStaffResponse> | yes |  |
| `meta` | object \| null | no |  |

### ApiSuccess_list_ServiceResponse__

| field | type | required | constraints |
|---|---|---|---|
| `success` | boolean | no | default=true |
| `data` | array<ServiceResponse> | yes |  |
| `meta` | object \| null | no |  |

### ApiSuccess_list_StaffResponse__

| field | type | required | constraints |
|---|---|---|---|
| `success` | boolean | no | default=true |
| `data` | array<StaffResponse> | yes |  |
| `meta` | object \| null | no |  |

### ApiSuccess_list_StoreTableResponse__

| field | type | required | constraints |
|---|---|---|---|
| `success` | boolean | no | default=true |
| `data` | array<StoreTableResponse> | yes |  |
| `meta` | object \| null | no |  |

### ApiSuccess_list_UserGlobalResponse__

| field | type | required | constraints |
|---|---|---|---|
| `success` | boolean | no | default=true |
| `data` | array<UserGlobalResponse> | yes |  |
| `meta` | object \| null | no |  |

### ApiSuccess_list_UserResponse__

| field | type | required | constraints |
|---|---|---|---|
| `success` | boolean | no | default=true |
| `data` | array<UserResponse> | yes |  |
| `meta` | object \| null | no |  |

### ApiSuccess_list_WaitlistEntryResponse__

| field | type | required | constraints |
|---|---|---|---|
| `success` | boolean | no | default=true |
| `data` | array<WaitlistEntryResponse> | yes |  |
| `meta` | object \| null | no |  |

### ApiSuccess_MercadoPagoOAuthStartResponse_

| field | type | required | constraints |
|---|---|---|---|
| `success` | boolean | no | default=true |
| `data` | MercadoPagoOAuthStartResponse | yes |  |
| `meta` | object \| null | no |  |

### ApiSuccess_NotificationListResponse_

| field | type | required | constraints |
|---|---|---|---|
| `success` | boolean | no | default=true |
| `data` | NotificationListResponse | yes |  |
| `meta` | object \| null | no |  |

### ApiSuccess_NotificationMarkReadResponse_

| field | type | required | constraints |
|---|---|---|---|
| `success` | boolean | no | default=true |
| `data` | NotificationMarkReadResponse | yes |  |
| `meta` | object \| null | no |  |

### ApiSuccess_OAuthDisconnectResponse_

| field | type | required | constraints |
|---|---|---|---|
| `success` | boolean | no | default=true |
| `data` | OAuthDisconnectResponse | yes |  |
| `meta` | object \| null | no |  |

### ApiSuccess_OutboxProcessResponse_

| field | type | required | constraints |
|---|---|---|---|
| `success` | boolean | no | default=true |
| `data` | OutboxProcessResponse | yes |  |
| `meta` | object \| null | no |  |

### ApiSuccess_OutboxStatsResponse_

| field | type | required | constraints |
|---|---|---|---|
| `success` | boolean | no | default=true |
| `data` | OutboxStatsResponse | yes |  |
| `meta` | object \| null | no |  |

### ApiSuccess_PaymentPreferenceResponse_

| field | type | required | constraints |
|---|---|---|---|
| `success` | boolean | no | default=true |
| `data` | PaymentPreferenceResponse | yes |  |
| `meta` | object \| null | no |  |

### ApiSuccess_PaymentResponse_

| field | type | required | constraints |
|---|---|---|---|
| `success` | boolean | no | default=true |
| `data` | PaymentResponse | yes |  |
| `meta` | object \| null | no |  |

### ApiSuccess_PlanResponse_

| field | type | required | constraints |
|---|---|---|---|
| `success` | boolean | no | default=true |
| `data` | PlanResponse | yes |  |
| `meta` | object \| null | no |  |

### ApiSuccess_ProfessionalReportsResponse_

| field | type | required | constraints |
|---|---|---|---|
| `success` | boolean | no | default=true |
| `data` | ProfessionalReportsResponse | yes |  |
| `meta` | object \| null | no |  |

### ApiSuccess_PromotionQuoteResponse_

| field | type | required | constraints |
|---|---|---|---|
| `success` | boolean | no | default=true |
| `data` | PromotionQuoteResponse | yes |  |
| `meta` | object \| null | no |  |

### ApiSuccess_PromotionResponse_

| field | type | required | constraints |
|---|---|---|---|
| `success` | boolean | no | default=true |
| `data` | PromotionResponse | yes |  |
| `meta` | object \| null | no |  |

### ApiSuccess_PublicBookingResponse_

| field | type | required | constraints |
|---|---|---|---|
| `success` | boolean | no | default=true |
| `data` | PublicBookingResponse | yes |  |
| `meta` | object \| null | no |  |

### ApiSuccess_PublicDepositPreviewResponse_

| field | type | required | constraints |
|---|---|---|---|
| `success` | boolean | no | default=true |
| `data` | PublicDepositPreviewResponse | yes |  |
| `meta` | object \| null | no |  |

### ApiSuccess_PublicPaymentStatusResponse_

| field | type | required | constraints |
|---|---|---|---|
| `success` | boolean | no | default=true |
| `data` | PublicPaymentStatusResponse | yes |  |
| `meta` | object \| null | no |  |

### ApiSuccess_PublicPromotionPreviewResponse_

| field | type | required | constraints |
|---|---|---|---|
| `success` | boolean | no | default=true |
| `data` | PublicPromotionPreviewResponse | yes |  |
| `meta` | object \| null | no |  |

### ApiSuccess_PublicStoreRefResponse_

| field | type | required | constraints |
|---|---|---|---|
| `success` | boolean | no | default=true |
| `data` | PublicStoreRefResponse | yes |  |
| `meta` | object \| null | no |  |

### ApiSuccess_PublicStoreResponse_

| field | type | required | constraints |
|---|---|---|---|
| `success` | boolean | no | default=true |
| `data` | PublicStoreResponse | yes |  |
| `meta` | object \| null | no |  |

### ApiSuccess_ReconciliationSummaryResponse_

| field | type | required | constraints |
|---|---|---|---|
| `success` | boolean | no | default=true |
| `data` | ReconciliationSummaryResponse | yes |  |
| `meta` | object \| null | no |  |

### ApiSuccess_ReportSummaryResponse_

| field | type | required | constraints |
|---|---|---|---|
| `success` | boolean | no | default=true |
| `data` | ReportSummaryResponse | yes |  |
| `meta` | object \| null | no |  |

### ApiSuccess_ReportTrendResponse_

| field | type | required | constraints |
|---|---|---|---|
| `success` | boolean | no | default=true |
| `data` | ReportTrendResponse | yes |  |
| `meta` | object \| null | no |  |

### ApiSuccess_ResetPasswordResponse_

| field | type | required | constraints |
|---|---|---|---|
| `success` | boolean | no | default=true |
| `data` | ResetPasswordResponse | yes |  |
| `meta` | object \| null | no |  |

### ApiSuccess_RevokedSessionsResult_

| field | type | required | constraints |
|---|---|---|---|
| `success` | boolean | no | default=true |
| `data` | RevokedSessionsResult | yes |  |
| `meta` | object \| null | no |  |

### ApiSuccess_ScheduleResponse_

| field | type | required | constraints |
|---|---|---|---|
| `success` | boolean | no | default=true |
| `data` | ScheduleResponse | yes |  |
| `meta` | object \| null | no |  |

### ApiSuccess_ServiceResponse_

| field | type | required | constraints |
|---|---|---|---|
| `success` | boolean | no | default=true |
| `data` | ServiceResponse | yes |  |
| `meta` | object \| null | no |  |

### ApiSuccess_SessionListResponse_

| field | type | required | constraints |
|---|---|---|---|
| `success` | boolean | no | default=true |
| `data` | SessionListResponse | yes |  |
| `meta` | object \| null | no |  |

### ApiSuccess_StaffResponse_

| field | type | required | constraints |
|---|---|---|---|
| `success` | boolean | no | default=true |
| `data` | StaffResponse | yes |  |
| `meta` | object \| null | no |  |

### ApiSuccess_StoreFeatureFlagsResponse_

| field | type | required | constraints |
|---|---|---|---|
| `success` | boolean | no | default=true |
| `data` | StoreFeatureFlagsResponse | yes |  |
| `meta` | object \| null | no |  |

### ApiSuccess_StoreGlobalResponse_

| field | type | required | constraints |
|---|---|---|---|
| `success` | boolean | no | default=true |
| `data` | StoreGlobalResponse | yes |  |
| `meta` | object \| null | no |  |

### ApiSuccess_StoreMediaUploadResponse_

| field | type | required | constraints |
|---|---|---|---|
| `success` | boolean | no | default=true |
| `data` | StoreMediaUploadResponse | yes |  |
| `meta` | object \| null | no |  |

### ApiSuccess_StoreOverviewResponse_

| field | type | required | constraints |
|---|---|---|---|
| `success` | boolean | no | default=true |
| `data` | StoreOverviewResponse | yes |  |
| `meta` | object \| null | no |  |

### ApiSuccess_StoreResponse_

| field | type | required | constraints |
|---|---|---|---|
| `success` | boolean | no | default=true |
| `data` | StoreResponse | yes |  |
| `meta` | object \| null | no |  |

### ApiSuccess_StoreSubscriptionResponse_

| field | type | required | constraints |
|---|---|---|---|
| `success` | boolean | no | default=true |
| `data` | StoreSubscriptionResponse | yes |  |
| `meta` | object \| null | no |  |

### ApiSuccess_StoreSubscriptionStatusResponse_

| field | type | required | constraints |
|---|---|---|---|
| `success` | boolean | no | default=true |
| `data` | StoreSubscriptionStatusResponse | yes |  |
| `meta` | object \| null | no |  |

### ApiSuccess_StoreTermsAcceptanceResponse_

| field | type | required | constraints |
|---|---|---|---|
| `success` | boolean | no | default=true |
| `data` | StoreTermsAcceptanceResponse | yes |  |
| `meta` | object \| null | no |  |

### ApiSuccess_StoreTermsStatusResponse_

| field | type | required | constraints |
|---|---|---|---|
| `success` | boolean | no | default=true |
| `data` | StoreTermsStatusResponse | yes |  |
| `meta` | object \| null | no |  |

### ApiSuccess_StoreWideBlockResponse_

| field | type | required | constraints |
|---|---|---|---|
| `success` | boolean | no | default=true |
| `data` | StoreWideBlockResponse | yes |  |
| `meta` | object \| null | no |  |

### ApiSuccess_TokenResponse_

| field | type | required | constraints |
|---|---|---|---|
| `success` | boolean | no | default=true |
| `data` | TokenResponse | yes |  |
| `meta` | object \| null | no |  |

### ApiSuccess_UnsubscribeResponse_

| field | type | required | constraints |
|---|---|---|---|
| `success` | boolean | no | default=true |
| `data` | UnsubscribeResponse | yes |  |
| `meta` | object \| null | no |  |

### ApiSuccess_UserGlobalResponse_

| field | type | required | constraints |
|---|---|---|---|
| `success` | boolean | no | default=true |
| `data` | UserGlobalResponse | yes |  |
| `meta` | object \| null | no |  |

### ApiSuccess_UserResponse_

| field | type | required | constraints |
|---|---|---|---|
| `success` | boolean | no | default=true |
| `data` | UserResponse | yes |  |
| `meta` | object \| null | no |  |

### ApiSuccess_WaitlistEntryResponse_

| field | type | required | constraints |
|---|---|---|---|
| `success` | boolean | no | default=true |
| `data` | WaitlistEntryResponse | yes |  |
| `meta` | object \| null | no |  |

### AppliedCouponSummary

| field | type | required | constraints |
|---|---|---|---|
| `public_id` | string | yes |  |
| `code` | string | yes |  |
| `coupon_type` | string | yes |  |
| `value` | string | yes | pattern="^(?!^[-+.]*$)[+-]?0*\\d*\\.?\\d*$" |
| `currency` | string \| null | yes |  |
| `is_active` | boolean | yes |  |

### AppointmentBlockBatchResponse

| field | type | required | constraints |
|---|---|---|---|
| `created` | integer | yes |  |
| `blocks` | array<AppointmentBlockResponse> | yes |  |

### AppointmentBlockCreate

| field | type | required | constraints |
|---|---|---|---|
| `staff_id` | string | yes | minLength=1, maxLength=64 |
| `starts_at` | string | yes | format="date-time" |
| `ends_at` | string | yes | format="date-time" |
| `reason` | string | no | maxLength=255, default="No atender" |
| `cancel_affected` | boolean | no | default=false |

### AppointmentBlockResponse

| field | type | required | constraints |
|---|---|---|---|
| `public_id` | string | yes |  |
| `staff_id` | string | yes |  |
| `starts_at` | string | yes | format="date-time" |
| `ends_at` | string | yes | format="date-time" |
| `reason` | string | yes |  |
| `is_active` | boolean | yes |  |

### AppointmentBlockUpdate

| field | type | required | constraints |
|---|---|---|---|
| `starts_at` | string \| null | no | format="date-time" |
| `ends_at` | string \| null | no | format="date-time" |
| `reason` | string \| null | no | maxLength=255 |
| `is_active` | boolean \| null | no |  |
| `cancel_affected` | boolean | no | default=false |

### AppointmentCreate

| field | type | required | constraints |
|---|---|---|---|
| `service_id` | string | yes | minLength=1, maxLength=64, pattern="^[A-Za-z0-9_-]{1,64}$" |
| `staff_id` | string \| null | no | minLength=1, maxLength=64, pattern="^[A-Za-z0-9_-]{1,64}$" |
| `starts_at` | string | yes | format="date-time" |
| `notes` | string \| null | no | maxLength=1000 |
| `idempotency_key` | string | yes | minLength=10, maxLength=128 |
| `client_name` | string \| null | no | minLength=1, maxLength=100 |
| `client_phone` | string \| null | no | minLength=6, maxLength=30 |
| `client_email` | string \| null | no | maxLength=255, format="email" |
| `allow_outside_schedule` | boolean | no | default=false |

### AppointmentListItem

| field | type | required | constraints |
|---|---|---|---|
| `public_id` | string | yes |  |
| `service_id` | string | yes |  |
| `service_name` | string | yes |  |
| `staff_id` | string | yes |  |
| `staff_name` | string | yes |  |
| `client_name` | string | yes |  |
| `client_phone` | string \| null | no |  |
| `starts_at` | string | yes | format="date-time" |
| `ends_at` | string | yes | format="date-time" |
| `status` | AppointmentStatus | yes |  |
| `notes` | string \| null | no |  |
| `notes_staff` | string \| null | no |  |
| `intake_answers` | object<string, string> | no |  |

### AppointmentNotesStaffUpdate

| field | type | required | constraints |
|---|---|---|---|
| `notes_staff` | string | yes | maxLength=1000 |

### AppointmentReschedule

| field | type | required | constraints |
|---|---|---|---|
| `new_starts_at` | string | yes | format="date-time" |
| `idempotency_key` | string | yes | minLength=10, maxLength=128 |

### AppointmentResponse

| field | type | required | constraints |
|---|---|---|---|
| `public_id` | string | yes |  |
| `service_id` | string | yes |  |
| `staff_id` | string | yes |  |
| `starts_at` | string | yes | format="date-time" |
| `ends_at` | string | yes | format="date-time" |
| `status` | AppointmentStatus | yes |  |
| `notes` | string \| null | no |  |
| `notes_staff` | string \| null | no |  |
| `intake_answers` | object<string, string> | no |  |
| `cancelled_at` | string \| null | no | format="date-time" |
| `completed_at` | string \| null | no | format="date-time" |

### AppointmentSearchResponse

| field | type | required | constraints |
|---|---|---|---|
| `total` | integer \| null | yes |  |
| `page` | integer | yes |  |
| `page_size` | integer | yes |  |
| `results` | array<AppointmentSearchResult> | yes |  |
| `next_cursor` | string \| null | no |  |

### AppointmentSearchResult

| field | type | required | constraints |
|---|---|---|---|
| `public_id` | string | yes |  |
| `starts_at` | string | yes | format="date-time" |
| `ends_at` | string | yes | format="date-time" |
| `status` | AppointmentStatus | yes |  |
| `notes` | string \| null | no |  |
| `notes_staff` | string \| null | no |  |
| `intake_answers` | object<string, string> | no |  |
| `cancelled_at` | string \| null | no | format="date-time" |
| `completed_at` | string \| null | no | format="date-time" |
| `service_name` | string | yes |  |
| `service_id` | string | yes |  |
| `staff_name` | string | yes |  |
| `staff_id` | string | yes |  |
| `client_name` | string | yes |  |
| `client_id` | string | yes |  |
| `client_phone` | string \| null | no |  |

### AppointmentStatus

Type: `enum("pending", "pending_payment", "confirmed", "cancelled", "completed", "absent", "expired")`

### AuditLogItem

| field | type | required | constraints |
|---|---|---|---|
| `id` | string | yes |  |
| `created_at` | string | yes | format="date-time" |
| `actor_email` | string \| null | yes |  |
| `resource_type` | string | yes |  |
| `resource_id` | string | yes |  |
| `action` | string | yes |  |
| `payload_before` | object \| array<any> \| string \| integer \| number \| boolean \| null | yes |  |
| `payload_after` | object \| array<any> \| string \| integer \| number \| boolean \| null | yes |  |

### AuditLogResponse

| field | type | required | constraints |
|---|---|---|---|
| `public_id` | string | yes |  |
| `created_at` | string | yes | format="date-time" |
| `actor_email` | string \| null | yes |  |
| `resource_type` | string | yes |  |
| `action` | string | yes |  |
| `payload_before` | object \| array<any> \| string \| integer \| number \| boolean \| null | yes |  |
| `payload_after` | object \| array<any> \| string \| integer \| number \| boolean \| null | yes |  |
| `context` | string \| null | yes |  |

### BlockPreviewRequest

| field | type | required | constraints |
|---|---|---|---|
| `staff_id` | string \| null | no | minLength=1, maxLength=64 |
| `starts_at` | string | yes | format="date-time" |
| `ends_at` | string | yes | format="date-time" |
| `recurrence` | string | no | pattern="^(none\|daily\|weekly)$", default="none" |
| `recurrence_until` | string \| null | no | format="date-time" |
| `max_occurrences` | integer | no | minimum=1.0, maximum=120.0, default=30 |

### BlockPreviewResponse

| field | type | required | constraints |
|---|---|---|---|
| `ranges` | integer | yes |  |
| `affected` | array<AffectedAppointmentResponse> | yes |  |

### BlockTemplateResponse

| field | type | required | constraints |
|---|---|---|---|
| `key` | string | yes |  |
| `label` | string | yes |  |
| `reason` | string | yes |  |

### Body_upload_service_image_services__public_id__image_post

| field | type | required | constraints |
|---|---|---|---|
| `file` | string | yes |  |

### Body_upload_store_media_stores_me_media_post

| field | type | required | constraints |
|---|---|---|---|
| `kind` | string | yes |  |
| `file` | string | yes |  |

### BusinessHourPeriod-Input

| field | type | required | constraints |
|---|---|---|---|
| `open` | string | yes | format="time" |
| `close` | string | yes | format="time" |

### BusinessHourPeriod-Output

| field | type | required | constraints |
|---|---|---|---|
| `open` | string | yes |  |
| `close` | string | yes |  |

### ChangePasswordRequest

| field | type | required | constraints |
|---|---|---|---|
| `current_password` | string | yes | minLength=1, maxLength=128 |
| `new_password` | string | yes | minLength=12, maxLength=128 |

### ClientAppointmentItem

| field | type | required | constraints |
|---|---|---|---|
| `public_id` | string | yes |  |
| `service_name` | string | yes |  |
| `staff_name` | string | yes |  |
| `starts_at` | string | yes | format="date-time" |
| `ends_at` | string | yes | format="date-time" |
| `status` | string | yes |  |
| `notes` | string \| null | no |  |
| `custom_fields` | object<string, string> | no |  |
| `can_cancel` | boolean | yes |  |
| `can_reschedule` | boolean | yes |  |

### ClientAppointmentsResponse

| field | type | required | constraints |
|---|---|---|---|
| `client_name` | string | yes |  |
| `client_phone` | string | yes |  |
| `appointments` | array<ClientAppointmentItem> | yes |  |

### ClientCancelRequest

| field | type | required | constraints |
|---|---|---|---|
| `phone` | string | yes | minLength=6, maxLength=30 |
| `reason` | string \| null | no | maxLength=500 |

### ClientDataExport

| field | type | required | constraints |
|---|---|---|---|
| `exported_at` | string | yes | format="date-time" |
| `store_id` | string | yes |  |
| `client` | ExportedClient | yes |  |
| `appointments` | array<ExportedAppointment> | yes |  |
| `payments` | array<ExportedPayment> | yes |  |
| `ledger` | array<ExportedLedgerMovement> | yes |  |
| `waitlist` | array<ExportedWaitlistEntry> | yes |  |
| `marketing_opted_out_at` | string \| null | no | format="date-time" |

### ClientRescheduleRequest

| field | type | required | constraints |
|---|---|---|---|
| `phone` | string | yes | minLength=6, maxLength=30 |
| `new_starts_at` | string | yes | format="date-time" |
| `idempotency_key` | string | yes | minLength=10, maxLength=128 |

### CouponCreate

| field | type | required | constraints |
|---|---|---|---|
| `code` | string | yes | minLength=3, maxLength=50 |
| `coupon_type` | enum("percent", "fixed") | yes |  |
| `value` | number \| string | yes | maximum=10000000.0, exclusiveMinimum=0.0, pattern="^(?!^[-+.]*$)[+-]?0*\\d*\\.?\\d*$" |
| `currency` | string \| null | no | minLength=3, maxLength=10 |
| `max_uses` | integer \| null | no | minimum=1.0, maximum=1000000.0 |
| `valid_from` | string \| null | no | format="date-time" |
| `valid_until` | string \| null | no | format="date-time" |
| `one_time_per_store` | boolean | no | default=true |
| `description` | string \| null | no | maxLength=2000 |

### CouponRedeemRequest

| field | type | required | constraints |
|---|---|---|---|
| `coupon_code` | string | yes | minLength=3, maxLength=50, pattern="^[A-Za-z0-9_-]+$" |

### CouponRedemptionResponse

| field | type | required | constraints |
|---|---|---|---|
| `public_id` | string | yes |  |
| `coupon_id` | string | yes |  |
| `store_id` | string | yes |  |
| `subscription_id` | string \| null | yes |  |
| `redeemed_by_id` | string \| null | yes |  |
| `code_snapshot` | string | yes |  |
| `coupon_type_snapshot` | string | yes |  |
| `value_snapshot` | string | yes | pattern="^(?!^[-+.]*$)[+-]?0*\\d*\\.?\\d*$" |
| `base_amount` | string | yes | pattern="^(?!^[-+.]*$)[+-]?0*\\d*\\.?\\d*$" |
| `discount_amount` | string | yes | pattern="^(?!^[-+.]*$)[+-]?0*\\d*\\.?\\d*$" |
| `final_amount` | string | yes | pattern="^(?!^[-+.]*$)[+-]?0*\\d*\\.?\\d*$" |
| `currency` | string | yes |  |
| `created_at` | string | yes | format="date-time" |

### CouponResponse

| field | type | required | constraints |
|---|---|---|---|
| `public_id` | string | yes |  |
| `code` | string | yes |  |
| `coupon_type` | string | yes |  |
| `value` | string | yes | pattern="^(?!^[-+.]*$)[+-]?0*\\d*\\.?\\d*$" |
| `currency` | string \| null | yes |  |
| `max_uses` | integer \| null | yes |  |
| `current_uses` | integer | yes |  |
| `valid_from` | string \| null | yes | format="date-time" |
| `valid_until` | string \| null | yes | format="date-time" |
| `one_time_per_store` | boolean | yes |  |
| `description` | string \| null | yes |  |
| `is_active` | boolean | yes |  |
| `created_at` | string | yes | format="date-time" |
| `updated_at` | string | yes | format="date-time" |

### CouponUpdate

| field | type | required | constraints |
|---|---|---|---|
| `code` | string \| null | no | minLength=3, maxLength=50 |
| `coupon_type` | enum("percent", "fixed") \| null | no |  |
| `value` | number \| string \| null | no | maximum=10000000.0, exclusiveMinimum=0.0, pattern="^(?!^[-+.]*$)[+-]?0*\\d*\\.?\\d*$" |
| `currency` | string \| null | no | minLength=3, maxLength=10 |
| `max_uses` | integer \| null | no | minimum=1.0, maximum=1000000.0 |
| `valid_from` | string \| null | no | format="date-time" |
| `valid_until` | string \| null | no | format="date-time" |
| `one_time_per_store` | boolean \| null | no |  |
| `description` | string \| null | no | maxLength=2000 |
| `is_active` | boolean \| null | no |  |

### CustomerLedgerResponse

| field | type | required | constraints |
|---|---|---|---|
| `client_id` | string | yes |  |
| `balance` | string | yes | pattern="^(?!^[-+.]*$)[+-]?0*\\d*\\.?\\d*$" |
| `total` | integer | yes |  |
| `movements` | array<LedgerMovementResponse> | yes |  |
| `next_cursor` | string \| null | no |  |

### DashboardStatSummary

| field | type | required | constraints |
|---|---|---|---|
| `appointments_today` | integer | yes |  |
| `pending_confirmations` | integer | yes |  |
| `occupancy_rate` | number | yes |  |
| `new_clients_last_30d` | integer | yes |  |
| `weekly_revenue` | number | yes |  |
| `revenue_trend` | number | yes |  |
| `average_appointment_minutes` | integer | yes |  |

### DashboardSummaryResponse

| field | type | required | constraints |
|---|---|---|---|
| `stats` | DashboardStatSummary | yes |  |
| `upcoming_appointments` | array<UpcomingAppointmentItem> | yes |  |

### ExportedAppointment

| field | type | required | constraints |
|---|---|---|---|
| `public_id` | string | yes |  |
| `starts_at` | string | yes | format="date-time" |
| `ends_at` | string | yes | format="date-time" |
| `status` | string | yes |  |
| `service_id` | string | yes |  |
| `staff_id` | string | yes |  |
| `client_name` | string | yes |  |
| `client_email` | string \| null | no |  |
| `client_phone` | string \| null | no |  |
| `notes` | string \| null | no |  |
| `notes_staff` | string \| null | no |  |
| `intake_answers` | object \| null | no |  |
| `price_amount` | string \| null | no | pattern="^(?!^[-+.]*$)[+-]?0*\\d*\\.?\\d*$" |
| `terms_accepted_at` | string \| null | no | format="date-time" |
| `terms_version` | string \| null | no |  |
| `privacy_version` | string \| null | no |  |
| `cancelled_at` | string \| null | no | format="date-time" |
| `completed_at` | string \| null | no | format="date-time" |

### ExportedClient

| field | type | required | constraints |
|---|---|---|---|
| `public_id` | string | yes |  |
| `full_name` | string | yes |  |
| `first_name` | string \| null | no |  |
| `last_name` | string \| null | no |  |
| `email` | string \| null | no |  |
| `phone` | string \| null | no |  |
| `is_active` | boolean | yes |  |
| `created_at` | string \| null | no | format="date-time" |

### ExportedLedgerMovement

| field | type | required | constraints |
|---|---|---|---|
| `public_id` | string | yes |  |
| `movement_type` | string | yes |  |
| `amount` | string | yes | pattern="^(?!^[-+.]*$)[+-]?0*\\d*\\.?\\d*$" |
| `balance_after` | string | yes | pattern="^(?!^[-+.]*$)[+-]?0*\\d*\\.?\\d*$" |
| `appointment_id` | string \| null | no |  |
| `notes` | string \| null | no |  |
| `created_at` | string \| null | no | format="date-time" |

### ExportedPayment

| field | type | required | constraints |
|---|---|---|---|
| `public_id` | string | yes |  |
| `appointment_id` | string | yes |  |
| `provider` | string | yes |  |
| `amount` | string | yes | pattern="^(?!^[-+.]*$)[+-]?0*\\d*\\.?\\d*$" |
| `currency` | string | yes |  |
| `status` | string | yes |  |
| `paid_at` | string \| null | no | format="date-time" |
| `created_at` | string \| null | no | format="date-time" |

### ExportedWaitlistEntry

| field | type | required | constraints |
|---|---|---|---|
| `public_id` | string | yes |  |
| `status` | string | yes |  |
| `service_id` | string | yes |  |
| `window_starts_at` | string | yes | format="date-time" |
| `window_ends_at` | string | yes | format="date-time" |
| `client_name` | string | yes |  |
| `client_phone` | string | yes |  |
| `client_email` | string \| null | no |  |
| `notes` | string \| null | no |  |
| `terms_accepted_at` | string \| null | no | format="date-time" |
| `terms_version` | string \| null | no |  |
| `privacy_version` | string \| null | no |  |
| `created_at` | string \| null | no | format="date-time" |

### ForgotPasswordRequest

| field | type | required | constraints |
|---|---|---|---|
| `email` | string | yes | format="email" |

### ForgotPasswordResponse

| field | type | required | constraints |
|---|---|---|---|
| `message` | string | yes |  |

### GatewayConfigResponse

| field | type | required | constraints |
|---|---|---|---|
| `provider` | string | yes |  |
| `configured` | boolean | yes |  |
| `public_key` | string \| null | no |  |
| `access_token_masked` | string \| null | no |  |
| `connection_mode` | string \| null | no |  |
| `oauth_user_id` | string \| null | no |  |
| `oauth_connected_at` | string \| null | no | format="date-time" |
| `oauth_supported` | boolean | no | default=false |

### GatewayConfigUpsert

| field | type | required | constraints |
|---|---|---|---|
| `provider` | string | no | pattern="^(mercadopago\|stripe)$", default="mercadopago" |
| `access_token` | string \| null | no | minLength=3, maxLength=500 |
| `public_key` | string \| null | no | maxLength=255 |
| `webhook_secret` | string \| null | no | maxLength=255 |

### GlobalAdminUpdate

| field | type | required | constraints |
|---|---|---|---|
| `is_global_admin` | boolean | yes |  |

### HTTPValidationError

| field | type | required | constraints |
|---|---|---|---|
| `detail` | array<ValidationError> | no |  |

### LedgerClientItem

| field | type | required | constraints |
|---|---|---|---|
| `public_id` | string | yes |  |
| `name` | string | yes |  |
| `email` | string \| null | no |  |
| `phone` | string \| null | no |  |

### LedgerMovementCreate

| field | type | required | constraints |
|---|---|---|---|
| `movement_type` | string | yes | pattern="^(charge\|payment\|adjustment\|refund)$" |
| `amount` | number \| string | yes | minimum=0.0, maximum=10000000.0, pattern="^(?!^[-+.]*$)[+-]?0*(?:\\d{0,10}\|(?=[\\d.]{1,13}0*$)\\d{0,10}\\.\\d{0,2}0*$)" |
| `appointment_id` | string \| null | no | maxLength=64, pattern="^[A-Za-z0-9_-]{1,64}$" |
| `notes` | string \| null | no | maxLength=500 |

### LedgerMovementResponse

| field | type | required | constraints |
|---|---|---|---|
| `public_id` | string | yes |  |
| `movement_type` | string | yes |  |
| `amount` | string | yes | pattern="^(?!^[-+.]*$)[+-]?0*\\d*\\.?\\d*$" |
| `balance_after` | string | yes | pattern="^(?!^[-+.]*$)[+-]?0*\\d*\\.?\\d*$" |
| `appointment_id` | string \| null | no |  |
| `notes` | string \| null | no |  |
| `created_at` | string | yes | format="date-time" |

### LedgerSummaryClientItem

| field | type | required | constraints |
|---|---|---|---|
| `client_id` | string | yes |  |
| `client_name` | string | yes |  |
| `balance` | string | yes | pattern="^(?!^[-+.]*$)[+-]?0*\\d*\\.?\\d*$" |
| `last_movement_at` | string | yes | format="date-time" |

### LedgerSummaryResponse

| field | type | required | constraints |
|---|---|---|---|
| `total_balance` | string | yes | pattern="^(?!^[-+.]*$)[+-]?0*\\d*\\.?\\d*$" |
| `debtors_count` | integer | yes |  |
| `average_balance` | string | yes | pattern="^(?!^[-+.]*$)[+-]?0*\\d*\\.?\\d*$" |
| `total_movements` | integer | yes |  |
| `top_debtors` | array<LedgerSummaryClientItem> | yes |  |

### LegalVersionsResponse

| field | type | required | constraints |
|---|---|---|---|
| `terms_version` | string | yes |  |
| `privacy_version` | string | yes |  |

### LoginRequest

| field | type | required | constraints |
|---|---|---|---|
| `email` | string | yes | format="email" |
| `password` | string | yes | minLength=1, maxLength=128 |

### LogoutRequest

| field | type | required | constraints |
|---|---|---|---|
| `refresh_token` | string \| null | no | minLength=20, maxLength=256 |

### ManualPaymentRequest

| field | type | required | constraints |
|---|---|---|---|
| `amount` | number \| string \| null | no | minimum=0.0, maximum=10000000.0, pattern="^(?!^[-+.]*$)[+-]?0*(?:\\d{0,10}\|(?=[\\d.]{1,13}0*$)\\d{0,10}\\.\\d{0,2}0*$)" |
| `notes` | string \| null | no | maxLength=500 |

### MercadoPagoOAuthStartResponse

| field | type | required | constraints |
|---|---|---|---|
| `auth_url` | string | yes |  |
| `qr_url` | string | yes |  |
| `expires_at` | string | yes | format="date-time" |

### NotificationListResponse

| field | type | required | constraints |
|---|---|---|---|
| `items` | array<NotificationResponse> | yes |  |
| `unread_count` | integer | yes |  |

### NotificationMarkReadResponse

| field | type | required | constraints |
|---|---|---|---|
| `updated` | integer | yes |  |
| `unread_count` | integer | yes |  |

### NotificationResponse

| field | type | required | constraints |
|---|---|---|---|
| `public_id` | string | yes |  |
| `type` | string | yes |  |
| `title` | string | yes |  |
| `body` | string \| null | no |  |
| `appointment_id` | string \| null | no |  |
| `read_at` | string \| null | no | format="date-time" |
| `created_at` | string | yes | format="date-time" |

### OAuthDisconnectResponse

| field | type | required | constraints |
|---|---|---|---|
| `disconnected` | boolean | yes |  |

### OtpRequestPayload

| field | type | required | constraints |
|---|---|---|---|
| `store_public_id` | string | yes | minLength=1, maxLength=64, pattern="^[A-Za-z0-9_-]{1,64}$" |
| `phone` | string | yes | minLength=6, maxLength=30 |
| `channel` | string | no | pattern="^(email\|whatsapp\|sms)$", default="email" |
| `email` | string \| null | no | maxLength=255, format="email" |

### OtpVerifyPayload

| field | type | required | constraints |
|---|---|---|---|
| `store_public_id` | string | yes | minLength=1, maxLength=64, pattern="^[A-Za-z0-9_-]{1,64}$" |
| `phone` | string | yes | minLength=6, maxLength=30 |
| `code` | string | yes | minLength=4, maxLength=8 |

### OutboxProcessResponse

| field | type | required | constraints |
|---|---|---|---|
| `processed` | integer | yes |  |
| `failed` | integer | yes |  |
| `inspected` | integer | yes |  |

### OutboxStatsResponse

| field | type | required | constraints |
|---|---|---|---|
| `pending` | integer | yes |  |
| `pending_with_error` | integer | yes |  |
| `processed` | integer | yes |  |

### PaymentPreferenceResponse

| field | type | required | constraints |
|---|---|---|---|
| `payment_public_id` | string | yes |  |
| `appointment_id` | string | yes |  |
| `amount` | string | yes | pattern="^(?!^[-+.]*$)[+-]?0*\\d*\\.?\\d*$" |
| `currency` | string | yes |  |
| `preference_id` | string \| null | yes |  |
| `payment_link` | string \| null | yes |  |
| `status` | string | yes |  |

### PaymentResponse

| field | type | required | constraints |
|---|---|---|---|
| `public_id` | string | yes |  |
| `appointment_id` | string | yes |  |
| `amount` | string | yes | pattern="^(?!^[-+.]*$)[+-]?0*\\d*\\.?\\d*$" |
| `currency` | string | yes |  |
| `status` | string | yes |  |
| `paid_at` | string \| null | no | format="date-time" |

### PlanCreate

| field | type | required | constraints |
|---|---|---|---|
| `name` | string | yes | minLength=2, maxLength=120 |
| `description` | string \| null | no | maxLength=2000 |
| `price` | number \| string | yes | minimum=0.0, maximum=10000000.0, pattern="^(?!^[-+.]*$)[+-]?0*\\d*\\.?\\d*$" |
| `currency` | string | no | minLength=3, maxLength=10, default="ARS" |
| `billing_interval` | string | no | minLength=3, maxLength=20, default="monthly" |
| `max_staff` | integer \| null | no | minimum=0.0, maximum=10000.0 |
| `max_services` | integer \| null | no | minimum=0.0, maximum=10000.0 |

### PlanResponse

| field | type | required | constraints |
|---|---|---|---|
| `name` | string | yes | minLength=2, maxLength=120 |
| `description` | string \| null | no | maxLength=2000 |
| `price` | string | yes | pattern="^(?!^[-+.]*$)[+-]?0*\\d*\\.?\\d*$" |
| `currency` | string | no | minLength=3, maxLength=10, default="ARS" |
| `billing_interval` | string | no | minLength=3, maxLength=20, default="monthly" |
| `max_staff` | integer \| null | no | minimum=0.0, maximum=10000.0 |
| `max_services` | integer \| null | no | minimum=0.0, maximum=10000.0 |
| `public_id` | string | yes |  |
| `is_active` | boolean | yes |  |
| `created_at` | string | yes | format="date-time" |
| `updated_at` | string | yes | format="date-time" |

### PlanUpdate

| field | type | required | constraints |
|---|---|---|---|
| `name` | string \| null | no | minLength=2, maxLength=120 |
| `description` | string \| null | no | maxLength=2000 |
| `price` | number \| string \| null | no | minimum=0.0, maximum=10000000.0, pattern="^(?!^[-+.]*$)[+-]?0*\\d*\\.?\\d*$" |
| `currency` | string \| null | no | minLength=3, maxLength=10 |
| `billing_interval` | string \| null | no | minLength=3, maxLength=20 |
| `max_staff` | integer \| null | no | minimum=0.0, maximum=10000.0 |
| `max_services` | integer \| null | no | minimum=0.0, maximum=10000.0 |
| `is_active` | boolean \| null | no |  |

### ProfessionalReportItem

| field | type | required | constraints |
|---|---|---|---|
| `staff_id` | string | yes |  |
| `staff_name` | string | yes |  |
| `appointments` | integer | yes |  |
| `completed_appointments` | integer | yes |  |
| `confirmed_appointments` | integer | yes |  |
| `absent_appointments` | integer | yes |  |
| `cancelled_appointments` | integer | yes |  |
| `used_minutes` | integer | yes |  |
| `used_hours` | number | yes |  |
| `available_minutes` | integer | yes |  |
| `available_hours` | number | yes |  |
| `blocked_minutes` | integer | yes |  |
| `blocked_hours` | number | yes |  |
| `occupancy_rate` | number | yes |  |
| `revenue` | number | yes |  |

### ProfessionalReportsResponse

| field | type | required | constraints |
|---|---|---|---|
| `from_date` | string | yes | format="date" |
| `to_date` | string | yes | format="date" |
| `professionals` | array<ProfessionalReportItem> | yes |  |

### PromotionCreate

| field | type | required | constraints |
|---|---|---|---|
| `code` | string | yes | minLength=3, maxLength=30, pattern="^[A-Za-z0-9_-]{3,30}$" |
| `title` | string | yes | minLength=2, maxLength=120 |
| `description` | string \| null | no | maxLength=1000 |
| `promotion_type` | string | no | pattern="^(percent\|fixed)$", default="percent" |
| `value` | number \| string | yes | maximum=10000000.0, exclusiveMinimum=0.0, pattern="^(?!^[-+.]*$)[+-]?0*(?:\\d{0,10}\|(?=[\\d.]{1,13}0*$)\\d{0,10}\\.\\d{0,2}0*$)" |
| `min_service_amount` | number \| string \| null | no | minimum=0.0, maximum=10000000.0, pattern="^(?!^[-+.]*$)[+-]?0*(?:\\d{0,10}\|(?=[\\d.]{1,13}0*$)\\d{0,10}\\.\\d{0,2}0*$)" |
| `max_uses` | integer \| null | no | maximum=1000000.0, exclusiveMinimum=0.0 |
| `valid_from` | string \| null | no | format="date-time" |
| `valid_until` | string \| null | no | format="date-time" |
| `is_active` | boolean | no | default=true |

### PromotionQuoteResponse

| field | type | required | constraints |
|---|---|---|---|
| `code` | string | yes |  |
| `title` | string | yes |  |
| `promotion_type` | string | yes |  |
| `base_amount` | string | yes | pattern="^(?!^[-+.]*$)[+-]?0*\\d*\\.?\\d*$" |
| `discount_amount` | string | yes | pattern="^(?!^[-+.]*$)[+-]?0*\\d*\\.?\\d*$" |
| `final_amount` | string | yes | pattern="^(?!^[-+.]*$)[+-]?0*\\d*\\.?\\d*$" |

### PromotionResponse

| field | type | required | constraints |
|---|---|---|---|
| `public_id` | string | yes |  |
| `code` | string | yes |  |
| `title` | string | yes |  |
| `description` | string \| null | yes |  |
| `promotion_type` | string | yes |  |
| `value` | string | yes | pattern="^(?!^[-+.]*$)[+-]?0*\\d*\\.?\\d*$" |
| `min_service_amount` | string \| null | yes | pattern="^(?!^[-+.]*$)[+-]?0*\\d*\\.?\\d*$" |
| `max_uses` | integer \| null | yes |  |
| `current_uses` | integer | yes |  |
| `valid_from` | string \| null | yes | format="date-time" |
| `valid_until` | string \| null | yes | format="date-time" |
| `is_active` | boolean | yes |  |
| `created_at` | string | yes | format="date-time" |
| `updated_at` | string | yes | format="date-time" |

### PromotionUpdate

| field | type | required | constraints |
|---|---|---|---|
| `code` | string \| null | no | minLength=3, maxLength=30, pattern="^[A-Za-z0-9_-]{3,30}$" |
| `title` | string \| null | no | minLength=2, maxLength=120 |
| `description` | string \| null | no | maxLength=1000 |
| `promotion_type` | string \| null | no | pattern="^(percent\|fixed)$" |
| `value` | number \| string \| null | no | maximum=10000000.0, exclusiveMinimum=0.0, pattern="^(?!^[-+.]*$)[+-]?0*(?:\\d{0,10}\|(?=[\\d.]{1,13}0*$)\\d{0,10}\\.\\d{0,2}0*$)" |
| `min_service_amount` | number \| string \| null | no | minimum=0.0, maximum=10000000.0, pattern="^(?!^[-+.]*$)[+-]?0*(?:\\d{0,10}\|(?=[\\d.]{1,13}0*$)\\d{0,10}\\.\\d{0,2}0*$)" |
| `max_uses` | integer \| null | no | maximum=1000000.0, exclusiveMinimum=0.0 |
| `valid_from` | string \| null | no | format="date-time" |
| `valid_until` | string \| null | no | format="date-time" |
| `is_active` | boolean \| null | no |  |

### PublicBookingCreate

| field | type | required | constraints |
|---|---|---|---|
| `store_public_id` | string \| null | no | minLength=1, maxLength=64, pattern="^[A-Za-z0-9_-]{1,64}$" |
| `service_id` | string | yes | minLength=1, maxLength=64, pattern="^[A-Za-z0-9_-]{1,64}$" |
| `staff_id` | string \| null | no | minLength=1, maxLength=64, pattern="^[A-Za-z0-9_-]{1,64}$" |
| `starts_at` | string | yes | format="date-time" |
| `notes` | string \| null | no | maxLength=500 |
| `idempotency_key` | string \| null | no | minLength=10, maxLength=128 |
| `client_name` | string | yes | minLength=1, maxLength=100 |
| `client_phone` | string | yes | minLength=6, maxLength=30 |
| `client_email` | string \| null | no | maxLength=255, format="email" |
| `custom_fields` | object<string, string> | no |  |
| `promotion_code` | string \| null | no | minLength=3, maxLength=30, pattern="^[A-Za-z0-9_-]+$" |
| `payment_method` | string | no | pattern="^(auto\|manual\|mercadopago)$", default="manual" |
| `accepts_terms` | boolean | no | default=false |
| `terms_version` | string \| null | no | minLength=1, maxLength=20, pattern="^[A-Za-z0-9._-]{1,20}$" |
| `privacy_version` | string \| null | no | minLength=1, maxLength=20, pattern="^[A-Za-z0-9._-]{1,20}$" |

### PublicBookingResponse

| field | type | required | constraints |
|---|---|---|---|
| `public_id` | string | yes |  |
| `service_id` | string | yes |  |
| `service_name` | string | yes |  |
| `staff_id` | string | yes |  |
| `staff_name` | string | yes |  |
| `starts_at` | string | yes | format="date-time" |
| `ends_at` | string | yes | format="date-time" |
| `status` | string | yes |  |
| `client_name` | string | yes |  |
| `client_phone` | string | yes |  |
| `notes` | string \| null | no |  |
| `custom_fields` | object<string, string> | no |  |
| `payment_required` | boolean | no | default=false |
| `payment_status` | string \| null | no |  |
| `payment_link` | string \| null | no |  |
| `payment_public_id` | string \| null | no |  |
| `payment_amount` | number \| null | no |  |
| `promotion_code` | string \| null | no |  |
| `service_price` | number \| null | no |  |
| `discount_amount` | number \| null | no |  |
| `final_price` | number \| null | no |  |

### PublicDepositPreviewResponse

| field | type | required | constraints |
|---|---|---|---|
| `amount` | number | yes |  |
| `base_amount` | number | yes |  |
| `extra_percent` | integer | yes |  |
| `reasons` | array<string> | no |  |
| `price` | number | yes |  |
| `payments_enabled` | boolean | yes |  |
| `online_payment_mandatory` | boolean | yes |  |

### PublicPaymentStatusResponse

| field | type | required | constraints |
|---|---|---|---|
| `payment_public_id` | string | yes |  |
| `appointment_public_id` | string | yes |  |
| `payment_status` | string | yes |  |
| `appointment_status` | string | yes |  |
| `amount` | number | yes |  |
| `currency` | string | yes |  |
| `starts_at` | string | yes | format="date-time" |

### PublicPromotionPreviewResponse

| field | type | required | constraints |
|---|---|---|---|
| `code` | string | yes |  |
| `title` | string | yes |  |
| `promotion_type` | string | yes |  |
| `base_amount` | number | yes |  |
| `discount_amount` | number | yes |  |
| `final_amount` | number | yes |  |

### PublicServiceResponse

| field | type | required | constraints |
|---|---|---|---|
| `public_id` | string | yes |  |
| `name` | string | yes |  |
| `description` | string \| null | no |  |
| `duration_minutes` | integer | yes |  |
| `price` | number | yes |  |
| `deposit_mode` | string | no | default="none" |
| `deposit_type` | string | no | default="percent" |
| `deposit_amount` | number \| null | no |  |
| `color` | string \| null | no |  |
| `image_url` | string \| null | no |  |

### PublicStaffResponse

| field | type | required | constraints |
|---|---|---|---|
| `public_id` | string | yes |  |
| `kind` | string | no | default="person" |
| `first_name` | string | yes |  |
| `last_name` | string | yes |  |
| `email` | string \| null | no |  |
| `display_name` | string | yes |  |
| `service_ids` | array<string> | no |  |

### PublicStoreRefResponse

| field | type | required | constraints |
|---|---|---|---|
| `store_public_id` | string | yes |  |
| `name` | string | yes |  |
| `accepts_new_bookings` | boolean | yes |  |

### PublicStoreResponse

| field | type | required | constraints |
|---|---|---|---|
| `public_id` | string | yes |  |
| `name` | string | yes |  |
| `slug` | string | yes |  |
| `business_type` | string | no | default="generic" |
| `logo_url` | string \| null | no |  |
| `primary_color` | string | yes |  |
| `cancellation_hours` | integer | yes |  |
| `description` | string \| null | no |  |
| `cover_url` | string \| null | no |  |
| `whatsapp_number` | string \| null | no |  |
| `website_url` | string \| null | no |  |
| `allow_manual_coordination` | boolean | no | default=true |
| `deposit_policy` | string \| null | no |  |
| `custom_client_fields` | array<StoreCustomField> | no |  |
| `feature_flags` | object<string, boolean> | no |  |

### ReconciliationSummaryResponse

| field | type | required | constraints |
|---|---|---|---|
| `pending_payments` | integer | yes |  |
| `approved_payments` | integer | yes |  |
| `rejected_payments` | integer | yes |  |
| `manual_confirmed_payments` | integer | yes |  |
| `refunded_payments` | integer | yes |  |
| `total_pending_amount` | string | yes | pattern="^(?!^[-+.]*$)[+-]?0*\\d*\\.?\\d*$" |
| `total_approved_amount` | string | yes | pattern="^(?!^[-+.]*$)[+-]?0*\\d*\\.?\\d*$" |
| `pending_webhooks` | integer | yes |  |
| `failed_webhooks` | integer | yes |  |
| `pending_outbox` | integer | yes |  |

### RecurringAppointmentBlockCreate

| field | type | required | constraints |
|---|---|---|---|
| `staff_id` | string | yes | minLength=1, maxLength=64 |
| `starts_at` | string | yes | format="date-time" |
| `ends_at` | string | yes | format="date-time" |
| `reason` | string | no | maxLength=255, default="No atender" |
| `recurrence` | string | no | pattern="^(none\|daily\|weekly)$", default="none" |
| `recurrence_until` | string \| null | no | format="date-time" |
| `max_occurrences` | integer | no | minimum=1.0, maximum=120.0, default=30 |
| `cancel_affected` | boolean | no | default=false |

### RefundRequest

| field | type | required | constraints |
|---|---|---|---|
| `amount` | number \| string \| null | no | minimum=0.0, maximum=10000000.0, pattern="^(?!^[-+.]*$)[+-]?0*(?:\\d{0,10}\|(?=[\\d.]{1,13}0*$)\\d{0,10}\\.\\d{0,2}0*$)" |
| `reason` | string \| null | no | maxLength=500 |
| `manual` | boolean | no | default=false |

### ReportAppointmentItem

| field | type | required | constraints |
|---|---|---|---|
| `public_id` | string | yes |  |
| `starts_at` | string | yes | format="date-time" |
| `ends_at` | string | yes | format="date-time" |
| `status` | string | yes |  |
| `service_name` | string | yes |  |
| `staff_name` | string | yes |  |
| `client_name` | string | yes |  |
| `service_price` | number | yes |  |

### ReportClientStats

| field | type | required | constraints |
|---|---|---|---|
| `total_clients` | integer | yes |  |
| `new_clients` | integer | yes |  |
| `returning_clients` | integer | yes |  |
| `inactive_clients` | integer | yes |  |

### ReportDebtClientItem

| field | type | required | constraints |
|---|---|---|---|
| `client_id` | string | yes |  |
| `client_name` | string | yes |  |
| `balance` | number | yes |  |

### ReportDebtSummary

| field | type | required | constraints |
|---|---|---|---|
| `outstanding_balance` | number | yes |  |
| `debtors_count` | integer | yes |  |
| `average_debt` | number | yes |  |
| `top_debtors` | array<ReportDebtClientItem> | no |  |

### ReportExportRequest

| field | type | required | constraints |
|---|---|---|---|
| `format` | enum("csv", "excel", "pdf") | yes |  |
| `from_date` | string \| null | no | format="date" |
| `to_date` | string \| null | no | format="date" |
| `filename_prefix` | string | no | minLength=3, maxLength=50, pattern="^[A-Za-z0-9_-]{3,50}$", default="reporte-turnos" |

### ReportSummaryResponse

| field | type | required | constraints |
|---|---|---|---|
| `from_date` | string | yes | format="date" |
| `to_date` | string | yes | format="date" |
| `stats` | ReportSummaryStats | yes |  |
| `client_stats` | ReportClientStats | yes |  |
| `top_services` | array<ReportTopServiceItem> | no |  |
| `top_clients` | array<ReportTopClientItem> | no |  |
| `debt_summary` | ReportDebtSummary | yes |  |
| `appointments` | array<ReportAppointmentItem> | yes |  |
| `has_more` | boolean | no | default=false |

### ReportSummaryStats

| field | type | required | constraints |
|---|---|---|---|
| `total_appointments` | integer | yes |  |
| `completed_appointments` | integer | yes |  |
| `cancelled_appointments` | integer | yes |  |
| `pending_appointments` | integer | yes |  |
| `confirmed_appointments` | integer | yes |  |
| `total_revenue` | number | yes |  |
| `average_ticket` | number | yes |  |
| `retained_deposit_revenue` | number | no | default=0.0 |
| `absent_appointments` | integer | no | default=0 |
| `expired_appointments` | integer | no | default=0 |

### ReportTopClientItem

| field | type | required | constraints |
|---|---|---|---|
| `client_id` | string | yes |  |
| `client_name` | string | yes |  |
| `appointments` | integer | yes |  |
| `completed_appointments` | integer | yes |  |
| `revenue` | number | yes |  |

### ReportTopServiceItem

| field | type | required | constraints |
|---|---|---|---|
| `service_id` | string | yes |  |
| `service_name` | string | yes |  |
| `appointments` | integer | yes |  |
| `completed_appointments` | integer | yes |  |
| `revenue` | number | yes |  |

### ReportTrendPoint

| field | type | required | constraints |
|---|---|---|---|
| `month` | string | yes |  |
| `total_appointments` | integer | yes |  |
| `completed_appointments` | integer | yes |  |
| `cancelled_appointments` | integer | yes |  |

### ReportTrendResponse

| field | type | required | constraints |
|---|---|---|---|
| `points` | array<ReportTrendPoint> | no |  |

### ResetPasswordRequest

| field | type | required | constraints |
|---|---|---|---|
| `token` | string | yes | minLength=20, maxLength=256 |
| `new_password` | string | yes | minLength=12, maxLength=128 |

### ResetPasswordResponse

| field | type | required | constraints |
|---|---|---|---|
| `message` | string | yes |  |

### RevokedSessionsResult

| field | type | required | constraints |
|---|---|---|---|
| `revoked_sessions` | integer | yes |  |

### ScheduleCreate

| field | type | required | constraints |
|---|---|---|---|
| `day_of_week` | integer | yes | minimum=0.0, maximum=6.0 |
| `start_time` | string | yes | format="time" |
| `end_time` | string | yes | format="time" |

### ScheduleResponse

| field | type | required | constraints |
|---|---|---|---|
| `day_of_week` | integer | yes | minimum=0.0, maximum=6.0 |
| `start_time` | string | yes | format="time" |
| `end_time` | string | yes | format="time" |
| `public_id` | string | yes |  |

### ScheduleUpdate

| field | type | required | constraints |
|---|---|---|---|
| `day_of_week` | integer \| null | no | minimum=0.0, maximum=6.0 |
| `start_time` | string \| null | no | format="time" |
| `end_time` | string \| null | no | format="time" |

### ServiceCreate

| field | type | required | constraints |
|---|---|---|---|
| `name` | string | yes | minLength=2, maxLength=255 |
| `description` | string \| null | no | maxLength=1000 |
| `duration_minutes` | integer | yes | maximum=480.0, exclusiveMinimum=0.0 |
| `price` | number | yes | minimum=0.0, maximum=10000000.0 |
| `deposit_mode` | string | no | pattern="^(none\|optional\|required)$", default="none" |
| `deposit_type` | string | no | pattern="^(percent\|fixed\|full)$", default="percent" |
| `deposit_amount` | number \| null | no | minimum=0.0, maximum=10000000.0 |
| `color` | string \| null | no | pattern="^#([A-Fa-f0-9]{6}\|[A-Fa-f0-9]{3})$" |
| `image_url` | string \| null | no | maxLength=500 |
| `youtube_trailer_url` | string \| null | no | maxLength=500 |

### ServiceResponse

| field | type | required | constraints |
|---|---|---|---|
| `name` | string | yes | minLength=2, maxLength=255 |
| `description` | string \| null | no | maxLength=1000 |
| `duration_minutes` | integer | yes | maximum=480.0, exclusiveMinimum=0.0 |
| `price` | number | yes | minimum=0.0, maximum=10000000.0 |
| `deposit_mode` | string | no | pattern="^(none\|optional\|required)$", default="none" |
| `deposit_type` | string | no | pattern="^(percent\|fixed\|full)$", default="percent" |
| `deposit_amount` | number \| null | no | minimum=0.0, maximum=10000000.0 |
| `color` | string \| null | no | pattern="^#([A-Fa-f0-9]{6}\|[A-Fa-f0-9]{3})$" |
| `image_url` | string \| null | no | maxLength=500 |
| `youtube_trailer_url` | string \| null | no | maxLength=500 |
| `public_id` | string | yes |  |
| `is_active` | boolean | yes |  |
| `created_at` | string | yes | format="date-time" |
| `updated_at` | string | yes | format="date-time" |

### ServiceUpdate

| field | type | required | constraints |
|---|---|---|---|
| `name` | string \| null | no | minLength=2, maxLength=255 |
| `description` | string \| null | no | maxLength=1000 |
| `duration_minutes` | integer \| null | no | maximum=480.0, exclusiveMinimum=0.0 |
| `price` | number \| null | no | minimum=0.0, maximum=10000000.0 |
| `deposit_mode` | string \| null | no | pattern="^(none\|optional\|required)$" |
| `deposit_type` | string \| null | no | pattern="^(percent\|fixed\|full)$" |
| `deposit_amount` | number \| null | no | minimum=0.0, maximum=10000000.0 |
| `color` | string \| null | no | pattern="^#([A-Fa-f0-9]{6}\|[A-Fa-f0-9]{3})$" |
| `image_url` | string \| null | no | maxLength=500 |
| `youtube_trailer_url` | string \| null | no | maxLength=500 |
| `is_active` | boolean \| null | no |  |

### SessionItem

| field | type | required | constraints |
|---|---|---|---|
| `session_id` | string | yes |  |
| `created_at` | string | yes |  |
| `expires_at` | string | yes |  |
| `user_agent` | string \| null | yes |  |
| `ip_address` | string \| null | yes |  |
| `current` | boolean | yes |  |

### SessionListResponse

| field | type | required | constraints |
|---|---|---|---|
| `sessions` | array<SessionItem> | yes |  |

### StaffCreate

| field | type | required | constraints |
|---|---|---|---|
| `display_name` | string | yes | minLength=2, maxLength=255 |
| `kind` | enum("person", "resource") | no | default="person" |
| `first_name` | string \| null | no | maxLength=100 |
| `last_name` | string \| null | no | maxLength=100 |
| `email` | string \| null | no | format="email" |
| `service_ids` | array<string> | no | maxItems=100 |

### StaffResponse

| field | type | required | constraints |
|---|---|---|---|
| `display_name` | string | yes | minLength=2, maxLength=255 |
| `public_id` | string | yes |  |
| `kind` | string | no | default="person" |
| `first_name` | string | yes |  |
| `last_name` | string | yes |  |
| `email` | string \| null | no |  |
| `is_active` | boolean | yes |  |
| `service_ids` | array<string> | no |  |
| `services` | array<ServiceResponse> | no |  |
| `schedules` | array<ScheduleResponse> | no |  |

### StaffUpdate

| field | type | required | constraints |
|---|---|---|---|
| `first_name` | string \| null | no | minLength=1, maxLength=100 |
| `last_name` | string \| null | no | minLength=1, maxLength=100 |
| `email` | string \| null | no | format="email" |
| `display_name` | string \| null | no | minLength=2, maxLength=255 |
| `service_ids` | array<string> \| null | no | maxItems=100 |
| `is_active` | boolean \| null | no |  |

### StoreAdminCreate

| field | type | required | constraints |
|---|---|---|---|
| `email` | string | yes | format="email" |
| `password` | string | yes | minLength=12, maxLength=128 |
| `first_name` | string | yes | minLength=1, maxLength=100 |
| `last_name` | string | yes | minLength=1, maxLength=100 |
| `phone` | string \| null | no | maxLength=50 |

### StoreCreate

| field | type | required | constraints |
|---|---|---|---|
| `name` | string | yes | minLength=2, maxLength=255 |
| `slug` | string | yes | minLength=2, maxLength=100, pattern="^[a-z0-9][a-z0-9-]{0,98}[a-z0-9]$" |
| `logo_url` | string \| null | no | maxLength=500 |
| `primary_color` | string | no | pattern="^#([A-Fa-f0-9]{6}\|[A-Fa-f0-9]{3})$", default="#000000" |
| `cancellation_hours` | integer | no | minimum=0.0, maximum=8760.0, default=24 |
| `buffer_minutes` | integer | no | minimum=0.0, maximum=1440.0, default=0 |
| `send_email_confirmation` | boolean | no | default=true |
| `send_email_reminders` | boolean | no | default=true |

### StoreCustomField

| field | type | required | constraints |
|---|---|---|---|
| `key` | string | yes | minLength=2, maxLength=40, pattern="^[a-z][a-z0-9_]{1,39}$" |
| `label` | string | yes | minLength=1, maxLength=80 |
| `type` | enum("text", "textarea", "tel", "email", "date", "select") | no | default="text" |
| `required` | boolean | no | default=false |
| `placeholder` | string \| null | no | maxLength=120 |
| `help_text` | string \| null | no | maxLength=200 |
| `options` | array<StoreCustomFieldOption> | no | maxItems=12 |

### StoreCustomFieldOption

| field | type | required | constraints |
|---|---|---|---|
| `label` | string | yes | minLength=1, maxLength=80 |
| `value` | string | yes | minLength=1, maxLength=80 |

### StoreFeatureFlags

| field | type | required | constraints |
|---|---|---|---|
| `payments` | boolean | no | default=false |
| `ledger` | boolean | no | default=false |
| `advanced_reports` | boolean | no | default=false |
| `new_calendar` | boolean | no | default=false |
| `otp_booking` | boolean | no | default=false |

### StoreFeatureFlagsResponse

| field | type | required | constraints |
|---|---|---|---|
| `flags` | StoreFeatureFlags | yes |  |

### StoreFeatureFlagsUpdate

| field | type | required | constraints |
|---|---|---|---|
| `payments` | boolean \| null | no |  |
| `ledger` | boolean \| null | no |  |
| `advanced_reports` | boolean \| null | no |  |
| `new_calendar` | boolean \| null | no |  |
| `otp_booking` | boolean \| null | no |  |

### StoreGlobalResponse

| field | type | required | constraints |
|---|---|---|---|
| `public_id` | string | yes |  |
| `name` | string | yes |  |
| `slug` | string | yes |  |
| `logo_url` | string \| null | yes |  |
| `primary_color` | string | yes |  |
| `cancellation_hours` | integer | yes |  |
| `buffer_minutes` | integer | yes |  |
| `send_email_confirmation` | boolean | yes |  |
| `send_email_reminders` | boolean | yes |  |
| `is_active` | boolean | yes |  |
| `created_at` | string | yes | format="date-time" |
| `updated_at` | string | yes | format="date-time" |

### StoreGlobalUpdate

| field | type | required | constraints |
|---|---|---|---|
| `name` | string \| null | no | minLength=2, maxLength=255 |
| `slug` | string \| null | no | minLength=2, maxLength=100, pattern="^[a-z0-9][a-z0-9-]{0,98}[a-z0-9]$" |
| `logo_url` | string \| null | no | maxLength=500 |
| `primary_color` | string \| null | no | pattern="^#([A-Fa-f0-9]{6}\|[A-Fa-f0-9]{3})$" |
| `cancellation_hours` | integer \| null | no | minimum=0.0, maximum=8760.0 |
| `buffer_minutes` | integer \| null | no | minimum=0.0, maximum=1440.0 |
| `send_email_confirmation` | boolean \| null | no |  |
| `send_email_reminders` | boolean \| null | no |  |
| `is_active` | boolean \| null | no |  |

### StoreMediaUploadResponse

| field | type | required | constraints |
|---|---|---|---|
| `url` | string | yes |  |
| `media_id` | string | yes |  |
| `kind` | string | yes |  |

### StoreOverviewResponse

| field | type | required | constraints |
|---|---|---|---|
| `store` | StoreGlobalResponse | yes |  |
| `users` | StoreUsersOverviewResponse | yes |  |
| `subscription` | StoreSubscriptionOverviewResponse \| null | yes |  |
| `recent_redemptions` | array<CouponRedemptionResponse> | yes |  |

### StoreResponse

| field | type | required | constraints |
|---|---|---|---|
| `public_id` | string | yes |  |
| `name` | string | yes |  |
| `slug` | string | yes |  |
| `business_type` | enum("generic", "beauty", "medical", "wellness", "professional_services") | no | default="generic" |
| `logo_url` | string \| null | yes |  |
| `primary_color` | string | yes |  |
| `cover_url` | string \| null | no |  |
| `description` | string \| null | no |  |
| `whatsapp_number` | string \| null | no |  |
| `instagram_url` | string \| null | no |  |
| `facebook_url` | string \| null | no |  |
| `website_url` | string \| null | no |  |
| `custom_client_fields` | array<StoreCustomField> | no |  |
| `cancellation_hours` | integer | yes |  |
| `min_booking_notice_hours` | integer | no | default=2 |
| `buffer_minutes` | integer | yes |  |
| `allow_manual_coordination` | boolean | no | default=true |
| `deposit_policy` | string \| null | no |  |
| `deposit_far_notice_days` | integer | no | default=0 |
| `deposit_far_notice_extra_percent` | integer | no | default=0 |
| `deposit_new_client_extra_percent` | integer | no | default=0 |
| `deposit_absent_client_extra_percent` | integer | no | default=0 |
| `business_hours` | object<string, array<BusinessHourPeriod-Output>> | yes |  |
| `send_email_confirmation` | boolean | yes |  |
| `send_email_reminders` | boolean | yes |  |
| `feature_flags` | StoreFeatureFlags | yes |  |

### StoreSubscriptionCreate

| field | type | required | constraints |
|---|---|---|---|
| `plan_id` | string | yes | minLength=1, maxLength=64, pattern="^[A-Za-z0-9_-]{1,64}$" |
| `status` | enum("active", "past_due", "suspended", "cancelled") | no | default="active" |
| `base_amount` | number \| string \| null | no | minimum=0.0, maximum=10000000.0, pattern="^(?!^[-+.]*$)[+-]?0*\\d*\\.?\\d*$" |
| `currency` | string \| null | no | minLength=3, maxLength=10 |
| `current_period_start` | string \| null | no | format="date-time" |
| `current_period_end` | string \| null | no | format="date-time" |

### StoreSubscriptionOverviewResponse

| field | type | required | constraints |
|---|---|---|---|
| `public_id` | string | yes |  |
| `store_id` | string | yes |  |
| `plan_id` | string | yes |  |
| `plan_name` | string \| null | no |  |
| `status` | string | yes |  |
| `base_amount` | string | yes | pattern="^(?!^[-+.]*$)[+-]?0*\\d*\\.?\\d*$" |
| `discount_amount` | string | yes | pattern="^(?!^[-+.]*$)[+-]?0*\\d*\\.?\\d*$" |
| `total_amount` | string | yes | pattern="^(?!^[-+.]*$)[+-]?0*\\d*\\.?\\d*$" |
| `currency` | string | yes |  |
| `current_period_start` | string \| null | yes | format="date-time" |
| `current_period_end` | string \| null | yes | format="date-time" |
| `coupon_id` | string \| null | yes |  |
| `is_active` | boolean | yes |  |
| `created_at` | string | yes | format="date-time" |
| `updated_at` | string | yes | format="date-time" |
| `billing_interval` | string \| null | no |  |
| `max_staff` | integer \| null | no |  |
| `max_services` | integer \| null | no |  |
| `applied_coupon` | AppliedCouponSummary \| null | no |  |

### StoreSubscriptionResponse

| field | type | required | constraints |
|---|---|---|---|
| `public_id` | string | yes |  |
| `store_id` | string | yes |  |
| `plan_id` | string | yes |  |
| `plan_name` | string \| null | no |  |
| `status` | string | yes |  |
| `base_amount` | string | yes | pattern="^(?!^[-+.]*$)[+-]?0*\\d*\\.?\\d*$" |
| `discount_amount` | string | yes | pattern="^(?!^[-+.]*$)[+-]?0*\\d*\\.?\\d*$" |
| `total_amount` | string | yes | pattern="^(?!^[-+.]*$)[+-]?0*\\d*\\.?\\d*$" |
| `currency` | string | yes |  |
| `current_period_start` | string \| null | yes | format="date-time" |
| `current_period_end` | string \| null | yes | format="date-time" |
| `coupon_id` | string \| null | yes |  |
| `is_active` | boolean | yes |  |
| `created_at` | string | yes | format="date-time" |
| `updated_at` | string | yes | format="date-time" |

### StoreSubscriptionStatusResponse

| field | type | required | constraints |
|---|---|---|---|
| `status` | string | yes |  |
| `plan_name` | string \| null | no |  |
| `current_period_end` | string \| null | no | format="date-time" |
| `days_left` | integer \| null | no |  |
| `grace_until` | string \| null | no | format="date" |
| `warn` | boolean | no | default=false |
| `blocks_writes` | boolean | no | default=false |

### StoreTableResponse

| field | type | required | constraints |
|---|---|---|---|
| `public_id` | string | yes |  |
| `name` | string | yes |  |
| `slug` | string | yes |  |
| `logo_url` | string \| null | yes |  |
| `primary_color` | string | yes |  |
| `cancellation_hours` | integer | yes |  |
| `buffer_minutes` | integer | yes |  |
| `send_email_confirmation` | boolean | yes |  |
| `send_email_reminders` | boolean | yes |  |
| `is_active` | boolean | yes |  |
| `created_at` | string | yes | format="date-time" |
| `updated_at` | string | yes | format="date-time" |
| `admins_count` | integer | yes |  |
| `users_count` | integer | yes |  |
| `active_users_count` | integer | yes |  |
| `has_subscription` | boolean | yes |  |
| `subscription_status` | string \| null | yes |  |
| `current_plan_name` | string \| null | yes |  |
| `current_period_end` | string \| null | yes | format="date-time" |
| `last_redemption_at` | string \| null | yes | format="date-time" |

### StoreTermsAcceptanceResponse

| field | type | required | constraints |
|---|---|---|---|
| `terms_version` | string | yes |  |
| `accepted_at` | string | yes | format="date-time" |
| `accepted_by` | string | yes |  |

### StoreTermsStatusResponse

| field | type | required | constraints |
|---|---|---|---|
| `current_version` | string | yes |  |
| `current_version_accepted` | boolean | yes |  |
| `latest` | StoreTermsAcceptanceResponse \| null | no |  |

### StoreUpdate

| field | type | required | constraints |
|---|---|---|---|
| `name` | string \| null | no | maxLength=255 |
| `slug` | string \| null | no | maxLength=100, pattern="^[a-z0-9][a-z0-9-]{0,98}[a-z0-9]$" |
| `business_type` | enum("generic", "beauty", "medical", "wellness", "professional_services") \| null | no |  |
| `logo_url` | string \| null | no | maxLength=500 |
| `primary_color` | string \| null | no | pattern="^#([A-Fa-f0-9]{6}\|[A-Fa-f0-9]{3})$" |
| `cover_url` | string \| null | no | maxLength=500 |
| `description` | string \| null | no | maxLength=2000 |
| `whatsapp_number` | string \| null | no | maxLength=50 |
| `instagram_url` | string \| null | no | maxLength=500 |
| `facebook_url` | string \| null | no | maxLength=500 |
| `website_url` | string \| null | no | maxLength=500 |
| `custom_client_fields` | array<StoreCustomField> \| null | no | maxItems=8 |
| `cancellation_hours` | integer \| null | no | minimum=0.0, maximum=8760.0 |
| `min_booking_notice_hours` | integer \| null | no | minimum=0.0, maximum=168.0 |
| `buffer_minutes` | integer \| null | no | minimum=0.0, maximum=1440.0 |
| `allow_manual_coordination` | boolean \| null | no |  |
| `deposit_policy` | string \| null | no | maxLength=2000 |
| `deposit_far_notice_days` | integer \| null | no | minimum=0.0, maximum=365.0 |
| `deposit_far_notice_extra_percent` | integer \| null | no | minimum=0.0, maximum=100.0 |
| `deposit_new_client_extra_percent` | integer \| null | no | minimum=0.0, maximum=100.0 |
| `deposit_absent_client_extra_percent` | integer \| null | no | minimum=0.0, maximum=100.0 |
| `business_hours` | object<string, array<BusinessHourPeriod-Input>> \| null | no |  |
| `send_email_confirmation` | boolean \| null | no |  |
| `send_email_reminders` | boolean \| null | no |  |

### StoreUsersOverviewResponse

| field | type | required | constraints |
|---|---|---|---|
| `admins` | array<UserGlobalResponse> | yes |  |
| `users` | array<UserGlobalResponse> | yes |  |
| `admins_count` | integer | yes |  |
| `users_count` | integer | yes |  |
| `active_users_count` | integer | yes |  |

### StoreWideBlockCreate

| field | type | required | constraints |
|---|---|---|---|
| `starts_at` | string | yes | format="date-time" |
| `ends_at` | string | yes | format="date-time" |
| `reason` | string | no | maxLength=255, default="Cerrado" |
| `cancel_affected` | boolean | no | default=false |

### StoreWideBlockResponse

| field | type | required | constraints |
|---|---|---|---|
| `blocked_staff` | integer | yes |  |
| `starts_at` | string | yes | format="date-time" |
| `ends_at` | string | yes | format="date-time" |
| `reason` | string | yes |  |

### TokenResponse

| field | type | required | constraints |
|---|---|---|---|
| `access_token` | string | yes |  |
| `token_type` | string | no | default="bearer" |

### UnsubscribeRequest

| field | type | required | constraints |
|---|---|---|---|
| `token` | string | yes | minLength=1, maxLength=256 |

### UnsubscribeResponse

| field | type | required | constraints |
|---|---|---|---|
| `status` | string | yes |  |

### UpcomingAppointmentItem

| field | type | required | constraints |
|---|---|---|---|
| `public_id` | string | yes |  |
| `starts_at` | string | yes | format="date-time" |
| `status` | string | yes |  |
| `service_name` | string | yes |  |
| `staff_name` | string | yes |  |
| `client_name` | string | yes |  |

### UserCreate

| field | type | required | constraints |
|---|---|---|---|
| `email` | string | yes | format="email" |
| `first_name` | string \| null | no | minLength=1, maxLength=100 |
| `last_name` | string \| null | no | minLength=1, maxLength=100 |
| `phone` | string \| null | no | maxLength=50 |
| `role` | UserRole | no | default="staff" |
| `password` | string | yes | minLength=12, maxLength=128 |

### UserGlobalResponse

| field | type | required | constraints |
|---|---|---|---|
| `public_id` | string | yes |  |
| `email` | string | yes | format="email" |
| `first_name` | string \| null | yes |  |
| `last_name` | string \| null | yes |  |
| `phone` | string \| null | yes |  |
| `role` | string | yes |  |
| `store_id` | string | yes |  |
| `is_active` | boolean | yes |  |
| `is_global_admin` | boolean | yes |  |
| `created_at` | string | yes | format="date-time" |
| `updated_at` | string | yes | format="date-time" |

### UserGlobalUpdate

| field | type | required | constraints |
|---|---|---|---|
| `first_name` | string \| null | no | minLength=1, maxLength=100 |
| `last_name` | string \| null | no | minLength=1, maxLength=100 |
| `phone` | string \| null | no | maxLength=50 |
| `role` | UserRole \| null | no |  |
| `password` | string \| null | no | minLength=12, maxLength=128 |
| `is_active` | boolean \| null | no |  |

### UserResponse

| field | type | required | constraints |
|---|---|---|---|
| `email` | string | yes | format="email" |
| `first_name` | string \| null | no | minLength=1, maxLength=100 |
| `last_name` | string \| null | no | minLength=1, maxLength=100 |
| `phone` | string \| null | no | maxLength=50 |
| `role` | UserRole | no | default="staff" |
| `public_id` | string | yes |  |
| `is_active` | boolean | yes |  |
| `is_global_admin` | boolean | no | default=false |
| `created_at` | string | yes | format="date-time" |
| `updated_at` | string | yes | format="date-time" |

### UserRole

Type: `enum("admin", "staff", "receptionist", "client")`

### UserUpdate

| field | type | required | constraints |
|---|---|---|---|
| `first_name` | string \| null | no | minLength=1, maxLength=100 |
| `last_name` | string \| null | no | minLength=1, maxLength=100 |
| `phone` | string \| null | no | maxLength=50 |
| `role` | UserRole \| null | no |  |
| `password` | string \| null | no | minLength=12, maxLength=128 |
| `is_active` | boolean \| null | no |  |

### ValidationError

| field | type | required | constraints |
|---|---|---|---|
| `loc` | array<string \| integer> | yes |  |
| `msg` | string | yes |  |
| `type` | string | yes |  |
| `input` | any | no |  |
| `ctx` | object | no |  |

### WaitlistBookRequest

| field | type | required | constraints |
|---|---|---|---|
| `starts_at` | string | yes | format="date-time" |
| `staff_id` | string \| null | no | maxLength=64, pattern="^[A-Za-z0-9_-]{1,64}$" |

### WaitlistClientQuery

| field | type | required | constraints |
|---|---|---|---|
| `store_public_id` | string | yes | minLength=1, maxLength=64, pattern="^[A-Za-z0-9_-]{1,64}$" |
| `phone` | string | yes | minLength=6, maxLength=30 |

### WaitlistEntryResponse

| field | type | required | constraints |
|---|---|---|---|
| `public_id` | string | yes |  |
| `status` | string | yes |  |
| `service_id` | string | yes |  |
| `service_name` | string | yes |  |
| `staff_id` | string \| null | yes |  |
| `staff_name` | string \| null | yes |  |
| `window_starts_at` | string | yes | format="date-time" |
| `window_ends_at` | string | yes | format="date-time" |
| `client_name` | string | yes |  |
| `client_phone` | string \| null | no |  |
| `client_email` | string \| null | no |  |
| `notes` | string \| null | no |  |
| `notified_at` | string \| null | no | format="date-time" |
| `offer_expires_at` | string \| null | no | format="date-time" |
| `offered_starts_at` | string \| null | no | format="date-time" |
| `offered_staff_id` | string \| null | no |  |
| `created_at` | string | yes | format="date-time" |

### WaitlistJoinRequest

| field | type | required | constraints |
|---|---|---|---|
| `store_public_id` | string | yes | minLength=1, maxLength=64, pattern="^[A-Za-z0-9_-]{1,64}$" |
| `service_id` | string | yes | minLength=1, maxLength=64, pattern="^[A-Za-z0-9_-]{1,64}$" |
| `staff_id` | string \| null | no | maxLength=64, pattern="^[A-Za-z0-9_-]{1,64}$" |
| `window_starts_at` | string | yes | format="date-time" |
| `window_ends_at` | string | yes | format="date-time" |
| `client_name` | string | yes | minLength=1, maxLength=100 |
| `client_phone` | string | yes | minLength=6, maxLength=30 |
| `client_email` | string \| null | no | maxLength=255, format="email" |
| `notes` | string \| null | no | maxLength=300 |
| `accepts_terms` | boolean \| null | no |  |
| `terms_version` | string \| null | no | minLength=1, maxLength=20, pattern="^[A-Za-z0-9._-]{1,20}$" |
| `privacy_version` | string \| null | no | minLength=1, maxLength=20, pattern="^[A-Za-z0-9._-]{1,20}$" |

Generado desde app.openapi() el 2026-09-25, commit 7448c6f
