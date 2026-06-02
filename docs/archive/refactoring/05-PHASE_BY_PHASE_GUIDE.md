# 📅 PHASE-BY-PHASE EXECUTION GUIDE

## Quick Reference

| Phase | Name | Duration | Complexity | Risk |
|-------|------|----------|-----------|------|
| 0 | Preparation | 3 hrs | Low | None |
| 1 | Extract Presentation | 8-10 hrs | Medium | Low |
| 2 | Create Routers | 8-12 hrs | High | Medium |
| 3 | Cleanup | 1-2 hrs | Low | None |
| 4 | Testing & Validation | 4-6 hrs | Medium | Medium |
| 5 | Documentation | 3-4 hrs | Low | None |
| **TOTAL** | **All Phases** | **27-37 hrs** | — | — |

---

## 🟦 PHASE 0: PREPARATION (3 hours)

### Objective
Set up infrastructure for clean refactoring with minimal risk

### Prerequisites
- [ ] Node.js 18+ installed
- [ ] Git repository initialized
- [ ] Current branch is clean (`git status` shows nothing)
- [ ] Latest changes committed
- [ ] Team informed about refactoring

### Step-by-Step Execution

#### 0.1 Create Backup Branch (15 min)
```bash
cd frontend
git checkout -b refactoring/clean-architecture
git push origin refactoring/clean-architecture
```

#### 0.2 Create Directory Structure (30 min)
```bash
# Create presentation structure
mkdir -p src/presentation/api/v1/{auth,appointments,users,staff,services,dashboard,reports,budget,bookings,settings}
mkdir -p src/presentation/api/middleware
mkdir -p src/presentation/pages
mkdir -p src/presentation/containers
mkdir -p src/presentation/layouts
mkdir -p src/presentation/context
mkdir -p src/presentation/hooks
mkdir -p src/presentation/components/{atoms,molecules,organisms}

# Create shared structure
mkdir -p src/shared/utils/__tests__
mkdir -p src/shared/constants
mkdir -p src/shared/types
mkdir -p src/shared/theme

# Create scripts
mkdir -p scripts
```

Verify structure:
```bash
find src/presentation -type d | head -20
# Should show all new directories
```

#### 0.3 Copy Existing Layers (30 min)
Verify these layers are complete and untouched:
- [ ] Run: `ls -la src/domain/`
  - Should have: entities/, repositories/, use-cases/, value-objects/, exceptions/
  - ✅ KEEP AS-IS (no changes)

- [ ] Run: `ls -la src/application/`
  - Should have: services/, dtos/, validators/, mappers/, errors/
  - ✅ KEEP AS-IS (no changes)

- [ ] Run: `ls -la src/infrastructure/`
  - Should have: http/, repositories/, storage/, cache/
  - ✅ KEEP AS-IS (no changes)

- [ ] Run: `ls -la src/shared/`
  - Should have: utils/, constants/, types/, theme/
  - ✅ KEEP AS-IS (no changes)

#### 0.4 Create Git Tag for Safety (15 min)
```bash
git add -A
git commit -m "Phase 0: Directory structure created"
git tag -a phase-0-prepared -m "Before Phase 0 prep - clean state"
git log --oneline -1
```

#### 0.5 Documentation Setup (15 min)
Copy documentation files from REFACTORING_DOCS/:
```bash
cp ../REFACTORING_DOCS/*.md ./docs/REFACTORING/
```

Verify documents exist:
- [ ] 01-FILE_MAPPING.md
- [ ] 02-IMPORT_RULES.md
- [ ] 03-MIGRATION_CHECKLIST.md
- [ ] 04-PURE_CLEAN_ARCHITECTURE.md

#### 0.6 Verification Checkpoint
```bash
npm run build 2>&1 | head -20
# Should have same errors as before (nothing new broken)

npm run dev
# Start dev server - should work
# Stop with Ctrl+C
```

