# Plan de Auditoria para el Frontend

## Objetivo

Reducir masa del frontend sin romper la arquitectura activa.

La regla no es "borrar mucho". La regla es:

1. confirmar consumidor real
2. clasificar segun paradigma
3. eliminar solo lo huérfano
4. refactorizar lo que sigue vivo pero viola capas

## Alcance

Trabajar solo en:

- `frontend/src/presentation`
- `frontend/src/application`
- `frontend/src/infrastructure`
- `frontend/src/shared`
- `frontend/scripts`
- `frontend/src/App.tsx`

No tocar backend, docs de backend ni migraciones.

## Paradigmas a validar

### Clean Architecture

El frontend declara capas:

- `domain`
- `application`
- `infrastructure`
- `presentation`
- `shared`

La verificacion obligatoria es:

- `frontend/scripts/verify-clean-architecture.ts`
- reglas de ESLint en `frontend/eslint.config.mjs`

### POO / estructuracion

Auditar:

- duplicacion de hooks
- componentes que instancian servicios o repositorios adentro
- barrels sin consumidores
- helpers duplicados
- paginas que no entran al router real

### Consumo real

Un archivo solo se conserva si aparece en alguno de estos grupos:

- runtime activo en `App.tsx`
- importado por otro archivo vivo
- usado por tests
- requerido por scripts
- requerido por build o lint

Si no entra en ninguno, es candidato a borrar o archivar.

## Secuencia de trabajo

### Paso 1. Confirmar baseline

Ejecutar:

```bash
npm run dead-code
npm run lint
npm run typecheck
npm test
```

### Paso 2. Barrido de rutas activas

Revisar:

- `frontend/src/App.tsx`
- `frontend/src/presentation/layouts/*`
- `frontend/src/presentation/pages/*`
- `frontend/src/presentation/containers/*`

Todo lo que no entre en el router real o en una ruta hija debe marcarse como huérfano.

### Paso 3. Barrido de duplicados

Buscar y resolver:

- `useService` duplicado
- `lib/utils.ts` duplicado contra `shared/utils/cn.ts`
- `hooks/index.ts` sin consumidores
- `infrastructure/di/index.ts` sin consumidores
- páginas o hooks que ya quedaron reemplazados

### Paso 4. Barrido de hooks

Clasificar cada hook como:

- `vivo y correcto`
- `vivo pero refactorizable`
- `huérfano`

Regla:

- si el hook hace HTTP directo y pertenece a UI, moverlo a servicio o dejarlo solo si no hay alternativa inmediata
- si el hook no tiene consumidores, borrar

### Paso 5. Barrido de componentes

Buscar componentes que:

- instancian servicios/repositories manualmente
- mezclan UI con orquestación
- dependen de pages huérfanas

Esos se refactorizan si siguen en el flujo real.

### Paso 6. Barrido de docs y guardrails

No borrar:

- `verify-clean-architecture.ts`
- docs vigentes que expliquen arquitectura activa

Archivar:

- docs históricas
- guias que describen una estructura ya reemplazada

## Criterio de borrado

Solo borrar si:

- `rg` devuelve cero consumidores relevantes
- no participa en tests
- no participa en scripts
- no participa en build o lint
- no es fuente de verdad documental

Si hay dudas, marcar como `refactorizar` o `archivar`.

## Orden recomendado

1. hooks y barrels muertos
2. duplicados de utilidades
3. paginas huérfanas
4. componentes fuera del router real
5. docs de frontend que ya no reflejan el estado actual

## Comandos de verificacion

Después de cada bloque:

```bash
npm run dead-code
npm run lint
npm run typecheck
npm test
```

Y además:

```bash
rg -n "nombre-del-archivo-o-hook" frontend/src
```

## Entregable esperado

Al finalizar, devolver:

- lista de archivos borrados
- lista de archivos refactorizados
- lista de archivos archivados
- lista de riesgos abiertos
- salida de verificaciones corridas

