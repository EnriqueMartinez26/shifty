import React, { useState } from 'react'

import { Search } from 'lucide-react'

import { buttonStyles2000s, colors2000s } from '../../../theme/colors'

interface UserSearchFormProps {
  /** Se llama al enviar (Enter o boton), no en cada tecla. */
  onSearch: (term: string) => void
}

/**
 * Busqueda explicita: cada envio es una consulta al servidor, asi que no hay
 * efecto con debounce que dispare una por tecla (regla 27). El tope de 80 es
 * el `max_length` de `q` en `GET /users/`.
 */
export const UserSearchForm: React.FC<UserSearchFormProps> = ({ onSearch }) => {
  const [term, setTerm] = useState('')

  return (
    <form
      role="search"
      className="flex gap-3"
      onSubmit={(e) => {
        e.preventDefault()
        onSearch(term)
      }}
    >
      <div className="relative group flex-1">
        <Search
          className="absolute left-4 top-1/2 -translate-y-1/2 text-gray-400 group-focus-within:text-orange-500 transition-colors"
          size={20}
        />
        <input
          type="search"
          aria-label="Buscar usuario"
          placeholder="NOMBRE, TELÉFONO O EMAIL..."
          maxLength={80}
          className="w-full pl-12 pr-4 py-3.5 rounded-2xl font-black uppercase tracking-widest text-xs outline-none"
          style={{
            background: 'white',
            border: `1px solid ${colors2000s.border.default}`,
            boxShadow: colors2000s.shadows.insetDark,
            color: colors2000s.text.primary
          }}
          value={term}
          onChange={(e) => setTerm(e.target.value)}
        />
      </div>
      <button
        type="submit"
        className="px-6 rounded-2xl font-black uppercase tracking-widest text-xs transition-all active:scale-95"
        style={buttonStyles2000s.default}
      >
        Buscar
      </button>
    </form>
  )
}