### ✅ Phase 0 Complete Checklist
- [ ] Branch created: `refactoring/clean-architecture`
- [ ] All directories created under `src/presentation/`
- [ ] Existing layers verified (domain/, application/, infrastructure/, shared/)
- [ ] Git tag created: `phase-0-prepared`
- [ ] Documentation copied to docs/REFACTORING/
- [ ] Build still works
- [ ] Team notified

### 💾 Rollback If Needed
```bash
git reset --hard HEAD~1  # Undo Phase 0
git checkout main        # Back to main branch
```

---

## 🟩 PHASE 1: EXTRACT PRESENTATION LAYER (8-10 hours)

### Objective
Move all UI-related code (pages, components, hooks, context) to unified presentation layer

### Day-of Checklist
- [ ] Fresh dev environment: `npm install`
- [ ] No uncommitted changes: `git status` is clean
- [ ] Dev server not running
- [ ] Check that features/ directory still exists (we delete in Phase 3)

### Step-by-Step Execution

#### Phase 1.1: Move Pages (Subtask - 2 hours)

**Move "clean" pages first** (9 pages with no infrastructure imports):

```bash
# Create index file
touch src/presentation/pages/index.ts

# Move individual files (copy, don't delete yet)
cp src/pages/Dashboard.tsx src/presentation/pages/dashboard-page.tsx
cp src/pages/Calendar.tsx src/presentation/pages/appointments-page.tsx
cp src/pages/Reports.tsx src/presentation/pages/reports-page.tsx
cp src/pages/Budget.tsx src/presentation/pages/budget-page.tsx
cp src/pages/Services.tsx src/presentation/pages/services-page.tsx
cp src/pages/Staff.tsx src/presentation/pages/staff-page.tsx
cp src/pages/Users.tsx src/presentation/pages/users-page.tsx
cp src/pages/Settings.tsx src/presentation/pages/settings-page.tsx
cp src/pages/PublicBooking.tsx src/presentation/pages/public-booking-page.tsx
```

**For each moved page**:
1. Open file in editor
2. Check all imports still resolve (they should - using same path aliases)
3. Save

**Create index file** `src/presentation/pages/index.ts`:
```typescript
export { DashboardPage as default } from './dashboard-page'
export { AppointmentsPage } from './appointments-page'
export { ReportsPage } from './reports-page'
export { BudgetPage } from './budget-page'
export { ServicesPage } from './services-page'
export { StaffPage } from './staff-page'
export { UsersPage } from './users-page'
export { SettingsPage } from './settings-page'
export { PublicBookingPage } from './public-booking-page'
```

**Test**: `npm run build` - should have no new errors

**Commit**:
```bash
git add src/presentation/pages/
git commit -m "feat: move 9 clean pages to presentation layer"
```

---

**Move "needs refactor" pages** (4 pages that import apiClient):

For each of these files: `Login.tsx`, `Register.tsx`, `ForgotPassword.tsx`, `ResetPassword.tsx`

1. **Copy file with new name**:
```bash
cp src/pages/Login.tsx src/presentation/pages/login-page.tsx
```

2. **Remove infrastructure import**:
```typescript
// REMOVE:
import { apiClient } from '@infrastructure/http/client'

// ADD:
import { UserService } from '@application/services'
import { HttpUserRepository } from '@infrastructure/repositories'
```

3. **Replace all apiClient.post/get calls** with service calls:
```typescript
// BEFORE:
const response = await apiClient.post('/auth/login', { email, password })
const user = response.data

// AFTER:
const userService = new UserService(new HttpUserRepository())
const user = await userService.login({ email, password })
```

4. **Test in browser**:
   - Dev server: `npm run dev`
   - Navigate to /login
   - Should render without errors
   - Stop dev server

5. **Build test**: `npm run build`

6. **Commit**:
```bash
git add src/presentation/pages/{login,register,forgot-password,reset-password}-page.tsx
git commit -m "refactor: move auth pages with API refactoring"
```

**Git Tag**:
```bash
git tag -a phase-1.1-pages-moved -m "All 13 pages moved to presentation layer"
```

---

#### Phase 1.2: Move Components (Subtask - 1.5 hours)

