# Shifty External API Client Integration Guide

This document defines the public contract, response wrapping conventions, authentication procedures, and idempotency rules for integrating external clients with the Shifty platform.

---

## 1. Headers & Protocol

All external API interactions must use standard HTTP/1.1 or HTTP/2 over TLS. The following headers are supported:

| Header | Required | Description |
|---|---|---|
| `Content-Type` | Yes (for writes) | Must be `application/json`. |
| `Authorization` | Yes (protected) | Bearer token format: `Bearer <jwt_token>`. |
| `x-raw-response` | Optional | Set to `true` to bypass the canonical `ApiSuccess` wrapper envelope and receive the raw resource JSON structure. |
| `X-Idempotency-Key` | Optional | Client-generated UUID to safeguard webhook ingestion or critical mutations at the transport level. |

---

## 2. Authentication & Authorization Flow

Protected endpoints require a JSON Web Token (JWT) passed in the `Authorization` header.

### Authenticating a Client
1. Submit credentials to the login endpoint:
   ```http
   POST /auth/login
   Content-Type: application/json

   {
     "email": "user@example.com",
     "password": "secure_password"
   }
   ```
2. The response will contain the access token:
   ```json
   {
     "success": true,
     "data": {
       "access_token": "eyJhbGciOi...",
       "token_type": "bearer"
     }
   }
   ```
3. Use this token in subsequent headers:
   ```http
   Authorization: Bearer eyJhbGciOi...
   ```

---

## 3. API Response Formats

Shifty uses a canonical envelope format for all responses by default, ensuring predictability across endpoints.

### 3.1. Success Response Envelope (Default)
Successful requests (status codes `2xx`) return the payload wrapped in an `ApiSuccess` envelope:
```json
{
  "success": true,
  "data": {
    "public_id": "01HXXXXXX...",
    "name": "Corte de Cabello",
    "duration_minutes": 30,
    "price": 12500.00
  },
  "meta": {
    "timestamp": "2026-06-08T01:00:00Z"
  }
}
```
*   `success`: Always `true`.
*   `data`: The actual payload model (object, list, or primitive).
*   `meta`: Optional operational metadata (such as pagination parameters).

### 3.2. Raw Response Mode (`x-raw-response: true`)
If your client integration does not support unwrapping envelopes, pass `x-raw-response: true` in the request headers. The API will strip the envelope and return the raw model structure directly:
```json
{
  "public_id": "01HXXXXXX...",
  "name": "Corte de Cabello",
  "duration_minutes": 30,
  "price": 12500.00
}
```

### 3.3. Error Response Envelope
Unsuccessful requests (status codes `4xx` and `5xx`) return a structured `ApiError` envelope. Error payloads are **never** affected by the `x-raw-response` header.
```json
{
  "success": false,
  "error_code": "APPOINTMENT_CONFLICT",
  "message": "El profesional ya tiene un turno de 14:00 a 14:30.",
  "detail": {
    "conflict_start": "2026-06-08T14:00:00Z",
    "conflict_end": "2026-06-08T14:30:00Z",
    "suggestion": "2026-06-08T14:30:00Z"
  }
}
```
*   `success`: Always `false`.
*   `error_code`: A unique machine-readable string identifying the error category.
*   `message`: A user-friendly error description.
*   `detail`: Optional dictionary containing field-level validations or context parameters.

---

## 4. Error Code Catalog

Integrators should match against `error_code` strings to customize user experiences or execute self-healing retry flows.

