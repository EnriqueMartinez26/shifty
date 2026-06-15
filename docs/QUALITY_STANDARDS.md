# Quality Standards

## Scope

These standards apply to every change in the repo. A PR is not acceptable if it introduces a new layer violation, skips required checks, or depends on undocumented local steps.

## Global Rules

- Keep import directions explicit and layered.
- Do not add new `any` types when a typed DTO, `unknown`, or a domain object is available.
- Prefer one source of truth for validation, errors, and API contracts.
- Treat lint warnings as failures; the repo standard is zero warnings.
- Preserve runtime consumers, tests, migrations, scripts, and docs that are still active.
- If a file is historical only, archive it instead of leaving it in the active surface.

## Frontend Standards

### Presentation

- Own UI composition, view state, and user interaction only.
- Do not instantiate repositories or HTTP clients directly in components.
- Use semantic HTML first, then ARIA only when native semantics are not enough.
- Every form field must have a real label association.
- Loading, success, and error states must be announced with `role="status"` or `role="alert"` when appropriate.

Acceptance:

- `npm run check`
- `npm test`
- `npm run build`

### Application

- Own orchestration and use-case coordination only.
- Keep API calls behind services or repositories.
- Keep DTOs and service contracts typed.
- Do not import from presentation layers.

Acceptance:

- `npm run typecheck`
- `npm run lint`
- `npm run dead-code`

### Infrastructure

- Own API clients, repositories, DI containers, and adapters only.
- Do not import from presentation.
- Keep transport errors normalized before they reach UI.

Acceptance:

- `npm run typecheck`
- `npm run lint`

### Shared

- Keep utilities, cross-cutting error helpers, shared types, and generic contracts only.
- Do not put feature-specific behavior here.

Acceptance:

- `npm run check`
- `npm test`

## Backend Standards

### Domain

- No FastAPI, HTTP, database, or framework imports.
- Keep business rules, entities, value objects, and exceptions pure.

Acceptance:

- `uv run ruff check .`
- `uv run mypy .`

### Application

- Own use cases, service orchestration, and validation boundaries.
- Keep transport and persistence out of this layer.

Acceptance:

- `uv run ruff format --check .`
- `uv run ruff check .`
- `uv run mypy .`

### Infrastructure

- Own database, cache, message bus, storage, and external integrations.
- Do not import presentation-layer code.

Acceptance:

- `uv run ruff format --check .`
- `uv run ruff check .`
- `uv run mypy .`

### API and Modules

- Routers should only wire request/response flow and call application services.
- Keep route modules thin and explicit.

Acceptance:

- `uv run python -c "from main import app; app.openapi()"`
- `uv run alembic heads`

## Validation Gates

### Local

- `frontend`: `npm run check`, `npm test`, `npm run build`
- `backend`: `uv run ruff format --check .`, `uv run ruff check .`, `uv run mypy .`, `uv run pytest`

### CI

The pipeline must fail on:

- frontend format, lint, typecheck, dead-code, or test failures
- backend format, lint, typecheck, migration validation, or integration test failures
- hook-equivalent standard checks failing

## Commit Policy

- Commits are blocked locally by the Git hook in `.githooks/pre-commit`.
- The hook mirrors the standard checks instead of relying on manual discipline.
- In a fresh clone, enable it with `git config core.hooksPath .githooks`.
- If the hook fails, fix the code or update the standard explicitly before committing.
