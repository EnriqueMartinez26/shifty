import { bulkCancelSkipReason } from './bulkCancelSkipReason'

describe('bulkCancelSkipReason', () => {
  it.each([
    ['APPOINTMENT_ALREADY_CANCELLED', 'Ya estaba cancelada.'],
    ['APPOINTMENT_ALREADY_STARTED', 'El turno ya empezó.'],
    ['APPOINTMENT_NOT_ACTIVE', 'El turno ya no está activo.'],
    ['APPOINTMENT_NOT_FOUND', 'No la encontramos en esta tienda.'],
    ['NOT_FOUND', 'No la encontramos en esta tienda.']
  ])('%s tiene su mensaje', (code, esperado) => {
    expect(bulkCancelSkipReason(code)).toBe(esperado)
  })

  it('un codigo desconocido cae en un mensaje generico sin mostrar el codigo', () => {
    expect(bulkCancelSkipReason('ALGO_NUEVO')).toBe('No se pudo cancelar.')
  })
})
