import axios from "axios";
import axiosRetry from "axios-retry";

const API_URL =
  import.meta.env.VITE_API_URL ||
  (import.meta.env.DEV ? "http://localhost:8000" : "https://shifty-iota.vercel.app");
const TOKEN_KEY = "shifty_token";

const apiClient = axios.create({
  baseURL: API_URL,
  withCredentials: true,
  headers: {
    "Content-Type": "application/json",
  },
});

export const setAuthToken = (token: string | null) => {
  if (token) {
    localStorage.setItem(TOKEN_KEY, token);
  } else {
    localStorage.removeItem(TOKEN_KEY);
  }
};

export const getAuthToken = () => localStorage.getItem(TOKEN_KEY);

apiClient.interceptors.request.use((config) => {
  const token = getAuthToken();
  if (token) {
    config.headers = config.headers ?? {};
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Configuración de Retry Inteligente
axiosRetry(apiClient, {
  retries: 3,
  retryDelay: (retryCount) => {
    // Backoff exponencial con Jitter: 1s, 2s, 4s (+ random offset)
    const delay = Math.pow(2, retryCount) * 1000;
    const jitter = Math.random() * 1000;
    return delay + jitter;
  },
  retryCondition: (error) => {
    // NO reintentar si el servidor rechazó la conexión (ERR_CONNECTION_REFUSED)
    // eso significa que el backend directamente no está corriendo.
    if (error.code === "ERR_NETWORK" || error.code === "ERR_CONNECTION_REFUSED") {
      return false;
    }
    // Reintentar solo en timeouts o errores de concurrencia (409 Conflict)
    return (
      error.code === "ECONNABORTED" ||
      error.response?.status === 409
    );
  },
});

apiClient.interceptors.response.use(
  (response) => response,
  async (error) => {
    if (error.response?.status === 401) {
      setAuthToken(null);
    }
    return Promise.reject(error);
  }
);

export default apiClient;
