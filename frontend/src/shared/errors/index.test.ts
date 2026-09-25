import * as errors from '@shared/errors'
import * as errorHandler from '@shared/errors/ErrorHandler'
import * as getErrorMessage from '@shared/errors/getErrorMessage'
import * as globalErrorHandler from '@shared/errors/GlobalErrorHandler'

describe('barrel de shared/errors (F12-10)', () => {
  // Antes exportaba 8 de los 11 modulos: getErrorMessage, ErrorHandler y
  // GlobalErrorHandler solo se alcanzaban por ruta directa.
  it.each([
    ['ErrorHandler', errorHandler],
    ['getErrorMessage', getErrorMessage],
    ['GlobalErrorHandler', globalErrorHandler]
  ])('re-exporta todo %s', (_modulo, exported) => {
    for (const [name, value] of Object.entries(exported)) {
      expect(errors).toHaveProperty(name, value)
    }
  })
})
