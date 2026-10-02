/**
 * Ref callback que lleva un aviso a la vista al montarse. Es una funcion de
 * modulo, estable entre renders: React la llama al montar y al desmontar, no
 * en cada tecla. Con `key` = el texto del aviso, uno nuevo se vuelve a mostrar.
 * Los errores de varios formularios quedaban fuera de la vista (QA 2026-10-02:
 * uno a top=-299px dentro de un modal). jsdom no implementa scrollIntoView.
 */
export const revealOnMount = (node: HTMLElement | null): void => {
  if (node && typeof node.scrollIntoView === 'function') {
    node.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }
}
