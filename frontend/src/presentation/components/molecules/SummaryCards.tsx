import React from 'react'

import { colors2000s } from '../../../theme/colors'
import { create2000sPanelStyle } from '../../lib/surfaceStyles'

interface SummaryCard {
  label: string
  value: string | number
}

interface SummaryCardsProps {
  cards: SummaryCard[]
  columns: 3 | 4
}

// Clases literales: Tailwind solo genera las que encuentra escritas enteras.
const GRID_COLUMNS: Record<SummaryCardsProps['columns'], string> = {
  3: 'md:grid-cols-3',
  4: 'md:grid-cols-4'
}

/** Fila de indicadores (etiqueta + numero) de las pantallas operativas. */
export const SummaryCards: React.FC<SummaryCardsProps> = ({ cards, columns }) => (
  <div className={`grid grid-cols-1 ${GRID_COLUMNS[columns]} gap-4`}>
    {cards.map((card) => (
      <div key={card.label} className="p-5 rounded-2xl" style={create2000sPanelStyle()}>
        <p
          className="text-[10px] font-black uppercase tracking-widest"
          style={{ color: colors2000s.text.secondary }}
        >
          {card.label}
        </p>
        <p className="mt-2 text-2xl font-black" style={{ color: colors2000s.orange.accent }}>
          {card.value}
        </p>
      </div>
    ))}
  </div>
)
