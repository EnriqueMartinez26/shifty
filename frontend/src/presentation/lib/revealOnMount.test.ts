import { revealOnMount, revealSection } from './revealOnMount'

const originalMatchMedia = Object.getOwnPropertyDescriptor(window, 'matchMedia')

const setReducedMotion = (matches: boolean): void => {
  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    value: jest.fn().mockReturnValue({ matches })
  })
}

const makeScrollable = (): HTMLElement => {
  const node = document.createElement('div')
  node.scrollIntoView = jest.fn()
  return node
}

afterEach(() => {
  if (originalMatchMedia) Object.defineProperty(window, 'matchMedia', originalMatchMedia)
  else Reflect.deleteProperty(window, 'matchMedia')
})

describe('revealOnMount y revealSection', () => {
  it('usa desplazamiento suave cuando no se prefiere movimiento reducido', () => {
    setReducedMotion(false)
    const node = makeScrollable()

    revealOnMount(node)

    expect(node.scrollIntoView).toHaveBeenCalledWith({ block: 'nearest', behavior: 'smooth' })
    expect(window.matchMedia).toHaveBeenCalledWith('(prefers-reduced-motion: reduce)')
  })

  it('evita el desplazamiento suave cuando se prefiere movimiento reducido', () => {
    setReducedMotion(true)
    const node = makeScrollable()

    revealOnMount(node)

    expect(node.scrollIntoView).toHaveBeenCalledWith({ block: 'nearest', behavior: 'auto' })
  })

  it('mantiene el bloque superior y el foco sin segundo scroll en revealSection', () => {
    setReducedMotion(true)
    const node = makeScrollable()
    node.setAttribute('tabindex', '-1')
    const focus = jest.spyOn(node, 'focus')

    revealSection(node)

    expect(node.scrollIntoView).toHaveBeenCalledWith({ block: 'start', behavior: 'auto' })
    expect(focus).toHaveBeenCalledWith({ preventScroll: true })
  })

  it('tolera entornos sin matchMedia y conserva el comportamiento previo', () => {
    Reflect.deleteProperty(window, 'matchMedia')
    const node = makeScrollable()

    revealOnMount(node)

    expect(node.scrollIntoView).toHaveBeenCalledWith({ block: 'nearest', behavior: 'smooth' })
  })
})
