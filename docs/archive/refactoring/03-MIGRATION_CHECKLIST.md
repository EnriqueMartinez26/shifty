# ✅ MIGRATION CHECKLIST

## Phase Breakdown & Checklists

---

## 🟦 PHASE 0: PREPARATION (Estimated: 3 hours)

### 0.1 Create New Directory Structure
- [ ] Create `frontend/src/presentation/api/` directory
- [ ] Create `frontend/src/presentation/api/v1/` directory
- [ ] Create `frontend/src/presentation/api/v1/middleware/` directory
- [ ] Create `frontend/src/presentation/pages/` directory
- [ ] Create `frontend/src/presentation/layouts/` directory
- [ ] Create `frontend/src/presentation/context/` directory
- [ ] Create `frontend/src/presentation/hooks/` directory
- [ ] Create `frontend/src/presentation/containers/` directory (if doesn't exist)
- [ ] Create `frontend/src/presentation/components/atoms/` directory
- [ ] Create `frontend/src/presentation/components/molecules/` directory
- [ ] Create `frontend/src/presentation/components/organisms/` directory
- [ ] Create feature subdirectories in `presentation/api/v1/`:
  - [ ] `presentation/api/v1/auth/`
  - [ ] `presentation/api/v1/appointments/`
  - [ ] `presentation/api/v1/users/`
  - [ ] `presentation/api/v1/staff/`
  - [ ] `presentation/api/v1/services/`
  - [ ] `presentation/api/v1/dashboard/`
  - [ ] `presentation/api/v1/reports/`
  - [ ] `presentation/api/v1/budget/`
  - [ ] `presentation/api/v1/bookings/`
  - [ ] `presentation/api/v1/settings/`

### 0.2 Verify Existing Layers (No Changes)
- [ ] Confirm `domain/` layer complete and unchanged
- [ ] Confirm `application/` layer complete and unchanged
- [ ] Confirm `infrastructure/` layer complete and unchanged
- [ ] Confirm `shared/` layer complete and unchanged

### 0.3 Create Git Tags for Safety
```bash
git tag -a phase-0-start -m "Before Phase 0 prep"
```
- [ ] Tag created

### 0.4 Create Documentation
- [ ] Copy FILE_MAPPING.md to project root
- [ ] Copy IMPORT_RULES.md to project root
- [ ] Copy this MIGRATION_CHECKLIST.md to project root
- [ ] Create REFACTORING_PROGRESS.md (track completed items)

---

## 🟩 PHASE 1: EXTRACT PRESENTATION LAYER (Estimated: 8-10 hours)

### 1.1 Move Pages to presentation/pages/
**Files**: 13 .tsx files from `src/pages/`

#### Subphase 1.1a: Move "Clean" Pages (No Refactor)
These pages have no direct infrastructure imports:
- [ ] Dashboard.tsx → presentation/pages/dashboard-page.tsx
- [ ] Calendar.tsx → presentation/pages/appointments-page.tsx
- [ ] Reports.tsx → presentation/pages/reports-page.tsx
- [ ] Budget.tsx → presentation/pages/budget-page.tsx
- [ ] Services.tsx → presentation/pages/services-page.tsx
- [ ] Staff.tsx → presentation/pages/staff-page.tsx
- [ ] Users.tsx → presentation/pages/users-page.tsx
- [ ] Settings.tsx → presentation/pages/settings-page.tsx
- [ ] PublicBooking.tsx → presentation/pages/public-booking-page.tsx

**For each**:
- [ ] Copy file to new location with kebab-case name
- [ ] Verify imports still work (path aliases correct)
- [ ] Test in browser (if possible)
- [ ] Create git commit

#### Subphase 1.1b: Move "Needs Refactor" Pages (Remove infra imports)
These import `apiClient` directly - must refactor:
- [ ] Login.tsx → presentation/pages/login-page.tsx
  - [ ] Remove: `import { apiClient }`
  - [ ] Add: `import { UserService } from '@application/services'`
  - [ ] Replace apiClient calls with userService calls
  - [ ] Add dependency injection in container
- [ ] Register.tsx → presentation/pages/register-page.tsx
  - [ ] Remove: `import { apiClient }`
  - [ ] Add: `import { UserService } from '@application/services'`
  - [ ] Refactor API calls
  - [ ] Add dependency injection
- [ ] ForgotPassword.tsx → presentation/pages/forgot-password-page.tsx
  - [ ] Remove: `import { apiClient }`
  - [ ] Refactor API calls
  - [ ] Add dependency injection
- [ ] ResetPassword.tsx → presentation/pages/reset-password-page.tsx
  - [ ] Remove: `import { apiClient }`
  - [ ] Refactor API calls
  - [ ] Add dependency injection

**For each refactored page**:
- [ ] Copy file
- [ ] Remove infrastructure imports
- [ ] Add application service imports
- [ ] Update API calls to use services
- [ ] Update imports in other files that reference this page
- [ ] Create git commit

### 1.2 Move Components to presentation/components/
**Files**: 2 + new components from features/

#### Subphase 1.2a: Move Existing Components
- [ ] Icon2000s.tsx → presentation/components/atoms/icon-2000s.tsx
- [ ] Sidebar.tsx → presentation/components/organisms/sidebar.tsx
- [ ] Delete empty `components/ui/` directory
- [ ] Create atom index file: `presentation/components/atoms/index.ts`
  - [ ] Export icon-2000s
  - [ ] Add skeleton exports for button, input, badge, etc.
- [ ] Create molecules index file: `presentation/components/molecules/index.ts`
- [ ] Create organisms index file: `presentation/components/organisms/index.ts`
- [ ] Create root index file: `presentation/components/index.ts`

#### Subphase 1.2b: Extract Components from Organisms (if needed)
If there are shared components in booking wizard or forms:
- [ ] Identify reusable components in features/
- [ ] Move to presentation/components/{atoms|molecules|organisms}
- [ ] Update imports in features files

### 1.3 Move Layouts to presentation/layouts/
**Files**: 1 existing + 2 new to create

- [ ] AdminLayout.tsx → presentation/layouts/admin-layout.tsx
- [ ] Create AuthLayout.tsx → presentation/layouts/auth-layout.tsx
  - [ ] Wrapper for /login, /register, /forgot-password, /reset-password
  - [ ] No sidebar, minimal header
  - [ ] Centered form container
- [ ] Create PublicLayout.tsx → presentation/layouts/public-layout.tsx
  - [ ] For /booking/:slug public booking
  - [ ] No admin UI, public-facing only
- [ ] Create index.ts for layouts
  - [ ] Export all layouts

### 1.4 Update presentation/context/
**Currently empty, will have moved context**

- [ ] Move `features/auth/context.tsx` → `presentation/context/auth-context.tsx`
  - [ ] Remove: `import { apiClient }`
  - [ ] Add: `import { UserService } from '@application/services'`
  - [ ] Refactor to use service instead of direct API
  - [ ] Keep context provider and useAuth hook
- [ ] Create `presentation/context/store-context.tsx` (empty skeleton)
- [ ] Create `presentation/context/theme-context.tsx` (empty skeleton)
- [ ] Create `presentation/context/index.ts`
  - [ ] Export AuthContext, AuthProvider, useAuthContext

### 1.5 Move Hooks to presentation/hooks/ (& Refactor)
**Files**: 9 existing in features/ + create generic hooks

#### Subphase 1.5a: Move Feature Hooks (Refactor)
Each needs to remove direct infrastructure imports:

- [ ] features/appointments/hooks.ts → presentation/hooks/use-appointments.ts
  - [ ] Audit imports for `apiClient` usage
  - [ ] Replace with AppointmentService injections
  - [ ] Keep React Query structure intact
  - [ ] Test hooks still work
  - [ ] Create git commit

- [ ] features/auth/hooks.ts → presentation/hooks/use-auth.ts
  - [ ] Move useChangePassword hook
  - [ ] Refactor to use AuthService

- [ ] features/budget/hooks.ts → presentation/hooks/use-budget.ts
  - [ ] Refactor infrastructure imports

- [ ] features/dashboard/hooks.ts → presentation/hooks/use-dashboard.ts
  - [ ] Refactor infrastructure imports

- [ ] features/public/hooks.ts → presentation/hooks/use-public-booking.ts
  - [ ] Refactor infrastructure imports

- [ ] features/reports/hooks.ts → presentation/hooks/use-reports.ts
  - [ ] Refactor infrastructure imports

- [ ] features/staff/hooks.ts → presentation/hooks/use-staff.ts
  - [ ] Refactor infrastructure imports

- [ ] features/stores/hooks.ts → presentation/hooks/use-store.ts
  - [ ] Refactor infrastructure imports

- [ ] features/booking/types.ts → presentation/types/booking-types.ts (or presentation/hooks/)
  - [ ] Move types file

**For each hook refactored**:
- [ ] Remove apiClient import
- [ ] Add service import from @application/services
- [ ] Update query/mutation functions to use service
- [ ] Verify React Query syntax still correct
- [ ] Create git commit

#### Subphase 1.5b: Create Generic Presentation Hooks
These are new, used across components:

- [ ] Create `presentation/hooks/use-form.ts`
  - [ ] Wrapper around React Hook Form
  - [ ] Handles validation with Zod
  - [ ] Provides form state + errors

- [ ] Create `presentation/hooks/use-async.ts`
  - [ ] Generic async state management
  - [ ] Loading, error, data states
  - [ ] Independent of React Query (for non-query async)

- [ ] Create `presentation/hooks/use-debounce.ts`
  - [ ] Debounce hook for search/filter inputs

- [ ] Create `presentation/hooks/use-local-storage.ts`
  - [ ] localStorage state management

- [ ] Create `presentation/hooks/index.ts`
  - [ ] Export all hooks

### 1.6 Verify Containers
**Containers already in presentation/, just rename for consistency**

- [ ] Rename CalendarContainer.tsx → appointments-container.tsx
- [ ] Rename UserManagementContainer.tsx → user-management-container.tsx
- [ ] Rename StaffManagementContainer.tsx → staff-management-container.tsx
- [ ] Rename ServiceManagementContainer.tsx → service-management-container.tsx
- [ ] Create `presentation/containers/booking-container.tsx` (if needed for public booking)
- [ ] Create `presentation/containers/auth-container.tsx` (for login/register flows)
- [ ] Update all imports in pages to use new names
- [ ] Create `presentation/containers/index.ts` to export all

### 1.7 Update App.tsx (Prepare for Phase 2)
- [ ] Create backup: `App.tsx.backup`
- [ ] Update page imports to use new paths
  - [ ] `import { DashboardPage } from '@presentation/pages'`
  - [ ] Update all 13 page imports
- [ ] Update layout imports
  - [ ] `import { AdminLayout, AuthLayout, PublicLayout } from '@presentation/layouts'`
- [ ] Keep routing structure the same for now (will refactor in Phase 3)

### 1.8 Run Tests & Verification
- [ ] No TypeScript compilation errors: `npm run build`
- [ ] Dev server starts: `npm run dev`
- [ ] All pages load without errors
- [ ] No missing import errors in console

### 1.9 Create Phase 1 Checkpoint
```bash
git tag -a phase-1-complete -m "Presentation layer extracted"
git commit -m "Phase 1: Extract presentation layer"
```
- [ ] Tag created
- [ ] Commit created

---

## 🟨 PHASE 2: CREATE ROUTERS (Estimated: 8-12 hours)

### 2.1 Create Router Structure
- [ ] Create `presentation/api/v1/index.ts` (aggregator)
- [ ] Create `presentation/api/v1/middleware/auth-middleware.ts`
  - [ ] ProtectedRoute component logic
  - [ ] Session validation
  - [ ] Redirect to login if needed

### 2.2 Create Feature Routers (One for Each Domain)

#### 2.2.1 Auth Router
- [ ] Create `presentation/api/v1/auth/router.tsx`
  - [ ] /login route (LoginPage)
  - [ ] /register route (RegisterPage)
  - [ ] /forgot-password route (ForgotPasswordPage)
  - [ ] /reset-password route (ResetPasswordPage)
  - [ ] All protected: false (public)
- [ ] Create `presentation/api/v1/auth/dependencies.ts`
  - [ ] Export AuthService instance
  - [ ] Export UserService instance
  - [ ] Export repositories
- [ ] Create `presentation/api/v1/auth/__tests__/router.test.tsx`
  - [ ] Test route exists
  - [ ] Test component renders

#### 2.2.2 Appointments Router
- [ ] Create `presentation/api/v1/appointments/router.tsx`
  - [ ] /dashboard/calendar route
  - [ ] Protected: true
- [ ] Create `presentation/api/v1/appointments/dependencies.ts`
  - [ ] AppointmentService instance
- [ ] Create `presentation/api/v1/appointments/__tests__/router.test.tsx`

#### 2.2.3 Users Router
- [ ] Create `presentation/api/v1/users/router.tsx`
  - [ ] /dashboard/users route
  - [ ] Protected: true
- [ ] Create `presentation/api/v1/users/dependencies.ts`
  - [ ] UserService instance
- [ ] Create tests

#### 2.2.4 Staff Router
- [ ] Create `presentation/api/v1/staff/router.tsx`
  - [ ] /dashboard/staff route
  - [ ] Protected: true
- [ ] Create `presentation/api/v1/staff/dependencies.ts`
- [ ] Create tests

#### 2.2.5 Services Router
- [ ] Create `presentation/api/v1/services/router.tsx`
  - [ ] /dashboard/services route
  - [ ] Protected: true
- [ ] Create `presentation/api/v1/services/dependencies.ts`
- [ ] Create tests

#### 2.2.6 Dashboard Router
- [ ] Create `presentation/api/v1/dashboard/router.tsx`
  - [ ] /dashboard root route
  - [ ] Protected: true
- [ ] Create dependencies
- [ ] Create tests

#### 2.2.7 Reports Router
- [ ] Create `presentation/api/v1/reports/router.tsx`
  - [ ] /dashboard/reports route
  - [ ] Protected: true
- [ ] Create dependencies
- [ ] Create tests

#### 2.2.8 Budget Router
- [ ] Create `presentation/api/v1/budget/router.tsx`
  - [ ] /dashboard/budget route
  - [ ] Protected: true
- [ ] Create dependencies
- [ ] Create tests

#### 2.2.9 Bookings Router (Public)
- [ ] Create `presentation/api/v1/bookings/router.tsx`
  - [ ] /booking/:slug route
  - [ ] /b/:slug route (alias)
  - [ ] Protected: false (public)
- [ ] Create `presentation/api/v1/bookings/dependencies.ts`
- [ ] Create tests

#### 2.2.10 Settings Router
- [ ] Create `presentation/api/v1/settings/router.tsx`
  - [ ] /dashboard/settings route
  - [ ] Protected: true
- [ ] Create dependencies
- [ ] Create tests

### 2.3 Update Main Router (App.tsx)
- [ ] Replace inline routes with router imports
- [ ] Change from `<BrowserRouter>` to `<RouterProvider>`
- [ ] Import all feature routers
- [ ] Combine into single app router
- [ ] Test routing still works
- [ ] All 13 page routes accessible

### 2.4 Dependency Injection Points
- [ ] Document which services injected in each router
- [ ] Create service instances in dependencies.ts files
- [ ] Use consistent pattern across all routers
- [ ] Add TypeScript types for dependency objects

### 2.5 Error Middleware
- [ ] Create `presentation/api/middleware/error-middleware.ts`
  - [ ] Global error boundary
  - [ ] Error page component
  - [ ] Error logging

### 2.6 Auth Middleware
- [ ] Move ProtectedRoute logic to `presentation/api/middleware/auth-middleware.ts`
  - [ ] Check token validity
  - [ ] Check user permissions
  - [ ] Redirect to login if needed
  - [ ] Loading state

### 2.7 Update Context Providers
- [ ] Wrap app with AuthProvider
- [ ] Wrap app with QueryClientProvider (React Query)
- [ ] Wrap app with ThemeProvider (if exists)
- [ ] Correct order: App → Auth → Query → Theme

### 2.8 Run Tests
- [ ] `npm run build` - no errors
- [ ] `npm run dev` - server starts
- [ ] All routes accessible
- [ ] Protected routes redirect when logged out
- [ ] Public routes always accessible
- [ ] Dependency injection working

### 2.9 Create Phase 2 Checkpoint
```bash
git tag -a phase-2-complete -m "Routers created and integrated"
git commit -m "Phase 2: Create routers and middleware"
```
- [ ] Tag created

---

## 🟧 PHASE 3: DELETE FEATURES & CLEANUP (Estimated: 1-2 hours)

### 3.1 Verify All Features Migrated
Before deleting features/, confirm:
- [ ] All hooks moved to presentation/hooks/
- [ ] All context moved to presentation/context/
- [ ] All types moved to presentation/ or shared/
- [ ] All components either deleted or moved to presentation/components/
- [ ] No imports from features/ remain

### 3.2 Find & Update All imports from features/
```bash
grep -r "from.*features" frontend/src/
```
- [ ] Update all found imports to new paths
- [ ] Replace hooks imports: `@features/` → `@presentation/hooks/`
- [ ] Replace context imports: `@features/` → `@presentation/context/`
- [ ] Replace types imports: `@features/` → `@presentation/types/`

### 3.3 Delete features/ Directory
```bash
rm -rf frontend/src/features/
```
- [ ] features/ directory deleted
- [ ] Verify from git status

### 3.4 Delete Old pages/ Directory
```bash
rm -rf frontend/src/pages/
```
- [ ] pages/ directory deleted

### 3.5 Delete Old layouts/ Directory
```bash
rm -rf frontend/src/layouts/
```
- [ ] layouts/ directory deleted

### 3.6 Delete Old components/ Directory (keep only what's moved)
- [ ] If empty after moving to presentation/, delete
- [ ] If has remaining files, verify they're moved
- [ ] Delete empty directory

### 3.7 Verify No Broken Imports
```bash
npm run build
```
- [ ] Zero build errors
- [ ] Zero TypeScript errors
- [ ] No "module not found" errors

### 3.8 Create Phase 3 Checkpoint
```bash
git tag -a phase-3-complete -m "Features directory deleted, cleanup complete"
git commit -m "Phase 3: Delete legacy directories"
```
- [ ] Tag created

---

## 🔵 PHASE 4: TESTING & VALIDATION (Estimated: 4-6 hours)

### 4.1 Dependency Rule Verification
```bash
npm install -D eslint-plugin-import
```
- [ ] ESLint plugin installed
- [ ] Run eslint with import rules
- [ ] All violations fixed

### 4.2 Circular Dependency Check
```bash
npm install -D ts-prune
npx ts-prune
```
- [ ] Run ts-prune
- [ ] Fix any circular imports
- [ ] Verify clean output

### 4.3 Type Safety Check
```bash
npm run build -- --noEmit
```
- [ ] Zero TypeScript errors
- [ ] Strict mode enabled
- [ ] All types correct

### 4.4 Manual Testing
- [ ] Dev server starts without errors: `npm run dev`
- [ ] All pages load and render
- [ ] All routes work correctly
- [ ] Protected routes enforce authentication
- [ ] Public routes accessible without auth
- [ ] Authentication flow works (login/logout/register)
- [ ] API calls still work (via services)
- [ ] Forms submit correctly
- [ ] Validation works on forms
- [ ] Errors display correctly
- [ ] No console warnings/errors

### 4.5 Unit Tests
- [ ] Create tests for utility functions
- [ ] Create tests for domain entities (if not existing)
- [ ] Create tests for application services (if not existing)
- [ ] Coverage > 60%
- [ ] All tests pass: `npm test`

### 4.6 Integration Tests
- [ ] Test container components with mock services
- [ ] Test complete flows (auth, CRUD operations)
- [ ] Test error handling
- [ ] Coverage > 40%

### 4.7 E2E Tests (if using Cypress/Playwright)
- [ ] Login flow test
- [ ] CRUD flow test (create, read, update, delete)
- [ ] Navigation test
- [ ] All tests pass

### 4.8 Performance Check
- [ ] Build size not significantly increased
- [ ] Dev server hot reload still fast (~500ms)
- [ ] No performance regressions

### 4.9 Create Phase 4 Checkpoint
```bash
git tag -a phase-4-complete -m "Testing and validation complete"
git commit -m "Phase 4: Testing and validation"
```
- [ ] Tag created

---

## 📚 PHASE 5: DOCUMENTATION (Estimated: 3-4 hours)

### 5.1 Update README.md
- [ ] Add new architecture section
- [ ] Add folder structure diagram
- [ ] Add getting started guide
- [ ] Update development instructions
- [ ] Update build/deploy instructions
- [ ] Link to PURE_CLEAN_ARCHITECTURE.md

### 5.2 Create PURE_CLEAN_ARCHITECTURE.md
- [ ] Explain the 4-layer model
- [ ] Diagram layer boundaries
- [ ] Show allowed/forbidden imports
- [ ] Provide examples for each layer
- [ ] Include testing strategy

### 5.3 Create API_STRUCTURE.md
- [ ] Document all routes
- [ ] Show router organization
- [ ] Document middleware stack
- [ ] Show dependency injection pattern

### 5.4 Update CONTRIBUTING.md (if exists)
- [ ] Add new feature guidelines
- [ ] Add layer model explanation
- [ ] Add commit message conventions
- [ ] Add PR checklist

### 5.5 Create LAYER_GUIDELINES.md
- [ ] Domain layer: how to write entities/use-cases
- [ ] Application layer: how to write services
- [ ] Infrastructure layer: how to write repositories
- [ ] Presentation layer: how to write components
- [ ] Testing each layer

### 5.6 Document Dependencies Injection
- [ ] Explain DI pattern used
- [ ] Show examples per layer
- [ ] Document how to add new service
- [ ] Document how to swap implementations (for testing)

### 5.7 Create Phase 5 Checkpoint
```bash
git tag -a phase-5-complete -m "Documentation updated"
git commit -m "Phase 5: Documentation updates"
```
- [ ] Tag created

---

## 🎉 FINAL VERIFICATION

### Final Checklist
- [ ] All 6 phases complete
- [ ] Zero ESLint violations
- [ ] Zero TypeScript errors
- [ ] All tests passing
- [ ] All pages load correctly
- [ ] Features/ directory deleted
- [ ] Legacy pages/, layouts/ directories deleted
- [ ] Documentation updated
- [ ] Team trained on new structure
- [ ] Git tags created at each phase
- [ ] Deployment tested on staging

### Success Criteria Met?
- [ ] ✅ No imports violate Dependency Rule
- [ ] ✅ Domain/ has ZERO external dependencies
- [ ] ✅ Application/ imports from domain/ + infrastructure/ only
- [ ] ✅ Infrastructure/ implements domain/ interfaces
- [ ] ✅ Presentation/ imports application/ services + domain/ entities
- [ ] ✅ `features/` directory deleted entirely
- [ ] ✅ Routers in `presentation/api/v1/` (Express-like structure)
- [ ] ✅ Tests >60% coverage per layer
- [ ] ✅ No circular dependencies
- [ ] ✅ TypeScript strict mode
- [ ] ✅ All team members understand layer model

### Go/No-Go Decision
- [ ] **GO**: All criteria met, ready for production
- [ ] **NO-GO**: Issues found, address before proceeding

---

## Timeline Summary

| Phase | Tasks | Duration | Status |
|-------|-------|----------|--------|
| **Phase 0** | Prep & dirs | 3 hrs | ⏳ Not started |
| **Phase 1** | Extract presentation | 8-10 hrs | ⏳ Not started |
| **Phase 2** | Create routers | 8-12 hrs | ⏳ Not started |
| **Phase 3** | Cleanup | 1-2 hrs | ⏳ Not started |
| **Phase 4** | Testing | 4-6 hrs | ⏳ Not started |
| **Phase 5** | Documentation | 3-4 hrs | ⏳ Not started |
| **TOTAL** | **All phases** | **27-37 hrs** | — |

**Team capacity**: 
- 1 dev full-time: 6-7 days
- 2 devs: 3-4 days (in parallel where possible)
- 3 devs focused: 2 days

