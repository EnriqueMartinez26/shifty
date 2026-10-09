import { ErrorHandler } from './ErrorHandler'
import { GlobalErrorHandler } from './GlobalErrorHandler'
import { RequestCanceledError } from './RequestCanceledError'
import { UnauthorizedError } from './UnauthorizedError'
import { ValidationError } from './ValidationError'

const canceled = new RequestCanceledError('x', { errorCode: 'REQUEST_CANCELED', statusCode: 0 })

class MockHandler extends ErrorHandler {
  private readonly targetClass: Function

  constructor(targetClass: Function) {
    super()
    this.targetClass = targetClass
  }
  public canHandle(error: unknown): boolean {
    return error instanceof this.targetClass
  }
  public handle = jest.fn().mockResolvedValue(undefined)
}

describe('GlobalErrorHandler (Strategy Router)', () => {
  let globalHandler: GlobalErrorHandler
  let validationHandler: MockHandler
  let unauthorizedHandler: MockHandler

  beforeEach(() => {
    globalHandler = new GlobalErrorHandler()
    validationHandler = new MockHandler(ValidationError)
    unauthorizedHandler = new MockHandler(UnauthorizedError)

    globalHandler.registerHandler(validationHandler)
    globalHandler.registerHandler(unauthorizedHandler)
  })

  it('should successfully route specific errors to their matching registered handler', async () => {
    const err = new ValidationError('Invalid inputs')

    await globalHandler.handle(err)

    expect(validationHandler.handle).toHaveBeenCalledTimes(1)
    expect(validationHandler.handle).toHaveBeenCalledWith(err)
    expect(unauthorizedHandler.handle).not.toHaveBeenCalled()
  })

  it.each([
    ['tipada', canceled],
    ['envuelta por BaseService', Object.assign(new Error('x'), { originalError: canceled })]
  ])('una consulta cancelada %s no llega a ningun handler ni se registra', async (_caso, error) => {
    // 2026-10-02: una consulta cancelada por react-query se reportaba como
    // error de red a Sentry. Sin handler propio caia al fallback, que la
    // registraba con console.error.
    const catchAll = new MockHandler(Error)
    globalHandler.registerHandler(catchAll)
    const spyConsole = jest.spyOn(console, 'error').mockImplementation(() => {})

    await globalHandler.handle(error)

    expect(catchAll.handle).not.toHaveBeenCalled()
    expect(spyConsole).not.toHaveBeenCalled()
    spyConsole.mockRestore()
  })

  it('should route using the fallback strategy if no handler can handle the error type', async () => {
    const rawError = new Error('Some random DB crash')
    const spyConsole = jest.spyOn(console, 'error').mockImplementation(() => {})

    await globalHandler.handle(rawError)

    expect(validationHandler.handle).not.toHaveBeenCalled()
    expect(unauthorizedHandler.handle).not.toHaveBeenCalled()
    expect(spyConsole).toHaveBeenCalled()

    spyConsole.mockRestore()
  })
})
