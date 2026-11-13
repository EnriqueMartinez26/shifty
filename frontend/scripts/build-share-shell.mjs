import { readFileSync, writeFileSync } from 'node:fs'
import { resolve } from 'node:path'

const distDir = resolve('dist')
const indexPath = resolve(distDir, 'index.html')
const storePath = resolve(distDir, 'store.html')
const storeMetadataPath = resolve('store.html')

const managedMetadata = new Set([
  'description',
  'og:type',
  'og:locale',
  'og:site_name',
  'og:title',
  'og:url',
  'og:image',
  'og:image:width',
  'og:image:height',
  'og:image:alt',
  'og:description',
  'twitter:card',
  'twitter:title',
  'twitter:description',
  'twitter:image'
])

const storeMetadata = readFileSync(storeMetadataPath, 'utf8').trim()
if (!storeMetadata.includes('<!--# block name="default_store_metadata" -->')) {
  throw new Error('frontend/store.html no define el bloque SSI de metadata de fallback')
}
if (
  !storeMetadata.includes(
    '<!--# include virtual="/_internal/share-metadata?slug=$share_store_slug"'
  )
) {
  throw new Error('frontend/store.html no incluye el endpoint interno de metadata')
}

let html = readFileSync(indexPath, 'utf8')
const titlePattern = /<title\b[^>]*>[\s\S]*?<\/title\s*>/i
if (!titlePattern.test(html)) {
  throw new Error('El shell de Vite no contiene un <title> para reemplazar')
}
html = html.replace(titlePattern, '')

const removedMetadata = new Set()
html = html.replace(/<meta\b[^>]*>/gi, (tag) => {
  const keyMatch = /(?:^|\s)(?:name|property)\s*=\s*(["'])(.*?)\1/i.exec(tag)
  const key = keyMatch?.[2]?.toLowerCase()
  if (!key || !managedMetadata.has(key)) return tag
  removedMetadata.add(key)
  return ''
})

for (const requiredKey of ['description', 'og:title', 'og:url', 'og:image', 'twitter:title']) {
  if (!removedMetadata.has(requiredKey)) {
    throw new Error(`El shell de Vite ya no contiene metadata esperada: ${requiredKey}`)
  }
}

if (!/<script\b[^>]*\btype=["']module["'][^>]*\bsrc=/i.test(html)) {
  throw new Error('El shell generado por Vite no contiene el entrypoint ESM de la aplicacion')
}

const headClose = /<\/head\s*>/i
if (!headClose.test(html)) {
  throw new Error('El shell de Vite no contiene </head>')
}
html = html.replace(headClose, `\n    ${storeMetadata}\n  </head>`)

writeFileSync(storePath, html)
