import { render, screen } from '@testing-library/react'

import { BookingPriceSummary } from './BookingPriceSummary'

const strassX2 = [{ addonId: 'strass', name: 'Strass', unitPrice: 500, quantity: 2, amount: 1000 }]

const resumen = () => screen.getByTestId('booking-price-summary')

// 2026-10-16 (pedido de Mateo): sin adicionales ni descuento el resumen decia
// "Servicio $ 27.000" y abajo "Total $ 27.000", el mismo numero dos veces.
describe('BookingPriceSummary', () => {
  it('sin adicionales ni descuento muestra solo el total', () => {
    render(<BookingPriceSummary basePrice={27000} addons={[]} discount={null} total={27000} />)

    expect(resumen()).toHaveTextContent(/^Total\s*\$\s*27\.000$/)
    expect(resumen()).not.toHaveTextContent('Servicio')
  })

  it('un descuento en cero no cuenta como descuento', () => {
    render(<BookingPriceSummary basePrice={27000} addons={[]} discount={0} total={27000} />)

    expect(resumen()).not.toHaveTextContent('Servicio')
    expect(screen.queryByTestId('booking-price-discount')).not.toBeInTheDocument()
  })

  it('con adicionales detalla servicio, cada adicional y total', () => {
    render(
      <BookingPriceSummary basePrice={27000} addons={strassX2} discount={null} total={28000} />
    )

    expect(resumen()).toHaveTextContent(/Servicio\s*\$\s*27\.000/)
    expect(resumen()).toHaveTextContent(/Strass x2\s*\$\s*1\.000/)
    expect(resumen()).toHaveTextContent(/Total\s*\$\s*28\.000/)
  })

  it('con descuento y sin adicionales detalla servicio, descuento y total', () => {
    render(
      <BookingPriceSummary
        basePrice={5000}
        addons={[]}
        discount={500}
        promotionCode="BIENVENIDA10"
        total={4500}
      />
    )

    expect(resumen()).toHaveTextContent(/Servicio\s*\$\s*5\.000/)
    expect(screen.getByTestId('booking-price-discount')).toHaveTextContent(
      /Descuento \(BIENVENIDA10\)\s*-\$\s*500/
    )
    expect(resumen()).toHaveTextContent(/Total\s*\$\s*4\.500/)
  })

  it('sin total confirmado dice "Calculando…" o el aviso que se le pase', () => {
    const { rerender } = render(
      <BookingPriceSummary basePrice={5000} addons={[]} discount={null} total={null} />
    )
    expect(resumen()).toHaveTextContent(/^Total\s*Calculando…$/)

    rerender(
      <BookingPriceSummary
        basePrice={5000}
        addons={[]}
        discount={null}
        total={null}
        pendingLabel="Sin confirmar"
      />
    )
    expect(resumen()).toHaveTextContent(/^Total\s*Sin confirmar$/)
  })

  // Varios servicios en un turno (2026-10-16): una linea por servicio, cada
  // una con sus adicionales; el total sigue siendo el que se le pasa.
  it('con varios servicios detalla cada uno con sus adicionales', () => {
    render(
      <BookingPriceSummary
        basePrice={15000}
        addons={[]}
        serviceLines={[
          { serviceId: 'corte', name: 'Corte', price: 10000, addons: [] },
          {
            serviceId: 'barba',
            name: 'Barba',
            price: 5000,
            addons: [
              { addonId: 'toalla', name: 'Toalla', unitPrice: 500, quantity: 2, amount: 1000 }
            ]
          }
        ]}
        discount={null}
        total={16000}
      />
    )

    expect(resumen()).toHaveTextContent(
      /^Corte\s*\$\s*10\.000Barba\s*\$\s*5\.000Toalla x2\s*\$\s*1\.000Total\s*\$\s*16\.000$/
    )
    expect(screen.queryByText('Servicio')).not.toBeInTheDocument()
  })
})
