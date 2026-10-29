const reveal = (node: HTMLElement | null, block: ScrollLogicalPosition): void => {
  if (!node) return
  if (typeof node.scrollIntoView === 'function') {
    const reduceMotion =
      typeof window !== 'undefined' &&
      typeof window.matchMedia === 'function' &&
      window.matchMedia('(prefers-reduced-motion: reduce)').matches
    node.scrollIntoView({ block, behavior: reduceMotion ? 'auto' : 'smooth' })
  }
  if (node.hasAttribute('tabindex')) {
    node.focus({ preventScroll: true })
  }
}

/**
 * Ref callback que lleva un aviso a la vista al montarse. Es una funcion de
 * modulo, estable entre renders: React la llama al montar y al desmontar, no
 * en cada tecla. Con `key` = el texto del aviso, uno nuevo se vuelve a mostrar.
 * Los errores de varios formularios quedaban fuera de la vista (QA 2026-10-02:
 * uno a top=-299px dentro de un modal). jsdom no implementa scrollIntoView.
 *
 * Si el aviso es enfocable (`tabIndex={-1}`, como FormErrorAlert) tambien toma
 * el foco: en un telefono el teclado tapa medio modal y el lector de pantalla
 * lo anuncia (QA movil 2026-10-08). Sin `tabindex` solo se desplaza.
 */
export const revealOnMount = (node: HTMLElement | null): void => reveal(node, 'nearest')

/**
 * Lo mismo desde un evento: lleva el encabezado de una seccion al borde
 * superior y, si es enfocable, le pasa el foco. "Ver" en el panel SuperAdmin
 * cambiaba la tienda elegida sin ninguna senal visible (2026-10-10).
 */
export const revealSection = (node: HTMLElement | null): void => reveal(node, 'start')
