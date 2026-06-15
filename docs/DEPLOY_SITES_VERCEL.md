# Deploy Productivo: Sites + Vercel

Fecha de referencia: 3 de junio de 2026.

Este repo queda preparado para:

- `frontend/` en `Sites`
- `backend/` en `Vercel`
- `PostgreSQL` en `Neon`
- `Redis` en `Upstash`

## Arquitectura final

- `app.tudominio.com`: frontend publicado con `Sites`
- `api.tudominio.com`: backend FastAPI publicado en `Vercel`
- `DATABASE_URL`: connection string pooled de Neon
- `REDIS_URL`: endpoint TLS de Upstash Redis

## 1. Backend en Vercel

Hay dos formas soportadas por este repo:

- desplegar con root `backend/`
- desplegar desde la raiz del repo

La segunda opcion existe para evitar crashes por configuracion de root directory.

Crear un proyecto Vercel nuevo apuntando a la carpeta `backend/`.

Archivos relevantes:

- [vercel.json](/D:/Proyectos/martinez-scienza/shifty/vercel.json)
- [api/index.py](/D:/Proyectos/martinez-scienza/shifty/api/index.py)
- [requirements.txt](/D:/Proyectos/martinez-scienza/shifty/requirements.txt)
- [backend/.env.production.example](/D:/Proyectos/martinez-scienza/shifty/backend/.env.production.example)
- [backend/.env.vercel.import](/D:/Proyectos/martinez-scienza/shifty/backend/.env.vercel.import)
- [backend/main.py](/D:/Proyectos/martinez-scienza/shifty/backend/main.py)
- [backend/vercel.json](/D:/Proyectos/martinez-scienza/shifty/backend/vercel.json)
- [backend/.vercelignore](/D:/Proyectos/martinez-scienza/shifty/backend/.vercelignore)

### Variables requeridas

Tomar como base [backend/.env.production.example](/D:/Proyectos/martinez-scienza/shifty/backend/.env.production.example).

Si ya estas usando este repo y queres importar una configuracion lista para el backend actual, usar directamente [backend/.env.vercel.import](/D:/Proyectos/martinez-scienza/shifty/backend/.env.vercel.import).

Variables mínimas:

- `ENV=production`
- `SECRET_KEY`
- `FIELD_ENCRYPTION_KEY`
- `DATABASE_URL`
- `REDIS_URL`
- `SMTP_HOST`
- `SMTP_PORT`
- `SMTP_USER`
- `SMTP_PASS`
- `EMAILS_FROM_EMAIL`
- `FRONTEND_URL=https://app.tudominio.com`
- `PUBLIC_API_URL=https://api.tudominio.com`
- `CORS_ORIGINS=https://app.tudominio.com`
- `COOKIE_SECURE=true`
- `EXPOSE_API_DOCS=false`
- `ALLOW_PUBLIC_REGISTRATION=false`
- `CRON_SECRET`
- `VERCEL_QUEUE_REGION` opcional. Dejar vacio si no activaste Queues.
- `RUN_RUNTIME_CONTRACTS_ON_STARTUP=false`

### Neon

Usar el pooler serverless de Neon.

Formato esperado:

```env
DATABASE_URL=postgresql+asyncpg://USER:PASSWORD@ep-xxxx-pooler.us-east-1.aws.neon.tech/DBNAME?ssl=require
```

### Upstash

Usar la URL TLS completa.

Formato esperado:

```env
REDIS_URL=rediss://default:PASSWORD@HOST:6379
```

### Deploy backend

1. Crear proyecto en Vercel.
2. Elegir una de estas configuraciones:
   - recomendada: root `backend/`
   - alternativa segura: root repo completo, usando [vercel.json](/D:/Proyectos/martinez-scienza/shifty/vercel.json) y [api/index.py](/D:/Proyectos/martinez-scienza/shifty/api/index.py)