```bash
# Create index files
touch src/presentation/components/atoms/index.ts
touch src/presentation/components/molecules/index.ts
touch src/presentation/components/organisms/index.ts
touch src/presentation/components/index.ts

# Move existing components
cp src/components/Icon2000s.tsx src/presentation/components/atoms/icon-2000s.tsx
cp src/components/Sidebar.tsx src/presentation/components/organisms/sidebar.tsx

# Remove old components directory if empty
rm -rf src/components/ui/
```

**Create atom index** `src/presentation/components/atoms/index.ts`:
```typescript
export { Icon2000s } from './icon-2000s'
export { Button } from './button'
export { Input } from './input'
export { Badge } from './badge'
export { SkeuoCard } from './skeu-card'
```

**Create molecules index** `src/presentation/components/molecules/index.ts`:
```typescript
export { FormField } from './form-field'
export { UserCard } from './user-card'
export { StaffCard } from './staff-card'
export { ServiceCard } from './service-card'
```

**Create organisms index** `src/presentation/components/organisms/index.ts`:
```typescript
export { Sidebar } from './sidebar'
export { UserGrid } from './user-grid'
export { BookingWizard } from './booking-wizard'
```

**Create main index** `src/presentation/components/index.ts`:
```typescript
export * from './atoms'
export * from './molecules'
export * from './organisms'
```

**Build test**: `npm run build`

**Commit**:
```bash
git add src/presentation/components/
git commit -m "refactor: move components to atomic structure"
git tag -a phase-1.2-components-moved -m "Components organized by atomic design"
```

---

#### Phase 1.3: Move Layouts (Subtask - 1 hour)

```bash
# Move existing layout
cp src/layouts/AdminLayout.tsx src/presentation/layouts/admin-layout.tsx

# Create new layouts (copy AdminLayout as template, then modify)
cp src/presentation/layouts/admin-layout.tsx src/presentation/layouts/auth-layout.tsx
cp src/presentation/layouts/admin-layout.tsx src/presentation/layouts/public-layout.tsx
```

**Edit auth-layout.tsx**:
```typescript
// Remove sidebar, simplify header
export function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen flex items-center justify-center">
      <div className="w-full max-w-md">
        {children}
      </div>
    </div>
  )
}
```

**Edit public-layout.tsx**:
```typescript
// For public booking page
export function PublicLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-white">
      {/* Public header (no admin UI) */}
      {children}
    </div>
  )
}
```

**Create index** `src/presentation/layouts/index.ts`:
```typescript
export { AdminLayout } from './admin-layout'
export { AuthLayout } from './auth-layout'
export { PublicLayout } from './public-layout'
```

**Build test**: `npm run build`

**Commit**:
```bash
git add src/presentation/layouts/
git commit -m "refactor: move and extend layouts"
git tag -a phase-1.3-layouts-done -m "Layouts created and configured"
```

---

#### Phase 1.4: Move Context (Subtask - 45 min)

```bash
# Move auth context from features
cp src/features/auth/context.tsx src/presentation/context/auth-context.tsx

# Remove infrastructure import and add service
# BEFORE:
import { apiClient } from '@infrastructure/http/client'
const response = await apiClient.put('/auth/change-password', ...)

# AFTER:
import { UserService } from '@application/services'
const userService = new UserService(new HttpUserRepository())
await userService.changePassword(...)
```

**Create context index** `src/presentation/context/index.ts`:
```typescript
export { AuthContext, AuthProvider, useAuthContext } from './auth-context'
```

**Create skeleton contexts** (for future use):
```bash
touch src/presentation/context/store-context.tsx
touch src/presentation/context/theme-context.tsx
```

**Build test**: `npm run build`

**Commit**:
```bash
git add src/presentation/context/
git commit -m "refactor: move auth context with API refactoring"
git tag -a phase-1.4-context-done -m "Context moved and refactored"
```

---

#### Phase 1.5: Move & Refactor Hooks (Subtask - 2-3 hours)

For each hook file in `src/features/*/hooks.ts`:

**Example: features/auth/hooks.ts → presentation/hooks/use-auth.ts**

