# Diseño de Base de Datos: Normalización 3NF, RLS y Auditoría

## Introducción

Este documento describe la arquitectura de base de datos de Shifty, que implementa:
1. **Normalización 3NF** - Para integridad y eficiencia
2. **Row-Level Security (RLS)** - Para aislamiento multi-tenant
3. **Auditoría (Audit Logging)** - Para trazabilidad completa

---

## 1. Normalización 3NF (Third Normal Form - Normalization)

### ¿Qué es 3NF y Normalization?

**3NF (Tercera Forma Normal)** y **normalization (normalización)** son estándares de diseño de bases de datos relacionales que garantizan:
- ✅ Integridad de datos
- ✅ Minimización de redundancia
- ✅ Eficiencia en consultas
- ✅ Fácil mantenimiento
- ✅ Prevención de anomalías

### Tres Niveles de Normalización

#### 1NF (Primera Forma Normal)
- Todos los valores en una columna son atómicos (indivisibles)
- No hay campos con múltiples valores
- Cada campo tiene un único tipo de dato

#### 2NF (Segunda Forma Normal)
- Cumple con 1NF
- Todo atributo no-clave depende **completamente** de la clave primaria

#### 3NF (Tercera Forma Normal)
- Cumple con 2NF
- No hay **dependencias transitivas** entre atributos no-clave
- Cada tabla representa una sola entidad conceptual

### Estructura 3NF en Shifty

```
USERS → STORES ← SERVICES
  ↓      ↓          ↓
AUDIT  STAFF    APPOINTMENTS
               ↑
             SCHEDULES
```

Las tablas están separadas por responsabilidad:
- **USERS**: Cuentas de usuario
- **STORES**: Comercios/Salones
- **SERVICES**: Servicios ofrecidos
- **STAFF**: Personal del salón
- **APPOINTMENTS**: Turnos/citas
- **AUDIT_LOGS**: Registro de cambios

### Beneficios de 3NF en Shifty

1. **Integridad Referencial**: Foreign Keys aseguran consistencia
2. **Sin Redundancia**: Datos no duplicados
3. **Cambios Atómicos**: Modificar dato en un solo lugar
4. **Performance**: Índices estratégicos aceleran búsquedas
5. **Escalabilidad**: Fácil agregar nuevas entidades

---

## 2. Row-Level Security (RLS)

### ¿Qué es RLS?

**RLS (Row-Level Security)** es un mecanismo de PostgreSQL que filtra filas a nivel de base de datos, no en la aplicación.

### ¿Por qué RLS en Shifty?

Shifty es **multi-tenant**: múltiples salones comparten la misma BD pero sus datos deben estar completamente aislados.

### Cómo Funciona RLS

#### Paso 1: Contexto de Sesión
Al conectar, la aplicación establece:
```sql
SELECT set_config('app.current_store_id', '123', false);
```

#### Paso 2: Políticas en Tablas
Cada tabla tiene una política RLS:
```sql
CREATE POLICY appointments_isolation ON appointments
  USING (store_id = current_setting('app.current_store_id')::int);

CREATE POLICY users_isolation ON users
  USING (store_id = current_setting('app.current_store_id')::int);

CREATE POLICY services_isolation ON services
  USING (store_id = current_setting('app.current_store_id')::int);
```

#### Paso 3: Filtración Automática
```sql
-- Query normal:
SELECT * FROM appointments WHERE status = 'CONFIRMED';

-- Con RLS, efectivamente ejecuta:
SELECT * FROM appointments 
WHERE status = 'CONFIRMED' 
  AND store_id = current_setting('app.current_store_id')::int;
```

### Garantías de RLS

✅ **Seguridad a Nivel BD**: No depende del código de aplicación
✅ **Imposible Violar**: Incluso con SQL directo se respeta RLS
✅ **Transparente**: La app no agrega `WHERE store_id = ...` manualmente
✅ **Imposible Perder Datos**: Malas configuraciones en app no exponen datos

---

## 3. Auditoría (Audit Logging)

### ¿Qué es Auditoría?

La **auditoría** registra **todos los cambios significativos** en el sistema para:
- ✅ Trazabilidad completa
- ✅ Cumplimiento legal (GDPR, compliance)
- ✅ Debugging de problemas
- ✅ Análisis de seguridad

### Tabla AUDIT_LOGS

```sql
CREATE TABLE audit_logs (
  id INT PRIMARY KEY AUTO_INCREMENT,
  appointment_id INT FOREIGN KEY,
  action VARCHAR (CREATE, UPDATE, CANCEL, MARK_ABSENT),
  previous_state JSONB,
  new_state JSONB,
  user_id INT FOREIGN KEY,
  timestamp TIMESTAMP,
  store_id INT FOREIGN KEY
);
```

### Qué Se Audita

**Eventos Auditados:**
- ✅ Creación de turno: `CREATE`
- ✅ Cambio de estado: `UPDATE`
- ✅ Cancelación: `CANCEL`
- ✅ Marcado ABSENT: `MARK_ABSENT`
- ✅ Cambio de hora/personal: `UPDATE`

### Importancia de Auditoría

- **Investigación**: "¿Quién cambió este turno?"
- **Compliance**: Cumplimiento de regulaciones
- **Seguridad**: Detección de actividades sospechosas
- **Trazabilidad**: Reconstruir exactamente qué pasó

---

## 4. Integración: 3NF + RLS + Auditoría

### Flujo de una Operación

```
1. Cliente solicita cambiar turno
2. Middleware extrae store_id del JWT
3. BD ejecuta: set_config('app.current_store_id', store_id)
4. Query UPDATE appointments:
   - RLS filtra por store_id
   - 3NF valida integridad
5. Auditoría registra cambio:
   - action, previous_state, new_state
   - user_id, timestamp, store_id
6. Operación completada
```

Resultado: **Seguridad garantizada en múltiples niveles**