3. Cargar variables.
4. Deploy.
5. Validar:
   - `GET /`
   - `GET /ops/health/live`
   - `GET /ops/health/ready`

### Si aparece `FUNCTION_INVOCATION_FAILED`

La causa mas comun en este repo es que Vercel no haya instalado dependencias Python del backend.

Checklist:

1. Verificar que el proyecto use root `backend/`, o que este tomando [requirements.txt](/D:/Proyectos/martinez-scienza/shifty/requirements.txt) en la raiz.
2. Verificar que `SECRET_KEY`, `DATABASE_URL`, `REDIS_URL` y `SMTP_*` existan.
3. Verificar que `ENV=production` no entre en conflicto con envs faltantes como `CRON_SECRET` o `FIELD_ENCRYPTION_KEY`.
4. Mirar logs de la funcion y buscar errores tipo `ModuleNotFoundError: fastapi`, `pydantic`, `asyncpg` o `ValidationError` de settings.

## 2. Frontend en Sites

El frontend ya construye al formato esperado por Sites:

- `dist/client/**`
- `dist/server/index.js`

Archivos relevantes:

- [frontend/package.json](/D:/Proyectos/martinez-scienza/shifty/frontend/package.json)
- [frontend/scripts/build-sites.mjs](/D:/Proyectos/martinez-scienza/shifty/frontend/scripts/build-sites.mjs)
- [.openai/hosting.json](/D:/Proyectos/martinez-scienza/shifty/.openai/hosting.json)

### Variable requerida

Tomar como base [frontend/.env.example](/D:/Proyectos/martinez-scienza/shifty/frontend/.env.example).
Para produccion usar [frontend/.env.production.example](/D:/Proyectos/martinez-scienza/shifty/frontend/.env.production.example).

```env
VITE_API_URL=https://api.tudominio.com
```

### Deploy frontend

1. Crear proyecto `Sites`.
2. Root recomendado: `frontend/`.
3. Build command:

```bash
npm run build
```

4. Cargar `VITE_API_URL`.
5. Publicar y asociar `app.tudominio.com`.

## 3. Dominio y CORS

Configurar:

- `app.tudominio.com` -> `Sites`
- `api.tudominio.com` -> `Vercel`

En backend:

- `FRONTEND_URL=https://app.tudominio.com`
- `PUBLIC_API_URL=https://api.tudominio.com`
- `CORS_ORIGINS=https://app.tudominio.com`

No dejar `localhost` en producción.

## 4. Colas y jobs

Estado actual del repo:

- confirmaciones: `queue + drain` dentro del request cuando hay token OIDC
- reminders: cron diario en `Vercel` y publicación a cola

Endpoint interno:

- `GET /ops/internal/cron/reminders/schedule`
- `POST /ops/internal/queues/confirmations/drain`
- `POST /ops/internal/queues/reminders/drain`

Todos exigen:

```http
Authorization: Bearer <CRON_SECRET>
```

## 5. Limitación importante

Con `Vercel Hobby`, los cron jobs no sirven bien para recordatorios horarios de precisión.

Consecuencia práctica:

- el booking y el email de confirmación quedan cubiertos
- los reminders 24h no deben considerarse cerrados para producción estricta si seguís en Hobby

Opciones reales:

1. subir a `Vercel Pro`
2. usar un scheduler externo
3. sacar reminders automáticos del alcance inicial

## 6. Smoke test mínimo

Después de ambos deploys validar:

1. abrir `app.tudominio.com`
2. login exitoso
3. `GET /me` indirectamente desde UI
4. abrir `/booking/:slug`
5. crear reserva pública
6. confirmar que no haya error CORS
7. confirmar email de reserva
8. validar `api.tudominio.com/ops/health/ready`

## 7. Pendiente no resuelto

Falta generar la screenshot canónica pedida por el flujo de `Sites`:

- `frontend/public/screenshot.jpeg`

Conviene capturarla cuando el entorno productivo o staging ya esté accesible.
