# 📦 FILE MAPPING: OLD → NEW PATHS

## Executive Summary
- **Total files to move/reorganize**: 85+ files
- **Phases required**: 6 phases
- **Risk level**: LOW (simple move/refactor, no logic changes)
- **Breaking changes**: 0 (internal refactor, no API changes)

---

## DETAILED FILE MAPPING

### 🔵 PHASE 0: NO CHANGES (Copy as-is)

#### Domain Layer (No changes)
```
domain/                           →  domain/
├── entities/**/*.ts               →  entities/**/*.ts
├── repositories/**/*.ts           →  repositories/**/*.ts
├── use-cases/**/*.ts              →  use-cases/**/*.ts
├── value-objects/**/*.ts          →  value-objects/**/*.ts
└── exceptions/**/*.ts             →  exceptions/**/*.ts
```

#### Application Layer (No changes)
```
application/                      →  application/
├── services/**/*.ts               →  services/**/*.ts
├── dtos/**/*.ts                   →  dtos/**/*.ts
├── mappers/**/*.ts                →  mappers/**/*.ts
├── validators/**/*.ts             →  validators/**/*.ts
└── errors/**/*.ts                 →  errors/**/*.ts
```

#### Infrastructure Layer (No changes)
```
infrastructure/                   →  infrastructure/
├── http/
│   └── client.ts                  →  http/client.ts
├── repositories/**/*.ts           →  repositories/**/*.ts
├── storage/**/*.ts                →  storage/**/*.ts
└── cache/**/*.ts                  →  cache/**/*.ts
```

#### Shared Layer (No changes)
```
shared/                           →  shared/
├── utils/**/*.ts                  →  utils/**/*.ts
├── constants/**/*.ts              →  constants/**/*.ts
├── types/**/*.ts                  →  types/**/*.ts
├── theme/**/*.ts                  →  theme/**/*.ts
└── theme/**/*.css                 →  theme/**/*.css
```

---

### 🟢 PHASE 1A: MOVE PAGES

| Current Path | New Path | Type | Status |
|--------------|----------|------|--------|
| `pages/Login.tsx` | `presentation/pages/login-page.tsx` | ⚠️ Update imports | Needs Refactor |
| `pages/Register.tsx` | `presentation/pages/register-page.tsx` | ⚠️ Update imports | Needs Refactor |
| `pages/ForgotPassword.tsx` | `presentation/pages/forgot-password-page.tsx` | ⚠️ Update imports | Needs Refactor |
| `pages/ResetPassword.tsx` | `presentation/pages/reset-password-page.tsx` | ⚠️ Update imports | Needs Refactor |
| `pages/Dashboard.tsx` | `presentation/pages/dashboard-page.tsx` | ✅ Clean | Ready |
| `pages/Calendar.tsx` | `presentation/pages/appointments-page.tsx` | ✅ Clean | Ready |
| `pages/Reports.tsx` | `presentation/pages/reports-page.tsx` | ✅ Clean | Ready |
| `pages/Budget.tsx` | `presentation/pages/budget-page.tsx` | ✅ Clean | Ready |
| `pages/Services.tsx` | `presentation/pages/services-page.tsx` | ✅ Clean | Ready |
| `pages/Staff.tsx` | `presentation/pages/staff-page.tsx` | ✅ Clean | Ready |
| `pages/Users.tsx` | `presentation/pages/users-page.tsx` | ✅ Clean | Ready |
| `pages/Settings.tsx` | `presentation/pages/settings-page.tsx` | ✅ Clean | Ready |
| `pages/PublicBooking.tsx` | `presentation/pages/public-booking-page.tsx` | ✅ Clean | Ready |

**Summary**:
- 13 pages total
- 4 pages need import refactoring (remove `@infrastructure/http/client`)
- 9 pages ready to move as-is

---

### 🟢 PHASE 1B: MOVE COMPONENTS (Atomic Structure)

| Current Path | New Path | Type | Status |
|--------------|----------|------|--------|
| `components/Icon2000s.tsx` | `presentation/components/atoms/icon-2000s.tsx` | ✅ Atom | Ready |
| `components/Sidebar.tsx` | `presentation/components/organisms/sidebar.tsx` | ✅ Organism | Ready |
| `components/ui/*` | → Remove (empty) | — | — |

**Create new atoms** (move from features/ components):
- `presentation/components/atoms/button.tsx`
- `presentation/components/atoms/input.tsx`
- `presentation/components/atoms/badge.tsx`
- `presentation/components/atoms/skeu-card.tsx`