| Error Code | HTTP Status | Description |
|---|---|---|
| `AUTHENTICATION_FAILED` | 401 Unauthorized | Credentials are invalid, or the authentication token is missing or malformed. |
| `INVALID_TOKEN` | 400 Bad Request | The provided JWT token has expired or is invalid. |
| `PERMISSION_DENIED` | 403 Forbidden | The user lacks permissions to execute the action on the target tenant. |
| `FEATURE_DISABLED` | 403 Forbidden | The requested feature is not enabled for the store. |
| `REGISTRATION_DISABLED` | 403 Forbidden | Tenant self-registration is closed or disabled on this server. |
| `RESOURCE_NOT_FOUND` | 404 Not Found | A general resource (such as service or staff) could not be located. |
| `STORE_NOT_FOUND` | 404 Not Found | The referenced store does not exist. |
| `USER_NOT_FOUND` | 404 Not Found | The referenced user does not exist. |
| `SERVICE_NOT_FOUND` | 404 Not Found | The referenced service does not exist. |
| `STAFF_NOT_FOUND` | 404 Not Found | The referenced professional (staff member) does not exist. |
| `APPOINTMENT_NOT_FOUND` | 404 Not Found | The requested booking/appointment could not be found. |
| `BOOKING_NOTICE_REQUIRED`| 400 Bad Request | The booking was requested too close to the start time (violates tenant buffer rules). |
| `APPOINTMENT_CONFLICT` | 409 Conflict | The selected slot is already booked. Check `detail.suggestion` for alternatives. |
| `SCHEDULE_BLOCKED` | 409 Conflict | The professional or store agenda is blocked for the requested time frame. |
| `IDEMPOTENCY_IN_PROGRESS` | 409 Conflict | A request with the same idempotency key is currently executing. |
| `DUPLICATE_ACCOUNT` | 409 Conflict | An account with the same email or phone number already exists. |
| `INVALID_STATUS_TRANSITION` | 422 Unprocessable Entity | Transitioning the booking state is illegal (e.g., trying to cancel an already completed booking). |
| `VALIDATION_ERROR` | 422 Unprocessable Entity | The payload format is incorrect or business constraints were violated. |
| `OTP_INVALID` | 400 Bad Request | The OTP verification code is incorrect or expired. |
| `OTP_RATE_LIMITED` | 429 Too Many Requests | Too many OTP attempts. The client must wait before retrying. |
| `RATE_LIMITED` | 429 Too Many Requests | Request rate limit exceeded. |
| `PAYMENT_ERROR` | 400 Bad Request | A gateway payment preference or capture error occurred. |
| `WEBHOOK_ERROR` | 400 Bad Request | An external webhook signature or payload parsing verification failed. |

---

## 5. Idempotency Policies

To prevent accidental double charges or double bookings during network failures, Shifty provides strict idempotency checks at two distinct layers.

### 5.1. Client Mutation Idempotency (Payload level)
For state-modifying requests (e.g., booking slots, rescheduling), clients must supply an `idempotency_key` field (min 10, max 128 characters) in the JSON payload body.

*   **First Attempt**: The server locks the key, processes the request, saves the response status, and caches the result.
*   **Simultaneous Duplicate Request**: If a second request arrives while the first is still processing, the server immediately returns `409 Conflict` with `IDEMPOTENCY_IN_PROGRESS`.
*   **Subsequent Retries**: Once processing completes, any subsequent request with the same key returns the cached successful response directly, bypassing re-execution.
*   **Errors / Rollbacks**: If the execution fails (raises an exception), the lock is released, allowing the client to safely retry.

### 5.2. Payment Webhook Ingestion Idempotency
Payment webhook endpoints (e.g., MercadoPago webhook) validate signatures and verify events automatically against the `WebhookInbox` database table.

*   Duplicates are ignored, returning `{"success": true, "status": "already_processed"}`.
*   Failed webhook attempts (e.g., network timeout during handler execution) are stored without a `processed_at` timestamp. This allows retries to execute successfully on subsequent attempts.

---

## 6. Identifier Policy (`public_id` vs `id`)

*   **Exclusion of Database Keys**: Internal database autoincrement integer IDs or UUIDs are strictly private implementation details.
*   **Consistency**: Clients must only consume, store, and transmit ULID string identifiers via the `public_id` field.
*   **Alignment**: For components (like stores and services) that contain both `id` and `public_id` columns for database structural mapping, both fields are synchronized to use the exact same ULID string upon creation.
