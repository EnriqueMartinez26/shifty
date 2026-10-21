/**
 * Logo que llena el circulo del portal (S10.2). Muchos logos traen un margen
 * blanco o transparente grande (el de Jaziz Nails es una firma fina en el medio
 * de un cuadrado de 1440 px) y en el circulo quedaban chiquitos. Con los
 * pixeles del logo se mide hasta donde llega el contenido y se calcula cuanto
 * agrandarlo.
 *
 * Funcion pura: leer los pixeles (canvas) lo hace el componente.
 */

/** La forma de `ImageData`, sin depender del DOM. */
export interface LogoPixels {
  width: number
  height: number
  data: ArrayLike<number>
}

// Fondo: casi transparente, o casi blanco en los tres canales.
const MIN_CONTENT_ALPHA = 16
const MIN_BACKGROUND_CHANNEL = 245

// El pixel de contenido mas lejano queda al 80 % del radio: llena el circulo
// y deja un margen chico contra el aro.
const TARGET_FILL = 0.8
const MIN_SCALE = 1
const MAX_SCALE = 2.5

// Un canal que falta (arreglo corto) cuenta como 0: transparente, fondo.
const channel = (data: ArrayLike<number>, index: number): number => data[index] ?? 0

const isBackground = (data: ArrayLike<number>, offset: number): boolean =>
  channel(data, offset + 3) < MIN_CONTENT_ALPHA ||
  (channel(data, offset) >= MIN_BACKGROUND_CHANNEL &&
    channel(data, offset + 1) >= MIN_BACKGROUND_CHANNEL &&
    channel(data, offset + 2) >= MIN_BACKGROUND_CHANNEL)

/** Distancia del centro a la punta mas lejana del pixel, sobre un eje. */
const farthestEdge = (index: number, center: number): number =>
  Math.max(Math.abs(index - center), Math.abs(index + 1 - center))

/**
 * Cuanto agrandar el logo, que se ve con `object-fit: contain` en un circulo
 * y se escala desde su centro. Con `contain` el lado largo de la imagen es el
 * diametro. Manda el pixel de contenido mas lejano al centro, no el ancho ni
 * el alto del rectangulo que lo encierra: una firma ancha y baja no se corta
 * a los costados, y un emblema con las esquinas vacias crece lo que puede.
 * Redondea para abajo, asi nunca pasa del objetivo. Entre 1 y 2,5; 1 sin
 * contenido o sin margen.
 */
export const computeLogoScale = ({ width, height, data }: LogoPixels): number => {
  const centerX = width / 2
  const centerY = height / 2
  let farthest = 0
  for (let y = 0; y < height; y += 1) {
    const dy = farthestEdge(y, centerY)
    for (let x = 0; x < width; x += 1) {
      if (isBackground(data, (y * width + x) * 4)) continue
      farthest = Math.max(farthest, Math.hypot(farthestEdge(x, centerX), dy))
    }
  }
  if (farthest === 0) return MIN_SCALE
  const scale = (TARGET_FILL * Math.max(width, height)) / 2 / farthest
  return Math.min(MAX_SCALE, Math.max(MIN_SCALE, Math.floor(scale * 100) / 100))
}
