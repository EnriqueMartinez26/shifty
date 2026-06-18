/* istanbul ignore file */

export type RuntimeEnv = {
  apiUrl?: string
  dev: boolean
}

export const getRuntimeEnv = (): RuntimeEnv => ({
  apiUrl: import.meta.env.VITE_API_URL,
  dev: import.meta.env.DEV
})
