import {
  billingIntervalLabel,
  slotStatusLabel,
  subscriptionStatusLabel,
  userRoleLabel
} from './enumLabels'

// 2026-10-02, QA en navegador: la UI mostraba valores crudos de la API en
// ingles (CLIENT/STAFF/RECEPTIONIST, ACTIVE/SUSPENDED, available/booked).
describe('etiquetas en castellano de los enums de la API', () => {
  it('roles de usuario', () => {
    expect(userRoleLabel('admin')).toBe('Administrador')
    expect(userRoleLabel('staff')).toBe('Profesional')
    expect(userRoleLabel('receptionist')).toBe('Recepción')
    expect(userRoleLabel('client')).toBe('Cliente')
  })

  it('estados de suscripcion', () => {
    expect(subscriptionStatusLabel('active')).toBe('Activa')
    expect(subscriptionStatusLabel('past_due')).toBe('Pago vencido')
    expect(subscriptionStatusLabel('suspended')).toBe('Suspendida')
    expect(subscriptionStatusLabel('cancelled')).toBe('Cancelada')
  })

  it('intervalos de facturacion', () => {
    expect(billingIntervalLabel('monthly')).toBe('Mensual')
    expect(billingIntervalLabel('quarterly')).toBe('Trimestral')
    expect(billingIntervalLabel('yearly')).toBe('Anual')
    expect(billingIntervalLabel('custom')).toBe('Personalizado')
  })

  it('estados de un horario de la grilla publica', () => {
    expect(slotStatusLabel('available')).toBe('Libre')
    expect(slotStatusLabel('booked')).toBe('Ocupado')
    expect(slotStatusLabel('blocked')).toBe('Bloqueado')
  })

  it('un valor que el front todavia no conoce se muestra crudo', () => {
    expect(userRoleLabel('owner')).toBe('owner')
    expect(subscriptionStatusLabel('trialing')).toBe('trialing')
    expect(billingIntervalLabel('weekly')).toBe('weekly')
    expect(slotStatusLabel('held')).toBe('held')
  })
})