```bash
cp src/features/auth/hooks.ts src/presentation/hooks/use-auth.ts
```

**Edit the hook - remove infrastructure import**:
```typescript
// BEFORE:
import { apiClient } from '@infrastructure/http/client'

export function useChangePassword() {
  return useMutation({
    mutationFn: (params) => 
      apiClient.put('/auth/change-password', params)
  })
}

// AFTER:
import { UserService } from '@application/services'
import { HttpUserRepository } from '@infrastructure/repositories'

export function useChangePassword() {
  const userService = new UserService(new HttpUserRepository())
  
  return useMutation({
    mutationFn: (params) => 
      userService.changePassword(params)
  })
}
```

**Repeat for all 9 hooks**:
- appointments → use-appointments.ts
- budget → use-budget.ts
- dashboard → use-dashboard.ts
- public → use-public-booking.ts
- reports → use-reports.ts
- staff → use-staff.ts
- stores → use-store.ts

**Also move types**:
```bash
cp src/features/booking/types.ts src/presentation/types/booking-types.ts
```

**Create hook index** `src/presentation/hooks/index.ts`:
```typescript
export * from './use-appointments'
export * from './use-auth'
export * from './use-budget'
export * from './use-dashboard'
export * from './use-public-booking'
export * from './use-reports'
export * from './use-staff'
export * from './use-store'
// Generic hooks
export * from './use-form'
export * from './use-async'
export * from './use-debounce'
export * from './use-local-storage'
```

**Create generic hooks** (new files):

`use-form.ts` - wrapper around React Hook Form:
```typescript
import { useForm as useReactHookForm } from 'react-hook-form'
import { ZodSchema } from 'zod'
import { zodResolver } from '@hookform/resolvers/zod'

export function useForm<T>(schema: ZodSchema) {
  return useReactHookForm<T>({
    resolver: zodResolver(schema)
  })
}
```

`use-async.ts` - generic async state:
```typescript
import { useState, useCallback } from 'react'

export function useAsync<T>(fn: () => Promise<T>) {
  const [data, setData] = useState<T | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<Error | null>(null)

  const execute = useCallback(async () => {
    setLoading(true)
    try {
      const result = await fn()
      setData(result)
    } catch (err) {
      setError(err as Error)
    } finally {
      setLoading(false)
    }
  }, [fn])

  return { data, loading, error, execute }
}
```

`use-debounce.ts`:
```typescript
import { useEffect, useState } from 'react'

export function useDebounce<T>(value: T, delay: number): T {
  const [debounced, setDebounced] = useState(value)

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delay)
    return () => clearTimeout(timer)
  }, [value, delay])

  return debounced
}
```

`use-local-storage.ts`:
```typescript
import { useState, useEffect } from 'react'

export function useLocalStorage<T>(key: string, initialValue: T) {
  const [value, setValue] = useState<T>(() => {
    const item = localStorage.getItem(key)
    return item ? JSON.parse(item) : initialValue
  })

  useEffect(() => {
    localStorage.setItem(key, JSON.stringify(value))
  }, [key, value])

  return [value, setValue] as const
}
```

**Build test**: `npm run build`

**Commit**:
```bash
git add src/presentation/hooks/
git add src/presentation/types/
git commit -m "refactor: move hooks to presentation with API refactoring"
git tag -a phase-1.5-hooks-done -m "Hooks refactored and moved"
```

---

#### Phase 1.6: Verify & Update Containers (Subtask - 45 min)

**Rename existing containers** for consistency:
```bash
# These likely already exist in src/presentation/containers/
# Just rename to kebab-case if needed
mv src/presentation/containers/CalendarContainer.tsx \
   src/presentation/containers/appointments-container.tsx

mv src/presentation/containers/UserManagementContainer.tsx \
   src/presentation/containers/user-management-container.tsx

mv src/presentation/containers/StaffManagementContainer.tsx \
   src/presentation/containers/staff-management-container.tsx

mv src/presentation/containers/ServiceManagementContainer.tsx \
   src/presentation/containers/service-management-container.tsx
```

