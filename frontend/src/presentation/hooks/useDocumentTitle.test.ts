import { renderHook } from '@testing-library/react'

import { useDocumentTitle } from './useDocumentTitle'

// 2026-10-03: ninguna pagina fijaba document.title y toda pestana decia
// "Shifty", con el panel y el portal abiertos a la vez no se distinguian.
describe('useDocumentTitle', () => {
  beforeEach(() => {
    document.title = 'Shifty'
  })

  it('fija el titulo mientras la pagina esta montada', () => {
    renderHook(() => useDocumentTitle('Agenda · Shifty'))

    expect(document.title).toBe('Agenda · Shifty')
  })

  it('al desmontar devuelve el titulo anterior', () => {
    const { unmount } = renderHook(() => useDocumentTitle('Agenda · Shifty'))

    unmount()

    expect(document.title).toBe('Shifty')
  })

  it('un titulo nuevo reemplaza al anterior y el desmontaje vuelve al original', () => {
    const { rerender, unmount } = renderHook(({ title }) => useDocumentTitle(title), {
      initialProps: { title: 'Mis turnos · Shifty' as string | null }
    })

    rerender({ title: 'Mis turnos · Barberia Uno' })
    expect(document.title).toBe('Mis turnos · Barberia Uno')

    unmount()
    expect(document.title).toBe('Shifty')
  })

  it('sin titulo no toca el documento', () => {
    const { rerender } = renderHook(({ title }) => useDocumentTitle(title), {
      initialProps: { title: null as string | null }
    })
    expect(document.title).toBe('Shifty')

    rerender({ title: '' })
    expect(document.title).toBe('Shifty')
  })
})
