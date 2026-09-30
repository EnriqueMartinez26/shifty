// F9-08 (2026-09-30): cobertura de reportes. El rango, la pagina, los
// profesionales y la tendencia ya los fija QueryParams.test.ts (F9-11, FF-30);
// aca van las claves exactas del resumen y la exportacion.
const mockGet = jest.fn()
const mockPost = jest.fn()

jest.mock('@infrastructure/http/client', () => ({
  __esModule: true,
  default: {
    get: (...args: unknown[]) => mockGet(...args),
    post: (...args: unknown[]) => mockPost(...args)
  }
}))

import { reportsService, type ReportExportFormat } from './ReportsService'

const paramsOf = (call: number): Record<string, unknown> =>
  (mockGet.mock.calls[call] as [string, { params: Record<string, unknown> }])[1].params

describe('ReportsService.getSummary', () => {
  beforeEach(() => {
    mockGet.mockReset()
    mockGet.mockResolvedValue({ data: {} })
  })

  // El backend acepta `order` (F3-06, default "asc"); hoy el front no lo
  // manda nunca, con o sin pagina: el detalle llega del mas viejo al mas nuevo.
  it('sin pagina manda solo el rango y con pagina suma limit y offset, nunca order', async () => {
    await reportsService.getSummary('2026-09-01', '2026-09-30')
    await reportsService.getSummary('2026-09-01', '2026-09-30', { limit: 50, offset: 0 })

    expect(mockGet.mock.calls.map(([path]) => path)).toEqual([
      '/reports/summary',
      '/reports/summary'
    ])
    expect(Object.keys(paramsOf(0))).toEqual(['from_date', 'to_date'])
    expect(paramsOf(1)).toEqual({
      from_date: '2026-09-01',
      to_date: '2026-09-30',
      limit: 50,
      offset: 0
    })
    expect(paramsOf(1)).not.toHaveProperty('order')
  })
})

describe('ReportsService.exportReport', () => {
  beforeEach(() => {
    mockPost.mockReset()
  })

  const exportar = (format: ReportExportFormat, headers: Record<string, string> = {}) => {
    mockPost.mockResolvedValue({ data: 'contenido', headers })
    return reportsService.exportReport({ format, fromDate: '2026-09-01', toDate: '2026-09-30' })
  }

  it('pide el archivo por POST con el rango en el cuerpo y responseType blob', async () => {
    await exportar('csv')

    expect(mockPost).toHaveBeenCalledWith(
      '/reports/export',
      { format: 'csv', from_date: '2026-09-01', to_date: '2026-09-30' },
      { responseType: 'blob' }
    )
  })

  it.each<[ReportExportFormat, string, string]>([
    ['csv', 'text/csv', 'reporte-turnos.csv'],
    [
      'excel',
      'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      'reporte-turnos.xlsx'
    ],
    ['pdf', 'application/pdf', 'reporte-turnos.pdf']
  ])(
    '%s: el Blob lleva %s y sin content-disposition el nombre es %s',
    async (format, type, filename) => {
      const result = await exportar(format)

      expect(result.blob).toBeInstanceOf(Blob)
      expect(result.blob.type).toBe(type)
      expect(result.filename).toBe(filename)
    }
  )

  it('toma el nombre de content-disposition y le saca las comillas', async () => {
    const result = await exportar('excel', {
      'content-disposition': 'attachment; filename="turnos-septiembre.xlsx"'
    })

    expect(result.filename).toBe('turnos-septiembre.xlsx')
  })

  it('toma el nombre sin comillas, como lo manda hoy el backend', async () => {
    const result = await exportar('pdf', {
      'content-disposition': 'attachment; filename=reporte-turnos-2026-09-01-2026-09-30.pdf'
    })

    expect(result.filename).toBe('reporte-turnos-2026-09-01-2026-09-30.pdf')
  })
})