**Create container index** `src/presentation/containers/index.ts`:
```typescript
export { AppointmentsContainer } from './appointments-container'
export { UserManagementContainer } from './user-management-container'
export { StaffManagementContainer } from './staff-management-container'
export { ServiceManagementContainer } from './service-management-container'
export { BookingContainer } from './booking-container'
export { AuthContainer } from './auth-container'
export { DashboardContainer } from './dashboard-container'
```

**Build test**: `npm run build`

**Commit**:
```bash
git add src/presentation/containers/
git commit -m "refactor: standardize container naming"
```

---

#### Phase 1.7: Update App.tsx (Subtask - 30 min)

Update main routing file to use new page paths:

```typescript
// src/App.tsx - BEFORE
import { DashboardPage } from './pages/Dashboard'
import { LoginPage } from './pages/Login'
// ... 11 more imports

// src/App.tsx - AFTER
import * as Pages from '@presentation/pages'

export function App() {
  // Routes can now reference Pages.LoginPage, Pages.DashboardPage, etc.
}
```

OR keep individual imports updated:
```typescript
import { LoginPage } from '@presentation/pages/login-page'
import { RegisterPage } from '@presentation/pages/register-page'
// ... update all 13 imports
```

Also update layout imports:
```typescript
import { AdminLayout, AuthLayout, PublicLayout } from '@presentation/layouts'
```

**Build test**: `npm run build`

**Commit**:
```bash
git add src/App.tsx
git commit -m "refactor: update app routing imports"
```

---

#### Phase 1.8: Final Verification (Subtask - 30 min)

```bash
# Verify compilation
npm run build
# Should pass with no new errors

# Start dev server
npm run dev
# ✅ Server starts
# ✅ No console errors
# ✅ All routes load
# ⏹️ Stop dev server (Ctrl+C)

# Check TypeScript
npx tsc --noEmit
# Should pass
```

### ✅ Phase 1 Complete

**Final Commit & Tag**:
```bash
git add -A
git commit -m "Phase 1: Extract presentation layer complete"
git tag -a phase-1-complete -m "Presentation layer extracted and refactored"
git push origin refactoring/clean-architecture
```

**Status Check**:
- [ ] All 13 pages in `src/presentation/pages/`
- [ ] Components organized in atoms/molecules/organisms
- [ ] 3 layouts created (admin, auth, public)
- [ ] 8 hooks moved and refactored
- [ ] Context moved and refactored
- [ ] Containers renamed
- [ ] `src/App.tsx` updated
- [ ] Build passes
- [ ] Dev server runs
- [ ] No new errors in console

---

## 🟨 PHASE 2: CREATE ROUTERS (8-12 hours)

### Objective
Create Express-like router structure in `src/presentation/api/v1/` to centralize routing and dependency injection

### Step 1: Create Root Router Structure (30 min)

```bash
# Create main router files
touch src/presentation/api/v1/index.ts
touch src/presentation/api/middleware/auth-middleware.ts
touch src/presentation/api/middleware/error-middleware.ts
touch src/presentation/api/middleware/index.ts
```

**Create** `src/presentation/api/v1/index.ts`:
```typescript
import { createBrowserRouter, Navigate } from 'react-router-dom'
import { authRouter } from './auth/router'
import { appointmentsRouter } from './appointments/router'
import { usersRouter } from './users/router'
// ... import all feature routers

export const appRouter = createBrowserRouter([
  // Public routes
  ...authRouter,
  ...bookingsRouter,
  
  // Protected routes
  ...appointmentsRouter,
  ...usersRouter,
  ...staffRouter,
  ...servicesRouter,
  ...dashboardRouter,
  ...reportsRouter,
  ...budgetRouter,
  ...settingsRouter,
  
  // Fallback
  { path: '*', element: <Navigate to="/dashboard" /> }
])
```

### Step 2: Create Auth Router (1 hour)

