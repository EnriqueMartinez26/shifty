import { statusStyle } from './appointmentStatusStyle'
import { colors2000s } from '../../theme/colors'

describe('statusStyle', () => {
  it.each([
    ['absent', 'danger'],
    ['pending_payment', 'warning'],
    ['confirmed', 'info'],
    ['completed', 'success']
  ] as const)('mantiene %s en el rol semántico %s', (status, tone) => {
    const color = colors2000s.status[tone]
    expect(statusStyle(status)).toEqual({
      accent: color.accent,
      background: `linear-gradient(180deg, ${color.bg} 0%, ${color.border} 100%)`,
      text: color.text
    })
  })

  it('usa naranja de marca y superficie neutra para estados sin mapeo', () => {
    expect(statusStyle('unknown')).toEqual({
      accent: colors2000s.orange.accent,
      background: 'linear-gradient(180deg, #ffffff 0%, #f6f8f9 100%)',
      text: colors2000s.text.primary
    })
  })
})
