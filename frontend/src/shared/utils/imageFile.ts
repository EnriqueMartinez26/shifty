/**
 * Validacion rapida de una imagen de servicio ANTES de subirla: tipo, tamano y
 * magic bytes. Es solo feedback para el usuario; el backend
 * (modules/stores/media.py) valida lo mismo mas los pixeles y es quien manda.
 * Nunca se acepta SVG: puede llevar scripts.
 */
const MAX_SERVICE_IMAGE_BYTES = 1024 * 1024

const ALLOWED_TYPES: ReadonlySet<string> = new Set(['image/png', 'image/jpeg', 'image/webp'])

const startsWith = (head: Uint8Array, bytes: readonly number[], offset = 0): boolean =>
  bytes.every((byte, i) => head[offset + i] === byte)

// Los mismos que `_SNIFFERS` de media.py.
const PNG = [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]
const JPEG = [0xff, 0xd8, 0xff]
const RIFF = [0x52, 0x49, 0x46, 0x46]
const WEBP = [0x57, 0x45, 0x42, 0x50]

const isKnownImage = (head: Uint8Array): boolean =>
  startsWith(head, PNG) ||
  startsWith(head, JPEG) ||
  (head.length >= 12 && startsWith(head, RIFF) && startsWith(head, WEBP, 8))

// FileReader y no `Blob.arrayBuffer()`: el jsdom de los tests no lo implementa
// (mismo recurso que infrastructure/http/client.ts).
const readHead = (file: Blob): Promise<Uint8Array> =>
  new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(new Uint8Array(reader.result as ArrayBuffer))
    reader.onerror = () => reject(reader.error ?? new Error('No se pudo leer el archivo'))
    reader.readAsArrayBuffer(file.slice(0, 12))
  })

/** Mensaje para el usuario si la imagen no sirve, o `null` si se puede subir. */
export const validateServiceImage = async (file: File): Promise<string | null> => {
  if (!ALLOWED_TYPES.has(file.type)) {
    return 'Formato no permitido. Usá PNG, JPEG o WebP.'
  }
  if (file.size === 0) {
    return 'El archivo está vacío.'
  }
  if (file.size > MAX_SERVICE_IMAGE_BYTES) {
    return 'La imagen supera el máximo de 1 MB.'
  }
  if (!isKnownImage(await readHead(file))) {
    return 'El archivo no es una imagen PNG, JPEG o WebP válida.'
  }
  return null
}