**Create** `src/presentation/api/v1/auth/router.tsx`:
```typescript
import { RouteObject } from 'react-router-dom'
import { AuthLayout } from '@presentation/layouts'
import { LoginPage } from '@presentation/pages/login-page'
import { RegisterPage } from '@presentation/pages/register-page'
import { ForgotPasswordPage } from '@presentation/pages/forgot-password-page'
import { ResetPasswordPage } from '@presentation/pages/reset-password-page'

export const authRouter: RouteObject[] = [
  {
    path: '/login',
    element: <AuthLayout><LoginPage /></AuthLayout>,
    errorElement: <ErrorPage />
  },
  {
    path: '/register',
    element: <AuthLayout><RegisterPage /></AuthLayout>
  },
  {
    path: '/forgot-password',
    element: <AuthLayout><ForgotPasswordPage /></AuthLayout>
  },
  {
    path: '/reset-password',
    element: <AuthLayout><ResetPasswordPage /></AuthLayout>
  }
]
```

**Create** `src/presentation/api/v1/auth/dependencies.ts`:
```typescript
import { UserService } from '@application/services'
import { HttpUserRepository } from '@infrastructure/repositories'

export const authDependencies = {
  userService: new UserService(new HttpUserRepository())
}
```

### Step 3: Create Other Feature Routers (6-10 hours)

Repeat for each feature (appointments, users, staff, services, dashboard, reports, budget, bookings, settings):

**Template** `src/presentation/api/v1/{feature}/router.tsx`:
```typescript
import { RouteObject } from 'react-router-dom'
import { ProtectedRoute } from '@presentation/api/middleware/auth-middleware'
import { AdminLayout } from '@presentation/layouts'
import { FeaturePage } from '@presentation/pages/feature-page'
import { ProtectedRoute } from '../middleware/auth-middleware'

export const featureRouter: RouteObject[] = [
  {
    element: <ProtectedRoute><AdminLayout /></ProtectedRoute>,
    children: [
      {
        path: '/dashboard/feature',
        element: <FeaturePage />
      }
    ]
  }
]
```

**Template** `src/presentation/api/v1/{feature}/dependencies.ts`:
```typescript
import { FeatureService } from '@application/services'
import { HttpFeatureRepository } from '@infrastructure/repositories'

export const featureDependencies = {
  featureService: new FeatureService(new HttpFeatureRepository())
}
```

### Step 4: Update App.tsx (30 min)

**Before**:
```typescript
export function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        {/* 50+ routes */}
      </Routes>
    </BrowserRouter>
  )
}
```

**After**:
```typescript
import { RouterProvider } from 'react-router-dom'
import { appRouter } from '@presentation/api/v1'

export function App() {
  return <RouterProvider router={appRouter} />
}
```

### ✅ Phase 2 Complete

**Commit**:
```bash
git add src/presentation/api/
git commit -m "Phase 2: Create routers and dependency injection"
git tag -a phase-2-complete -m "Routers created in presentation/api/v1"
git push origin refactoring/clean-architecture
```

---

## 🟧 PHASE 3: CLEANUP (1-2 hours)

### Objective
Delete legacy directories that have been migrated

### Step 1: Verify Everything Migrated (15 min)

```bash
# Check for any imports from features/
grep -r "from.*features" src/

# Should be ZERO results (if any found, migrate them first)

# Check for imports from old locations
grep -r "from.*src/pages" src/
grep -r "from.*src/layouts" src/
```

### Step 2: Delete Legacy Directories (15 min)

```bash
# Backup first (just in case)
git tag -a before-cleanup-$(date +%s) -m "Before deleting legacy dirs"

# Delete features/
rm -rf src/features/

# Delete old pages/
rm -rf src/pages/

# Delete old layouts/
rm -rf src/layouts/

# Delete old components/ if empty
rm -rf src/components/

# Verify deletion
ls -la src/ | grep -E "features|pages|layouts|components"
# Should show NO results
```

### Step 3: Fix Any Broken Imports

```bash
npm run build
# If errors, fix import paths in affected files
```

### ✅ Phase 3 Complete

**Commit**:
```bash
git add -A
git commit -m "Phase 3: Delete legacy directories"
git tag -a phase-3-complete -m "Cleanup complete"
git push origin refactoring/clean-architecture
```

---

