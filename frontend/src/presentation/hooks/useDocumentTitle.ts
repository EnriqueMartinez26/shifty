import { useEffect } from 'react'

/**
 * Pone el titulo de la pestana mientras la pagina esta montada.
 *
 * Sin esto toda pestana decia "Shifty": con el panel y el portal abiertos a la
 * vez no se distinguian. `null`/vacio deja el titulo como esta (p. ej. el
 * portal mientras todavia no llego el nombre de la tienda).
 */
export const useDocumentTitle = (title: string | null | undefined): void => {
  // Sincroniza con el documento (sistema externo): al cambiar el titulo o al
  // desmontar se devuelve el anterior, asi una pagina que no fija el suyo no
  // hereda el de la ultima que paso.
  useEffect(() => {
    if (!title) return undefined
    const previous = document.title
    document.title = title
    return () => {
      document.title = previous
    }
  }, [title])
}