**Create new molecules**:
- `presentation/components/molecules/user-card.tsx`
- `presentation/components/molecules/staff-card.tsx`
- `presentation/components/molecules/service-card.tsx`
- `presentation/components/molecules/appointment-card.tsx`
- `presentation/components/molecules/form-field.tsx`
- `presentation/components/molecules/skeu-card-header.tsx`
- `presentation/components/molecules/skeu-card-footer.tsx`

**Create new organisms**:
- `presentation/components/organisms/user-grid.tsx`
- `presentation/components/organisms/staff-grid.tsx`
- `presentation/components/organisms/service-grid.tsx`
- `presentation/components/organisms/appointment-timeline.tsx`
- `presentation/components/organisms/booking-wizard.tsx`
- `presentation/components/organisms/skeu-card-grid.tsx`
- `presentation/components/organisms/user-form-modal.tsx`
- `presentation/components/organisms/staff-form-modal.tsx`
- `presentation/components/organisms/service-form-modal.tsx`

---

### 🟢 PHASE 1C: MOVE LAYOUTS

| Current Path | New Path | Type | Status |
|--------------|----------|------|--------|
| `layouts/AdminLayout.tsx` | `presentation/layouts/admin-layout.tsx` | ✅ Clean | Ready |

**Create new layouts**:
- `presentation/layouts/auth-layout.tsx` (for /login, /register, /forgot-password, /reset-password)
- `presentation/layouts/public-layout.tsx` (for /booking/:slug)

---

### 🟡 PHASE 2A: MOVE HOOKS (Presentation → presentation/hooks)

| Current Path | New Path | Type | Status |
|--------------|----------|------|--------|
| `features/appointments/hooks.ts` | `presentation/hooks/use-appointments.ts` | 🔴 Refactor | Remove infra imports |
| `features/auth/hooks.ts` | `presentation/hooks/use-auth.ts` | ✅ Clean | Ready |
| `features/budget/hooks.ts` | `presentation/hooks/use-budget.ts` | 🔴 Refactor | Remove infra imports |
| `features/dashboard/hooks.ts` | `presentation/hooks/use-dashboard.ts` | 🔴 Refactor | Remove infra imports |
| `features/public/hooks.ts` | `presentation/hooks/use-public-booking.ts` | 🔴 Refactor | Remove infra imports |
| `features/reports/hooks.ts` | `presentation/hooks/use-reports.ts` | 🔴 Refactor | Remove infra imports |
| `features/staff/hooks.ts` | `presentation/hooks/use-staff.ts` | 🔴 Refactor | Remove infra imports |
| `features/stores/hooks.ts` | `presentation/hooks/use-store.ts` | 🔴 Refactor | Remove infra imports |
| `features/booking/types.ts` | `presentation/types/booking-types.ts` | ✅ Types only | Ready |

**New shared hooks to create**:
- `presentation/hooks/use-form.ts` - React Hook Form integration
- `presentation/hooks/use-async.ts` - Generic async state
- `presentation/hooks/use-debounce.ts` - Debounce hook
- `presentation/hooks/use-local-storage.ts` - localStorage hook

---

### 🟡 PHASE 2B: MOVE CONTEXT

| Current Path | New Path | Type | Status |
|--------------|----------|------|--------|
| `features/auth/context.tsx` | `presentation/context/auth-context.tsx` | 🔴 Refactor | Remove infra imports |

**Create new contexts**:
- `presentation/context/store-context.tsx` - Store/organization context
- `presentation/context/theme-context.tsx` - Theme context

---

### 🟡 PHASE 2C: CREATE CONTAINERS

| Current Path (keep) | New Path (link from) | Type | Status |
|-----|-----|------|--------|
| `presentation/containers/CalendarContainer.tsx` | `presentation/containers/appointments-container.tsx` | ✅ Rename | Ready |
| `presentation/containers/UserManagementContainer.tsx` | `presentation/containers/user-management-container.tsx` | ✅ Rename | Ready |
| `presentation/containers/StaffManagementContainer.tsx` | `presentation/containers/staff-management-container.tsx` | ✅ Rename | Ready |
| `presentation/containers/ServiceManagementContainer.tsx` | `presentation/containers/service-management-container.tsx` | ✅ Rename | Ready |

**Create new containers**:
- `presentation/containers/booking-container.tsx`
- `presentation/containers/dashboard-container.tsx`
- `presentation/containers/reports-container.tsx`
- `presentation/containers/budget-container.tsx`
- `presentation/containers/settings-container.tsx`
- `presentation/containers/auth-container.tsx`

---

