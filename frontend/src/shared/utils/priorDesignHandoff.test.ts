import {
  type PriorDesignHandoff,
  readPriorDesignHandoff,
  savePriorDesignHandoff
} from './priorDesignHandoff'

const resumen = (patch: Partial<PriorDesignHandoff> = {}): PriorDesignHandoff => ({
  appointmentPublicId: 'apt-9',
  serviceName: 'Uñas esculpidas',
  servicesLabel: null,
  addons: [{ name: 'Strass', quantity: 6 }],
  clientFirstName: 'Lucia',
  startsAt: '2026-10-23T18:00:00+00:00',
  message: 'Mandame una foto',
  ...patch
})

describe('priorDesignHandoff', () => {
  beforeEach(() => window.sessionStorage.clear())
  afterEach(() => jest.restoreAllMocks())

  it('devuelve el resumen guardado para el mismo turno de la tienda', () => {
    savePriorDesignHandoff('store-1', resumen())

    expect(readPriorDesignHandoff('store-1', 'apt-9')).toEqual(resumen())
  })

  it('no lo devuelve para otro turno ni para otra tienda', () => {
    savePriorDesignHandoff('store-1', resumen())

    expect(readPriorDesignHandoff('store-1', 'apt-10')).toBeNull()
    expect(readPriorDesignHandoff('store-2', 'apt-9')).toBeNull()
  })

  it('guarda solo lo que arma el mensaje, sin telefono ni email', () => {
    savePriorDesignHandoff('store-1', resumen())

    const guardado = window.sessionStorage.getItem('shifty:prior-design:store-1') ?? ''
    expect(Object.keys(JSON.parse(guardado) as object).sort()).toEqual([
      'addons',
      'appointmentPublicId',
      'clientFirstName',
      'message',
      'serviceName',
      'servicesLabel',
      'startsAt'
    ])
  })

  it.each([
    ['ilegible', '{no es json'],
    ['con otra forma', JSON.stringify({ appointmentPublicId: 'apt-9' })]
  ])('un valor %s es como si no hubiera nada', (_caso, valor) => {
    window.sessionStorage.setItem('shifty:prior-design:store-1', valor)

    expect(readPriorDesignHandoff('store-1', 'apt-9')).toBeNull()
  })

  it('sin storage no tira: guardar no hace nada y leer da null', () => {
    jest.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('bloqueado', 'SecurityError')
    })
    jest.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new DOMException('bloqueado', 'SecurityError')
    })

    expect(() => savePriorDesignHandoff('store-1', resumen())).not.toThrow()
    expect(readPriorDesignHandoff('store-1', 'apt-9')).toBeNull()
  })
})
