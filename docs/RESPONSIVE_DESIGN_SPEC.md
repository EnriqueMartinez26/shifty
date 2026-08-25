# Especificación: diseño responsivo del frontend

## Estado actual (starting state)
- Frontend: React 19 + TypeScript + Vite
- Estado/datos: TanStack Query, React Router, React Hook Form, Zod, Axios
- Estilos: Tailwind CSS 4
- Tests: Jest + Testing Library
- Calidad: ESLint + Prettier
- El backend (FastAPI, Celery, PostgreSQL, Redis, RabbitMQ, Docker, Nginx) NO forma parte de esta tarea bajo ninguna circunstancia.

## Estado objetivo (target state)
Todas las pantallas y componentes existentes se ven y funcionan correctamente en estos breakpoints, sin scroll horizontal ni overlaps:
- Mobile: 375px
- Tablet: 768px
- Desktop: 1280px
- Desktop grande: 1440px+

La estructura de carpetas, nombres de componentes, convenciones de naming y organización del proyecto **se mantienen exactamente igual**. Esto es una adaptación de estilos, no una refactorización.

## Alcance permitido (scope lock)
- SOLO podés editar archivos dentro de `src/` relacionados a: componentes, layouts, páginas, y clases de Tailwind.
- Podés editar `tailwind.config.*` únicamente si es estrictamente necesario para breakpoints/tokens, y solo después de pedir confirmación (ver "Detenerse y preguntar antes de").
- NO toques: `backend/`, `docker-compose*`, `nginx/`, archivos de CI/CD, `package.json` (salvo que sea imprescindible y con confirmación previa), lógica de negocio (llamadas Axios, schemas Zod, hooks de React Query, validaciones de React Hook Form).

## Reglas obligatorias (MUST / MUST NOT)
- MUST usar utilidades responsivas nativas de Tailwind (`sm:`, `md:`, `lg:`, `xl:`, `2xl:`) con enfoque mobile-first.
- MUST preservar la jerarquía de componentes y props existentes.
- MUST NOT introducir librerías nuevas de UI o CSS (nada de agregar Bootstrap, MUI, styled-components, etc.).
- MUST NOT cambiar lógica de negocio, tipos, o contratos de API.
- MUST NOT renombrar archivos, carpetas o componentes.
- Solo hacé los cambios directamente pedidos. No refactorices ni agregues features fuera de esto.

## Proceso sugerido
1. Auditar `src/` y listar componentes/páginas sin soporte responsivo real (breakpoints ausentes, anchos fijos en px, overflow no controlado).
2. Priorizar por: componentes compartidos/layout global primero, luego páginas de mayor tráfico o complejidad.
3. Implementar mobile-first: definir el layout en el breakpoint más chico y agregar variantes hacia arriba.
4. Verificar visualmente en los 4 breakpoints listados arriba antes de pasar al siguiente archivo.
5. Correr los tests existentes (Jest + Testing Library) después de cada bloque de cambios — no deben romperse.

## Detenerse y preguntar antes de
- Modificar `tailwind.config.*` o cualquier archivo de configuración.
- Agregar cualquier dependencia nueva.
- Tocar un componente compartido que afecte a más de 3 páginas distintas.
- Cambiar cualquier test existente en lugar de solo actualizarlo por un cambio de markup esperado.

## Reporte de progreso
Después de cada archivo modificado, output:
`✅ [ruta del archivo] - [qué se cambió y por qué breakpoint]`

## Criterio de éxito (done when)
- Ningún componente o página tiene scroll horizontal ni overlap visual en 375px, 768px, 1280px y 1440px.
- Los tests existentes siguen pasando sin modificaciones de lógica.
- No se agregaron dependencias nuevas.
- La estructura de carpetas y nombres de archivos es idéntica a la original.
- `ruff`/`eslint`/`prettier` no reportan errores nuevos.

---

**Nota de seguridad agéntica:** este prompt es para una herramienta con acceso real al sistema de archivos y ejecución de comandos. Antes de pegarlo, confirmá que las rutas mencionadas (`src/`, `backend/`, `tailwind.config.*`) coinciden con la estructura real de tu repo, y revisá el scope lock y las condiciones de parada antes de darle luz verde.
