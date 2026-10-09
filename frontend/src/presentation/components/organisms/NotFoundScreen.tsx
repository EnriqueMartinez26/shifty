import React from 'react'

import { ArrowRight, Home } from 'lucide-react'
import { Link, useLocation } from 'react-router'

import { AuthShell } from './AuthShell'
import { buttonStyles2000s } from '../../../theme/colors'
import { useDocumentTitle } from '../../hooks/useDocumentTitle'

/** `/b/<slug>/...` o `/booking/<slug>/...`: la ruta de la tienda, con el prefijo que se uso. */
const STORE_PATH = /^\/(b|booking)\/([^/]+)/

/**
 * La portada de la tienda bajo la que cae la direccion, si cae bajo una y no
 * es ya esa portada (ofrecer "volver" a la misma pagina no saca de ningun lado).
 */
const storePathOf = (pathname: string): string | null => {
  const match = STORE_PATH.exec(pathname)
  if (!match) return null
  const storePath = `/${match[1]}/${match[2]}`
  return pathname.replace(/\/+$/, '') === storePath ? null : storePath
}

const BUTTON_CLASS =
  'w-full font-bold py-4 rounded-2xl flex items-center justify-center gap-2 transition-all active:scale-[0.98]'

interface NotFoundScreenProps {
  title?: string
  subtitle?: string
}

/**
 * Pantalla 404 con la cascara de acceso. Si la direccion cae bajo una tienda
 * (`/b/<slug>/...`), ofrece volver a esa tienda antes que al inicio.
 */
export const NotFoundScreen: React.FC<NotFoundScreenProps> = ({
  title = 'Página no encontrada',
  subtitle = 'La dirección que abriste no existe o cambió.'
}) => {
  const { pathname } = useLocation()
  const storePath = storePathOf(pathname)
  useDocumentTitle(`${title} · Shifty`)

  return (
    <AuthShell title={title} subtitle={subtitle}>
      <div className="space-y-4">
        {storePath && (
          <Link to={storePath} className={BUTTON_CLASS} style={buttonStyles2000s.selected}>
            Volver a la tienda
            <ArrowRight className="w-4 h-4" aria-hidden="true" />
          </Link>
        )}
        <Link
          to="/"
          className={BUTTON_CLASS}
          style={storePath ? buttonStyles2000s.default : buttonStyles2000s.selected}
        >
          <Home className="w-4 h-4" aria-hidden="true" />
          Ir al inicio
        </Link>
      </div>
    </AuthShell>
  )
}
