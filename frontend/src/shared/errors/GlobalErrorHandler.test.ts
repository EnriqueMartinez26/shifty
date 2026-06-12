import { GlobalErrorHandler } from './GlobalErrorHandler'
import { ErrorHandler } from './ErrorHandler'
import { ValidationError } from './ValidationError'
import { UnauthorizedError } from './UnauthorizedError'

class MockHandler extends ErrorHandler {
  private readonly targetClass: any

  constructor(targetClass: any) {
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
