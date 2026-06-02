# Estándar de Comunicación API (Fetch Standard)
> **Resumen:** Definición del cliente HTTP centralizado y protocolos de comunicación resiliente para el ecosistema Shifty.

## Introducción al Estándar
El "Fetch Standard" define el proceso de obtención de recursos, vinculando las **Requests** (peticiones) con las **Responses** (respuestas). En Shifty, este proceso es la columna vertebral de la sincronización entre el cliente y el servidor.

El objetivo es proporcionar un mecanismo unificado que garantice la integridad de los datos, la seguridad en el transporte y la resiliencia ante la inestabilidad de la red.

## Arquitectura del Cliente (Axios)
Shifty utiliza una instancia centralizada de **Axios** para gestionar todas las llamadas externas. Esta centralización permite inyectar lógica global sin repetir código en los componentes.

### Configuración Base
El cliente está configurado para apuntar a la URL base definida en las variables de entorno (`VITE_API_URL`). Por defecto, utiliza JSON como formato de intercambio de datos.

| Parámetro | Valor / Origen |
| :--- | :--- |
| `baseURL` | `import.meta.env.VITE_API_URL` |
| `Content-Type` | `application/json` |
| `Timeout` | Configurado dinámicamente (default: 10s) |

## Política de Resiliencia y Reintentos
Para mitigar fallos temporales, implementamos una estrategia de **Exponential Backoff con Jitter**. Esto evita que múltiples clientes saturen el servidor al reintentar simultáneamente.

### Reglas de Reintento
1. **Límite:** Se permiten hasta 3 reintentos automáticos.
2. **Intervalo:** El tiempo de espera crece exponencialmente (2^n) más un desfase aleatorio para evitar colisiones.
3. **Condiciones:**
   - **Timeout (408/ECONNABORTED):** Se reintenta bajo la premisa de saturación temporal.
   - **Conflict (409):** Se reintenta asumiendo una colisión de estado que podría resolverse en milisegundos.
4. **Exclusiones:** No se reintentan errores de red fatales (`ERR_CONNECTION_REFUSED`) o errores de cliente (400, 401, 403, 404).

## Seguridad y Autenticación
La seguridad se gestiona mediante un **Interceptor de Request**. Este interceptor actúa como un middleware antes de que la petición salga del navegador.

### Inyección de Token
Cada petición verifica la existencia de un `shifty_token` en el `localStorage`. Si está presente, se adjunta automáticamente al header `Authorization` siguiendo el esquema Bearer.

```typescript
// Lógica del Interceptor
apiClient.interceptors.request.use((config) => {
  const token = localStorage.getItem("shifty_token");
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});
```

## Protocolo CORS (Cross-Origin Resource Sharing)
Siguiendo la sección 3.3 del **Fetch Standard**, Shifty implementa un control de acceso estricto para proteger la integridad de los datos entre dominios.

### Configuración de Seguridad
1. **Credentials Mode:** El cliente siempre envía credenciales (`withCredentials: true`). El backend responde con `Access-Control-Allow-Credentials: true`.
2. **Exposición de Headers:** Para que el frontend pueda leer metadatos críticos, el backend expone explícitamente:
   - `X-Idempotency-Key`: Para validar el estado de transacciones repetidas.
   - `Content-Disposition`: Para permitir la descarga de archivos con nombres correctos.
3. **Preflight Cache (Max Age):** Se configura un `max_age` de 600 segundos (10 minutos) para reducir la latencia causada por peticiones `OPTIONS` repetitivas.

### Headers Permitidos
Para evitar bloqueos en operaciones complejas, permitimos explícitamente:
- `X-Tenant-ID`: Identificador de la tienda en el modelo multi-tenant.
- `X-Idempotency-Key`: Clave de protección contra duplicados.
- `Authorization`: Token Bearer de Shifty.

## Manejo de Idempotencia
En operaciones que modifican el estado (POST, PUT, DELETE), es crítico garantizar que una petición repetida no produzca efectos secundarios múltiples (como crear dos turnos iguales).

### Header X-Idempotency-Key
Para procesos críticos, el frontend debe generar un UUID único y enviarlo en el header `X-Idempotency-Key`. El backend utilizará esta clave para identificar y descartar peticiones duplicadas durante los reintentos de red.

## Glosario de Estados Comunes
| Código | Significado en Shifty | Acción Sugerida |
| :--- | :--- | :--- |
| 200/201 | Éxito total | Continuar flujo normal. |
| 401 | No autorizado | Redirigir a Login / Limpiar Token. |
| 409 | Conflicto | El sistema reintenta automáticamente. |
| 422 | Error de Validación | Mostrar errores de campo al usuario. |
| 503 | Servicio No Disponible | Mostrar mensaje de mantenimiento. |
