# Shifty v2 - Contexto Técnico para LLMs

Este documento proporciona una visión general técnica exhaustiva del proyecto **Shifty** para facilitar la asistencia de codificación por parte de IAs.

## 🚀 Visión General
Shifty es un sistema multi-tenant de gestión de turnos diseñado para salones de belleza y servicios similares. Permite a múltiples propietarios de salones gestionar su propia agenda, personal y servicios de forma aislada.

## 🛠 Tech Stack
- **Frontend**: React 18 (Vite), TypeScript, Tailwind CSS, Lucide React (Icons), Axios (API client).
- **Backend**: FastAPI (Python 3.13), SQLAlchemy 2.0 (Async/Asíncrono), PostgreSQL 16+, Redis (Memurai en Windows) para caché e idempotencia.
- **Base de Datos**: PostgreSQL con **Row Level Security (RLS)** para aislamiento estricto de datos.

## 🏗 Arquitectura Core: Multi-Tenancy via RLS
El aislamiento de datos no se hace mediante filtrado manual en cada query, sino a nivel de base de datos:
1. **RLS Policies**: Cada tabla tiene una policy que filtra por `store_id`.
2. **Contexto de Sesión**: El backend utiliza un middleware (`TenantMiddleware`) que extrae el `store_id` del JWT.
3. **Inyección de Variable**: `core/database.py` utiliza `set_config('app.current_store_id', ...)` en cada transacción. La base de datos usa `current_setting('app.current_store_id')` para filtrar las filas automáticamente.

## 🔧 Configuración para Desarrollo en Windows (Crucial)
Se han aplicado parches específicos para evitar bugs conocidos de Python 3.13 y drivers asíncronos en Windows:
- **Migraciones**: Si `asyncpg` falla con `WinError 64`, se utiliza un driver síncrono (`psycopg2`) en `alembic/env.py` solo para las migraciones.
- **Sintaxis SET**: PostgreSQL en Windows/Asyncpg no permite parámetros (`:sid`) en comandos `SET LOCAL`. Se utiliza `SELECT set_config(...)` en su lugar.
- **Redis local**: Se recomienda el uso de **Memurai** como alternativa nativa a Redis en Windows.

## 🔒 Autenticación y Seguridad
- **CORS**: Configurado en `main.py` para permitir peticiones desde el frontend local (`localhost:3000-3005`).
- **JWT**: Contiene `store_id`, `role` y `public_id`. Se encarga de la persistencia del tenant en el frontend.
- **Idempotencia**: Las rutas críticas (como creación de turnos) usan un header `X-Idempotency-Key` y Redis para evitar duplicaciones por reintentos de red.
- **Recuperación de contraseña**: Implementado flujo completo con `POST /auth/forgot-password` y `POST /auth/reset-password`, usando token temporal hasheado en base de datos.

## 📊 Reportes y Exportación
- **Resumen de reportes**: Endpoint `GET /reports/summary` con filtros por rango (`from_date`, `to_date`) y métricas de turnos/ingresos.
- **Exportación obligatoria**: Endpoint `POST /reports/export` con formatos `csv`, `excel` y `pdf`.
- **UI de reportes**: Página administrativa `/dashboard/reports` con filtros de fecha, tabla de turnos y botones de descarga.

## 💰 Presupuesto de Mejora
- **Módulo de presupuesto**: CRUD en `/budget` con baja lógica y aislamiento por tenant (RLS).
- **Campos clave**: título, descripción de mejora, horas estimadas, valor hora, moneda, estado y costo total calculado.
- **UI de presupuesto**: Página `/dashboard/budget` para crear, editar, listar y desactivar presupuestos.

## 👥 Gestión de Usuarios
- **ABM completo**: CRUD administrativo en `/users` con roles y baja lógica.
- **Restricción clave**: un administrador no puede desactivar su propio usuario activo.
- **UI de usuarios**: Página `/dashboard/users` con alta, edición, consulta y desactivación.

## 🎨 Fase 5: Portal de Reserva Público
- **Branding Dinámico**: El portal público (`/booking/:slug`) consume la configuración del salón y aplica el `primary_color` del modelo `Store` a todos los botones e indicadores UI.
- **Validación Estricta**: El campo `client_phone` es obligatorio tanto en el esquema Pydantic como en el frontend de reserva.

## 📁 Estructura de Carpetas
- `/backend`: Lógica de FastAPI organizada por módulos (`auth`, `stores`, `staff`, `appointments`).
- `/backend/core`: Configuración global, base de datos, seguridad y middleware.
- `/frontend/src/pages`: Vistas principales (Dashboard, Calendar, PublicBooking, Login/Register).
- `/frontend/src/components`: Componentes UI reutilizables con Tailwind.

## 📋 Comandos Recurrentes
- **Backend**: `python main.py` (ejecuta Uvicorn en puerto 8000).
- **Frontend**: `npm run dev` (ejecuta Vite en puerto 3000-3005).
- **Migraciones**: `python run_migrations.py` (script helper para Windows).