### 🔵 PHASE 3: CREATE ROUTERS (NEW)

| New Path | Purpose | Status |
|----------|---------|--------|
| `presentation/api/v1/auth/router.tsx` | Login, Register, ForgotPassword, ResetPassword routes | 🆕 Create |
| `presentation/api/v1/appointments/router.tsx` | Calendar/Appointments routes | 🆕 Create |
| `presentation/api/v1/users/router.tsx` | Users management routes | 🆕 Create |
| `presentation/api/v1/staff/router.tsx` | Staff management routes | 🆕 Create |
| `presentation/api/v1/services/router.tsx` | Services management routes | 🆕 Create |
| `presentation/api/v1/dashboard/router.tsx` | Dashboard route | 🆕 Create |
| `presentation/api/v1/reports/router.tsx` | Reports route | 🆕 Create |
| `presentation/api/v1/budget/router.tsx` | Budget route | 🆕 Create |
| `presentation/api/v1/bookings/router.tsx` | Public booking routes | 🆕 Create |
| `presentation/api/v1/settings/router.tsx` | Settings route | 🆕 Create |
| `presentation/api/v1/index.ts` | Aggregated router | 🆕 Create |

**Dependencies file** (inject dependencies):
| New Path | Purpose | Status |
|----------|---------|--------|
| `presentation/api/v1/auth/dependencies.ts` | AuthService, UserRepository, etc. | 🆕 Create |
| `presentation/api/v1/{feature}/dependencies.ts` | Feature-specific services | 🆕 Create |

---

### 🔵 PHASE 3B: CREATE MIDDLEWARE

| New Path | Purpose | Status |
|----------|---------|--------|
| `presentation/api/middleware/auth-middleware.ts` | ProtectedRoute guard + session check | 🆕 Create |
| `presentation/api/middleware/error-middleware.ts` | Global error handler | 🆕 Create |

---

### 🔴 PHASE 4: DELETE FEATURES

```
features/                         → ❌ DELETE ENTIRE FOLDER
├── appointments/
├── auth/
├── booking/
├── budget/
├── dashboard/
├── public/
├── reports/
├── staff/
└── stores/
```

**Why**: All functionality moved to presentation/api/v1/ and presentation/hooks/

---

## IMPORT UPDATES REQUIRED

### Files needing import statement updates (Phase 2+):

#### Auth Pages (4 files)
- `presentation/pages/login-page.tsx`
- `presentation/pages/register-page.tsx`
- `presentation/pages/forgot-password-page.tsx`
- `presentation/pages/reset-password-page.tsx`

**Change from**:
```typescript
import { apiClient } from '@infrastructure/http/client'
```

**Change to**:
```typescript
import { AuthService } from '@application/services'
import { HttpUserRepository } from '@infrastructure/repositories'
```

#### Hooks (8 files)
All `presentation/hooks/use-*.ts` files

**Change from**:
```typescript
import { apiClient } from '@infrastructure/http/client'
```

**Change to**:
```typescript
import { [Service]Service } from '@application/services'
import { Http[Feature]Repository } from '@infrastructure/repositories'
```

#### Context (1 file)
- `presentation/context/auth-context.tsx`

**Similar refactor to above**

#### App.tsx (1 file)
- `src/App.tsx`

**Change from**:
```typescript
import { BrowserRouter, Routes, Route } from 'react-router-dom'
```

**Change to**:
```typescript
import { RouterProvider } from 'react-router-dom'
import { appRouter } from '@presentation/api/v1'
```

---

## SUMMARY STATISTICS

| Category | Count | Status |
|----------|-------|--------|
| Files to move (no changes) | 45 | ✅ 100% Ready |
| Files to refactor (import changes) | 13 | 🟡 Needs refactor |
| New files to create | 35+ | 🆕 New |
| Files to delete | 0 (folder) | 🔴 Delete features/ |
| **Total affected files** | **~93** | — |

### Effort Breakdown
- Move files (Phase 1): 2-3 hours
- Refactor imports (Phase 2): 4-5 hours
- Create routers (Phase 3): 6-8 hours
- Delete cleanup (Phase 4): 30 minutes
- **Total**: 12-17 hours (1-2 developers)

---

## ROLLBACK PLAN

If issues occur during migration:

1. **Phase 0-1 Rollback**: Simple `git revert`
2. **Phase 2+ Rollback**: 
   - Keep old `features/` branch as backup
   - Revert all imports to use `features/`
   - Feature available within 1 hour

**Backup Strategy**: `git tag refactoring-phase-{N}` at end of each phase

