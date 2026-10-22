import { computeLogoScale, type LogoPixels } from './logoFit'

// 2026-10-22 (S10.2): el logo real de Jaziz Nails es una firma fina en el
// medio de un cuadrado blanco de 1440 px; en el circulo quedaba un punto. Se
// mide hasta donde llega el contenido y se agranda hasta llenar el circulo
// con un margen chico.

type Rgba = [number, number, number, number]

const WHITE: Rgba = [255, 255, 255, 255]
const CLEAR: Rgba = [0, 0, 0, 0]
const INK: Rgba = [20, 20, 20, 255]

interface Box {
  left: number
  top: number
  right: number
  bottom: number
}

/** Imagen de `width` x `height` con fondo `background` y rectangulos de tinta. */
const pixels = (
  width: number,
  height: number,
  background: Rgba,
  content: Box[],
  ink: Rgba = INK
): LogoPixels => {
  const data = new Uint8ClampedArray(width * height * 4)
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const inside = content.some(
        (box) => x >= box.left && x <= box.right && y >= box.top && y <= box.bottom
      )
      data.set(inside ? ink : background, (y * width + x) * 4)
    }
  }
  return { width, height, data }
}

/** Distancia del centro de la imagen a la esquina mas lejana de un rectangulo lleno. */
const farthestCorner = (width: number, height: number, box: Box) => {
  const dx = Math.max(width / 2 - box.left, box.right + 1 - width / 2)
  const dy = Math.max(height / 2 - box.top, box.bottom + 1 - height / 2)
  return Math.hypot(dx, dy)
}

// 4 x 4 en el medio de 10 x 10: diagonal 5,66 -> 8 (80 % de 10) con 1,41x.
const CENTRO_4X4 = { left: 3, top: 3, right: 6, bottom: 6 }

describe('computeLogoScale', () => {
  it('un logo sin margen queda como esta', () => {
    expect(
      computeLogoScale(pixels(10, 10, WHITE, [{ left: 0, top: 0, right: 9, bottom: 9 }]))
    ).toBe(1)
  })

  it('con margen blanco lo agranda hasta que el contenido llega al 80 % del circulo', () => {
    const scale = computeLogoScale(pixels(10, 10, WHITE, [CENTRO_4X4]))

    expect(scale).toBe(1.41)
    expect(farthestCorner(10, 10, CENTRO_4X4) * scale).toBeCloseTo(0.8 * 5, 1)
  })

  it('con margen transparente hace lo mismo, aunque el fondo sea negro transparente', () => {
    expect(computeLogoScale(pixels(10, 10, CLEAR, [CENTRO_4X4]))).toBe(1.41)
  })

  it('casi blanco (245 o mas en los tres canales) es fondo; 244 ya es contenido', () => {
    expect(computeLogoScale(pixels(10, 10, WHITE, [CENTRO_4X4], [245, 250, 252, 255]))).toBe(1)
    expect(computeLogoScale(pixels(10, 10, WHITE, [CENTRO_4X4], [244, 250, 252, 255]))).toBe(1.41)
  })

  it('un pixel casi transparente (alfa menor a 16) es fondo aunque sea oscuro', () => {
    expect(computeLogoScale(pixels(10, 10, WHITE, [CENTRO_4X4], [0, 0, 0, 15]))).toBe(1)
    expect(computeLogoScale(pixels(10, 10, WHITE, [CENTRO_4X4], [0, 0, 0, 16]))).toBe(1.41)
  })

  it('una firma ancha y baja entra entera: no se corta a los costados', () => {
    // 6 x 2 en el medio: por el alto pediria 4x; por la esquina, 1,26x.
    const firma = { left: 2, top: 4, right: 7, bottom: 5 }
    const scale = computeLogoScale(pixels(10, 10, WHITE, [firma]))

    expect(scale).toBe(1.26)
    expect(farthestCorner(10, 10, firma) * scale).toBeLessThanOrEqual(0.8 * 5)
  })

  it('un emblema con las esquinas vacias crece mas que un cuadrado lleno del mismo tamano', () => {
    // Una cruz que ocupa de 6 a 13 en 20 x 20: sus puntas no llegan a las
    // esquinas del rectangulo que la encierra.
    const cruz = [
      { left: 6, top: 9, right: 13, bottom: 10 },
      { left: 9, top: 6, right: 10, bottom: 13 }
    ]
    const lleno = { left: 6, top: 6, right: 13, bottom: 13 }

    const scale = computeLogoScale(pixels(20, 20, WHITE, cruz))

    expect(scale).toBeGreaterThan(computeLogoScale(pixels(20, 20, WHITE, [lleno])))
    // La punta de la cruz (4 de largo y 1 de ancho desde el centro) queda al 80 %.
    expect(Math.hypot(4, 1) * scale).toBeLessThanOrEqual(0.8 * 10)
    expect(Math.hypot(4, 1) * scale).toBeGreaterThan(0.79 * 10)
  })

  it('con el contenido corrido del centro agranda menos, para no cortarlo', () => {
    // 8 x 8 en 20 x 20: centrado da 1,41x; corrido un pixel, 1,13x.
    const centrado = { left: 6, top: 6, right: 13, bottom: 13 }
    const corrido = { left: 7, top: 7, right: 14, bottom: 14 }
    const scale = computeLogoScale(pixels(20, 20, WHITE, [corrido]))

    expect(scale).toBe(1.13)
    expect(computeLogoScale(pixels(20, 20, WHITE, [centrado]))).toBe(1.41)
    expect(farthestCorner(20, 20, corrido) * scale).toBeLessThanOrEqual(0.8 * 10)
  })

  it('contenido pegado a un borde no se agranda', () => {
    expect(
      computeLogoScale(pixels(10, 10, WHITE, [{ left: 0, top: 4, right: 2, bottom: 5 }]))
    ).toBe(1)
  })

  it('un contenido diminuto no pasa de 2,5x', () => {
    expect(
      computeLogoScale(pixels(20, 20, WHITE, [{ left: 10, top: 10, right: 10, bottom: 10 }]))
    ).toBe(2.5)
  })

  it('en una imagen apaisada mide contra el lado largo, que es el que llena el circulo', () => {
    // 20 x 10: el circulo tiene 20 de diametro; contenido 12 x 6 centrado.
    const box = { left: 4, top: 2, right: 15, bottom: 7 }
    const scale = computeLogoScale(pixels(20, 10, WHITE, [box]))

    expect(scale).toBe(1.19)
    expect(farthestCorner(20, 10, box) * scale).toBeCloseTo(0.8 * 10, 1)
  })

  it('sin contenido, o sin pixeles, queda en 1', () => {
    expect(computeLogoScale(pixels(10, 10, WHITE, []))).toBe(1)
    expect(computeLogoScale(pixels(10, 10, CLEAR, []))).toBe(1)
    expect(computeLogoScale({ width: 0, height: 0, data: new Uint8ClampedArray(0) })).toBe(1)
  })
})
