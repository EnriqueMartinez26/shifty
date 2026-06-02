# Shifty - System Architecture & Components

This document provides a detailed overview of the Shifty system architecture, designed for developers and RAG systems to understand the internal workings and module relationships.

## 🏗️ Core Architecture: Multi-Tenancy, Overlap Detection, and Row-Level Security (RLS)

Shifty implements a strict multi-tenant isolation strategy at the database level using PostgreSQL RLS. All critical operations are designed to be **idempotent** to ensure reliability.

### Idempotent Operations
The system ensures **idempotent** request handling using `X-Idempotency-Key` headers. If a request is retried with the same idempotency key, the same result is returned without duplicating operations.

### Overlap and Conflict Detection
The system uses **overlap detection** to prevent scheduling conflicts. When a new appointment is requested, the system checks for any overlapping time slots with existing confirmed appointments for the same staff member.

- **Isolation Logic**: Instead of filtering by `store_id` in every SQL query, the database enforces the filter.
- **Conflict Detection**: Validates no time overlaps with confirmed appointments
- **Context Handling**: 
    1. `TenantMiddleware` extracts `store_id` from the JWT token.
    2. The database session (managed in `core/database.py`) sets a local variable: `SELECT set_config('app.current_store_id', :sid, true)`.
    3. PostgreSQL policies automatically restrict access to rows where `store_id = current_setting('app.current_store_id')`.

## 📦 Modules Overview

The backend is modularized to ensure separation of concerns:

| Module | Description | Key Responsibilities |
|--------|-------------|----------------------|
| **Auth** | Authentication & Security | JWT issuance, password hashing, password recovery. |
| **Appointments** | Turn Management | Scheduling, status tracking (confirmed, cancelled, completed), conflicts validation. |
| **Staff** | Professional Management | Availability, specific services assigned to staff. |
| **Services** | Catalog Management | Services offered by the store, prices, and durations. |
| **Stores** | Tenant Configuration | Store branding (colors), metadata, and global settings. |
| **Users** | Account Management | CRUD for administrative users and roles. |
| **Reports** | Analytics | Income summaries, appointment statistics, CSV/Excel/PDF exports. |
| **Budget** | Improvement Planning | Tracking estimated hours and costs for system improvements. |
| **Public** | Booking Portal | Publicly accessible endpoints for clients to book turns. |
| **Notifications** | Event System | Async event listeners for sending alerts (email/SMS). |

## 🛠️ Technical Details

- **Framework**: FastAPI (Asynchronous)
- **ORM**: SQLAlchemy 2.0 (Async)
- **Cache/Idempotency**: Redis (using Memurai on Windows)
- **Migrations**: Alembic (using a specialized `run_migrations.py` to handle Windows-specific asyncpg issues).

## 🚀 Key Endpoints

- `POST /auth/login`: Identity provider.
- `GET /appointments`: Dashboard calendar feed (filtered by RLS).
- `POST /appointments`: Booking creation with idempotency check.
- `GET /booking/{slug}`: Public endpoint for specific store configurations.
- `GET /reports/summary`: Financial and operational metrics.

---

## 🎯 Design Patterns

### 1. Idempotence (Idempotencia)

**Problem**: Network timeouts can cause users to retry booking requests, potentially creating duplicate appointments.

**Solution**: Idempotent operations using Redis cache.

**Implementation**:
- Client sends `X-Idempotency-Key` header with unique UUID
- Server checks Redis: `idempotency:{key}`
- If exists: Return cached response
- If not exists: Process request, store result, return response

**Benefit**: Retrying a failed request produces same result (exactly one appointment created)

**Operations Using Idempotence**:
- `POST /appointments` - Create booking
- `POST /appointments/{id}/cancel` - Cancel appointment
- `POST /users` - Create user

### 2. Multi-Tenant Isolation (Aislamiento Multi-Tenant)

**Architecture**: Three-layer isolation strategy

**Layer 1: Application (JWT)**
- JWT token contains `store_id`
- User can only act as their assigned store

**Layer 2: Middleware**
- `TenantMiddleware` extracts `store_id` from JWT
- Configures database session: `set_config('app.current_store_id', store_id)`

**Layer 3: Database (RLS)**
- PostgreSQL policies filter by `store_id`
- Impossible to access another store's data (even with SQL injection)

**Guarantee**: 
```
Store A can NEVER see data from Store B
- Even if app has security bugs
- Even if user tries SQL injection
- RLS filters at database level
```

### 3. Overlap Detection (Detección de Solapamientos - Overlap y Detection)

**Problem**: Two appointments for same staff member at overlapping times.

**Solution**: Validate no conflicts before confirming appointment.

**Validation Logic**:
```
Two time intervals overlap if:
  interval1.start < interval2.end AND
  interval2.start < interval1.end
```

**SQL Implementation**:
```sql
SELECT COUNT(*) FROM appointments
WHERE staff_id = :staff_id
  AND (starts_at, starts_at + interval '1 minute' * duration_minutes)
    OVERLAPS (:new_start, :new_start + interval '1 minute' * :new_duration)
  AND status NOT IN ('CANCELLED')
```

**Result**:
- COUNT > 0 → Conflict detected → Return HTTP 409 (Conflict)
- COUNT = 0 → No conflict → Proceed with booking

**Performance**: Indexed on (staff_id, starts_at) → typically < 5ms

**Atomicity**: Wrapped in transaction to prevent race conditions
- If two clients book last slot simultaneously:
  - Transaction 1 succeeds (creates appointment)
  - Transaction 2 detects overlap → Rejected
  - **Result**: Exactly one appointment per slot

---

## 🔒 Security Model

The security model integrates multiple layers:

| Layer | Component | Mechanism | Purpose |
|-------|-----------|-----------|---------|
| **Database** | RLS Policies | Automatic row filtering by `store_id` | Multi-tenant isolation |
| **Application** | JWT Token | Carry `store_id` and `role` | Identity & authorization |
| **Middleware** | Tenant Context | Set `app.current_store_id` for session | DB knows current tenant |
| **API** | Route Guards | Require authentication on endpoints | Prevent anonymous access |

---

## 📊 Caching Strategy

- **Redis**: Used for:
  - Idempotency key storage (prevents duplicate bookings)
  - Session cache (optional, for performance)
  - Rate limiting (optional, for security)
- **Windows Note**: Use Memurai as Redis alternative on Windows

---

## 🔄 Asynchronous Processing

Notifications and event handlers run async:
- Event: `AppointmentConfirmed` → Trigger async email/SMS
- Event: `AppointmentCancelled` → Trigger cancellation notification
- No blocking of main request thread

