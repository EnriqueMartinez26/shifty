import { readFileSync, writeFileSync } from 'node:fs'

// Solo la imagen construida con GA4 habilitado necesita estos destinos.
// Sin ID se conserva exactamente la politica de seguridad original.
const [source, destination] = process.argv.slice(2)
if (!source || !destination) throw new Error('Uso: configure-analytics-csp.mjs origen destino')
const measurementId = (process.env.VITE_GA4_MEASUREMENT_ID ?? '').trim()
if (measurementId && !/^G-[A-Z0-9]{4,20}$/.test(measurementId)) {
  throw new Error('VITE_GA4_MEASUREMENT_ID invalido')
}
let policy = readFileSync(source, 'utf8')
if (measurementId) {
  const destinations = {
    "script-src 'self';": "script-src 'self' https://www.googletagmanager.com;",
    "connect-src 'self';":
      "connect-src 'self' https://www.google-analytics.com https://region1.google-analytics.com;",
    "img-src 'self' data: blob:;":
      "img-src 'self' data: blob: https://www.google-analytics.com https://region1.google-analytics.com;"
  }
  for (const [original, replacement] of Object.entries(destinations)) {
    if (policy.split(original).length !== 2) {
      throw new Error(`La directiva CSP esperada cambio: ${original}`)
    }
    policy = policy.replace(original, replacement)
  }
}
writeFileSync(destination, policy)
