# Shifty — Sistema de Gestión de Turnos Multi-Tenant

## 🚀 Introducción
**Shifty** es una plataforma administrativa de alto rendimiento diseñada para la gestión integral de turnos y recursos en comercios de servicios (barberías, centros de estética, consultorios). Combina una robusta arquitectura backend con una interfaz visual única inspirada en el **Skeuomorfismo de principios de los 2000 (Early Smartphone Aesthetic)**, proporcionando una experiencia táctil y nostálgica sin sacrificar la funcionalidad moderna.

---

## 🛠️ Stack Tecnológico

### Frontend (El "Hardware" Visual)
- **Framework**: React 18+ con Vite para un desarrollo ultra rápido.
- **Lenguaje**: TypeScript (Tipado estricto para mayor estabilidad).
- **Estilos**: Tailwind CSS v4 con una configuración personalizada de tokens de diseño.
- **Iconografía**: Sistema híbrido de **Lucide React** y **Material Design Icons (MDI)** con filtros CSS personalizados para efectos de relieve y profundidad.
- **Estado y API**: TanStack Query (React Query) para sincronización de estado asíncrono y caching.

### Backend (El Motor de Procesamiento)
- **Framework**: FastAPI (Python 3.12+). Elegido por su velocidad y soporte nativo de asincronía.
- **ORM**: SQLAlchemy 2.0 con soporte asíncrono (`asyncpg`).
- **Validación**: Pydantic v2 para garantizar que cada dato que entra o sale cumple con el esquema definido.
- **Seguridad**: Autenticación vía JWT (JSON Web Tokens) con hashing de contraseñas mediante `bcrypt`.

### Infraestructura y Datos
- **Base de Datos**: PostgreSQL 16 (Normalizada bajo principios 3NF).
- **Mensajería y Cache**: Redis para gestión de colas y almacenamiento temporal.
- **Tareas en Segundo Plano**: Celery para el envío de notificaciones y procesamiento pesado.
- **Contenerización**: Docker y Docker Compose para un entorno de despliegue idéntico en desarrollo y producción.
- **Proxy Inverso**: Nginx para el manejo de tráfico y serving de archivos estáticos.

---

## 🏛️ Metodologías y Arquitectura

### 1. Diseño Orientado a Objetos (OOP)
El sistema está construido siguiendo patrones de diseño clásicos para asegurar la escalabilidad:
- **Modelo-Repositorio-Servicio**:
    - **Models**: Definen la estructura y relaciones de los datos.
    - **Repositories**: Encapsulan la lógica de acceso a datos (Queries SQL).
    - **Services**: Contienen la lógica de negocio pura (validaciones, cálculos de presupuesto).
    - **Routers**: Gestionan las entradas HTTP y delegan la ejecución.

### 2. Normalización de Base de Datos (3NF)
La base de datos sigue estrictamente la **Tercera Forma Normal (3NF)**:
- Eliminación de redundancias.
- Dependencias funcionales claras (cada dato depende únicamente de su clave primaria).
- Integridad referencial fuerte para evitar huérfanos en el sistema de turnos.

### 3. Multi-Tenancy (Aislamiento de Tiendas)
Shifty es un sistema multi-inquilino. Cada salón de belleza o tienda tiene su propia burbuja de datos:
- Aislamiento mediante `store_id` en todas las tablas críticas.
- Middleware de detección de Tenant que inyecta el contexto de la tienda en cada petición.

### 4. Estética Skeuomórfica (Early 2000s)
A diferencia del diseño "Flat" moderno, Shifty utiliza:
- **Profundidad Física**: Sombras `inset` para campos de entrada y `outer` para botones elevados.
- **Gradientes Satinados**: Uso de `linear-gradients` complejos para simular texturas de hardware plástico y metálico.
- **Micro-animaciones**: Estados `active:scale-95` que imitan la pulsación de botones físicos.

---

## 📦 Características Principales

1. **Dashboard de Métricas**: Visualización de rendimiento diario, ocupación y facturación con estética de consola.
2. **Agenda Dinámica**: Gestión de slots de tiempo con detección automática de conflictos.
3. **Portal de Reserva Público**: Interfaz simplificada para que el cliente final reserve en 5 pasos sin necesidad de loguearse.
4. **Sistema de Presupuestos**: Calculadora interna para generar cotizaciones rápidas basadas en servicios y materiales.
5. **Gestión de Staff y Servicios**: Control granular de qué profesionales realizan qué servicios y sus horarios específicos.
6. **Notificaciones Automáticas**: Confirmaciones y recordatorios por email para reducir el ausentismo (no-show).

---

## 📂 Estructura del Proyecto

```text
Shifty/
├── backend/                # Lógica API Python
│   ├── core/               # Configuración, Seguridad y Middlewares
│   ├── modules/            # Módulos de negocio (auth, stores, appointments...)
│   └── main.py             # Punto de entrada de la aplicación
├── frontend/               # Interfaz React
│   ├── src/
│   │   ├── components/     # UI Elements skeuomórficos
│   │   ├── features/       # Lógica de negocio por dominio (booking, auth...)
│   │   ├── pages/          # Vistas principales
│   │   └── theme/          # Sistema de diseño (colores y estilos 2000s)
├── nginx/                  # Configuración de servidor web
└── docker-compose.yml      # Orquestación de contenedores
```

---

*Shifty — Donde la nostalgia del hardware clásico se encuentra con la eficiencia del software moderno.*
