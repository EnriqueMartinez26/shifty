# Plan de Auditoria para el Backend

## Objetivo

Reducir codigo muerto, duplicado y obsoleto del backend sin romper runtime, migraciones, seeds o tests que siguen siendo fuente de verdad.

## Alcance

Trabajar en:

- `backend/main.py`
- `backend/api/index.py`
- `backend/core/*`
- `backend/modules/*`
- `backend/scripts/*`
- `backend/tests/*`
- `backend/alembic/*`
- docs operativas de backend

No tocar frontend salvo enlaces documentales compartidos.

## Paradigmas a validar

### 3NF

Auditar:

- tablas y columnas calculadas
- campos redundantes persistidos
- dependencias transitivas
- datos de negocio duplicados entre modelo y property

### RLS

Auditar:

- tablas multi-tenant
- policies activas
- enforcement en runtime real
- bypasses de superadmin o scripts

### Arquitectura modular

Auditar:

- routers montados en `main.py`
- módulos que existen pero no entran al runtime
- shims legacy de arranque
- scripts manuales viejos

## Secuencia de trabajo

### Paso 1. Confirmar entrypoints reales

Verificar:

- `backend/main.py`
- `backend/api/index.py`
- `backend/pyproject.toml`
- `backend/Dockerfile`
- `backend/vercel.json`

### Paso 2. Barrido de routers y módulos

Buscar:

- routers no montados
- módulos `public_api` o `presentation` legacy
- submodulos solo referenciados por docs viejas

### Paso 3. Barrido de scripts

Clasificar scripts como:

- operativo vigente
- seed/test helper vigente
- legacy manual
- borrable

### Paso 4. Barrido de docs

Clasificar documentos como:

- fuente vigente
- referencia historica
- backlog viejo

Archivar lo historico. No borrar lo que explica contratos todavía activos.

### Paso 5. Barrido de datos

Revisar:

- migraciones que restauran contratos
- modelos que siguen existiendo solo para tests/seeds
- tablas que ya no tienen ruta de acceso

## Criterio de borrado

Solo borrar si:

- no hay consumidor runtime
- no hay consumidor de tests
- no participa en migraciones activas
- no participa en scripts operativos
- no es documentacion vigente

Si participa en alguno de esos grupos, refactorizar o archivar.

## Orden recomendado

1. entrypoints y shims duplicados
2. routers y módulos huérfanos
3. scripts manuales obsoletos
4. docs históricas
5. modelos o helpers de apoyo ya no usados

## Verificacion

Después de cada bloque:

- `rg -n "nombre-del-archivo-o-modulo" backend`
- `pytest` relevante
- smoke check de entrypoints si aplica

## Entregable esperado

Al finalizar, devolver:

- lista de archivos borrados
- lista de archivos refactorizados
- lista de archivos archivados
- riesgos abiertos
- verificaciones ejecutadas