## 🔵 PHASE 4: TESTING & VALIDATION (4-6 hours)

### Objective
Verify clean architecture compliance and no regressions

### Step 1: Run Verification Script (15 min)

```bash
# Install verification tool
npm install -D ts-node

# Run verification
npx ts-node scripts/verify-clean-architecture.ts

# Should output:
# ✅ PASSED: Architecture is 100% Clean Architecture compliant!
```

### Step 2: Run Build & Type Check (30 min)

```bash
# Build
npm run build
# Should complete with no errors

# Type check
npx tsc --noEmit
# Should show no errors
```

### Step 3: Manual Testing (2 hours)

```bash
# Start dev server
npm run dev

# Test each route manually:
# ✅ /login - renders
# ✅ /register - renders  
# ✅ /forgot-password - renders
# ✅ /reset-password - renders
# ✅ /dashboard - requires login (redirects to /login if not authenticated)
# ✅ /dashboard/appointments - loads appointments
# ✅ /dashboard/users - loads users
# ✅ /dashboard/staff - loads staff
# ✅ /dashboard/services - loads services
# ✅ /dashboard/reports - loads reports
# ✅ /dashboard/budget - loads budget
# ✅ /dashboard/settings - loads settings
# ✅ /booking/:slug - renders public booking page (public, no auth needed)

# Check console - should have ZERO errors, minimal warnings
# Login flow should work end-to-end
# API calls should complete successfully
```

### Step 4: Run Unit Tests (2 hours - if tests exist)

```bash
npm test

# Should pass all tests
# Coverage should be > 60%
```

### ✅ Phase 4 Complete

**Commit**:
```bash
git add -A
git commit -m "Phase 4: Testing and validation complete"
git tag -a phase-4-complete -m "All tests passing"
git push origin refactoring/clean-architecture
```

---

## 📚 PHASE 5: DOCUMENTATION (3-4 hours)

### Create Documentation

1. **Update README.md**
2. **Create ARCHITECTURE.md**
3. **Create API_STRUCTURE.md**
4. **Update CONTRIBUTING.md** (if exists)

### ✅ Phase 5 Complete

```bash
git add -A
git commit -m "Phase 5: Documentation updates"
git tag -a phase-5-complete -m "Documentation complete"
git push origin refactoring/clean-architecture
```

---

## 🎉 FINAL: MERGE & DEPLOY

### Pre-Merge Checklist
- [ ] All phases complete
- [ ] All tests passing
- [ ] All documentation updated
- [ ] Code reviewed by team lead
- [ ] Staging deployment successful

### Merge to Main
```bash
git checkout main
git pull origin main
git merge refactoring/clean-architecture
git push origin main
```

### Monitor in Production
- [ ] Watch error logs
- [ ] Monitor performance
- [ ] Check user reports
- [ ] Team feedback collection

---

## 📊 Progress Tracking Template

Use this to track progress day-by-day:

```markdown
## Refactoring Progress

### Phase 0: ✅ COMPLETE (3 hrs)
- [x] Created directory structure
- [x] Verified existing layers
- [x] Created git tags
- [x] Setup documentation

### Phase 1: 🟡 IN PROGRESS (___/10 hrs)
- [x] Moved 9 clean pages
- [ ] Moved 4 auth pages (refactoring)
- [ ] Moved components
- [ ] Moved layouts
- [ ] Moved context
- [ ] Moved hooks
- [ ] Updated containers
- [ ] Updated App.tsx

### Phase 2: ⏳ PENDING (0/12 hrs)
- [ ] Create root router
- [ ] Create auth router
- [ ] Create feature routers
- [ ] Update App.tsx

### Phase 3: ⏳ PENDING (0/2 hrs)
- [ ] Delete legacy directories

### Phase 4: ⏳ PENDING (0/6 hrs)
- [ ] Run verification
- [ ] Manual testing
- [ ] Unit tests

### Phase 5: ⏳ PENDING (0/4 hrs)
- [ ] Update documentation

**Total Time Spent**: ___ hours
**Estimated Remaining**: ___ hours
```

