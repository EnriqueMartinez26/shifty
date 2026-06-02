/**
 * parseApiError
 * Convierte un error de Axios o una respuesta del Backend en un string legible.
 * Sigue el estándar de Sentinel para Reporte de Errores.
 */
export const parseApiError = (err: any): string => {
  // 1. Error de validación estructurado (Pydantic / FastAPI)
  if (err.response?.data?.detail && Array.isArray(err.response.data.detail)) {
    return err.response.data.detail
      .map((d: any) => `${d.loc.join(" -> ")}: ${d.msg}`)
      .join("\n");
  }

  // 2. Error de dominio estandarizado (AppException)
  if (err.response?.data?.message) {
    return err.response.data.message;
  }

  // 3. Error de red o respuesta sin body
  if (err.response?.status === 401) return "Sesión expirada. Por favor reingresa.";
  if (err.response?.status === 403) return "No tienes permiso para realizar esta acción.";
  if (err.response?.status === 404) return "El recurso solicitado no existe.";
  
  return err.message || "Ocurrió un error inesperado.";
};

/**
 * handleMutationError
 * Helper para usar en onError de React Query mutations.
 */
export const handleMutationError = (err: any, toastFn?: (msg: string) => void) => {
  const msg = parseApiError(err);
  if (toastFn) {
    toastFn(msg);
  } else {
    console.error("API Error:", msg);
  }
  return msg;
};
