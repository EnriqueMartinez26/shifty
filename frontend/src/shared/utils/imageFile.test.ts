import { validateServiceImage } from './imageFile'

/**
 * 2026-09-30: el panel no podia subir la imagen de un servicio aunque el
 * backend ya lo permitia. Esta validacion es solo feedback rapido antes de
 * subir: el backend (modules/stores/media.py) valida los magic bytes y manda.
 */
const PNG = [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0, 0, 0, 0]
const JPEG = [0xff, 0xd8, 0xff, 0xe0, 0, 0, 0, 0, 0, 0, 0, 0]
const WEBP = [0x52, 0x49, 0x46, 0x46, 0, 0, 0, 0, 0x57, 0x45, 0x42, 0x50]

const archivo = (bytes: number[] | Uint8Array, type: string, name = 'foto') =>
  new File([new Uint8Array(bytes)], name, { type })

describe('validateServiceImage', () => {
  it.each([
    ['PNG', PNG, 'image/png'],
    ['JPEG', JPEG, 'image/jpeg'],
    ['WebP', WEBP, 'image/webp']
  ])('acepta un %s con sus magic bytes', async (_nombre, bytes, type) => {
    await expect(validateServiceImage(archivo(bytes, type))).resolves.toBeNull()
  })

  it('rechaza un SVG aunque el navegador lo marque como imagen', async () => {
    const svg = new File(['<svg xmlns="http://www.w3.org/2000/svg"/>'], 'x.svg', {
      type: 'image/svg+xml'
    })

    await expect(validateServiceImage(svg)).resolves.toMatch(/PNG, JPEG o WebP/)
  })

  it('rechaza un archivo que dice ser PNG pero no tiene sus magic bytes', async () => {
    const falso = archivo([0x3c, 0x73, 0x76, 0x67, 0, 0, 0, 0, 0, 0, 0, 0], 'image/png')

    await expect(validateServiceImage(falso)).resolves.toMatch(/no es una imagen/)
  })

  it('rechaza un RIFF que no es WebP', async () => {
    const wav = archivo([0x52, 0x49, 0x46, 0x46, 0, 0, 0, 0, 0x57, 0x41, 0x56, 0x45], 'image/webp')

    await expect(validateServiceImage(wav)).resolves.toMatch(/no es una imagen/)
  })

  it('rechaza una imagen de mas de 1 MB', async () => {
    const grande = new Uint8Array(1024 * 1024 + 1)
    grande.set(PNG)

    await expect(validateServiceImage(archivo(grande, 'image/png'))).resolves.toMatch(/1 MB/)
  })

  it('rechaza un archivo vacio', async () => {
    await expect(validateServiceImage(archivo([], 'image/png'))).resolves.toMatch(/vacío/)
  })
})
