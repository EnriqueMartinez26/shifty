import { displayableEmail, isDeliverableEmail, withoutTechnicalEmail } from './deliverableEmail'

// Mismo criterio que notifications/tasks.py::is_deliverable_email.
describe('deliverableEmail', () => {
  it('un email real se muestra', () => {
    expect(isDeliverableEmail('ana@example.com')).toBe(true)
    expect(displayableEmail('ana@example.com')).toBe('ana@example.com')
  })

  it('el email tecnico del alta publica no se muestra', () => {
    const tecnico = '5491155550707@store01m3xx3hzqhynqygq38hwdawjp.noreply'
    expect(isDeliverableEmail(tecnico)).toBe(false)
    expect(displayableEmail(tecnico)).toBeNull()
    expect(displayableEmail('X@STORE1.NOREPLY')).toBeNull()
  })

  it('un nombre armado con el email tecnico cae al respaldo; otro texto queda igual', () => {
    expect(withoutTechnicalEmail('99@store1.noreply', '1155550707')).toBe('1155550707')
    expect(withoutTechnicalEmail('Ana Gomez', '1155550707')).toBe('Ana Gomez')
    expect(withoutTechnicalEmail('ana@example.com', 'x')).toBe('ana@example.com')
  })

  it('vacio o sin arroba no se muestra', () => {
    expect(displayableEmail(null)).toBeNull()
    expect(displayableEmail(undefined)).toBeNull()
    expect(displayableEmail('')).toBeNull()
    expect(displayableEmail('sin-arroba')).toBeNull()
  })
})
