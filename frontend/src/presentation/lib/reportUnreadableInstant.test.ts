import {
  reportUnknownStatus,
  resetUnreadableInstantReports,
  setUnreadableInstantReporter
} from './reportUnreadableInstant'

const captureMessage = jest.fn()

beforeEach(() => {
  resetUnreadableInstantReports()
  captureMessage.mockClear()
  setUnreadableInstantReporter(captureMessage)
})

describe('reportUnknownStatus', () => {
  it('avisa una vez por estado desconocido, aunque se re-renderice (F8-03)', () => {
    reportUnknownStatus('agenda', 'on_hold')
    reportUnknownStatus('agenda', 'on_hold')

    expect(captureMessage).toHaveBeenCalledTimes(1)
    expect(captureMessage).toHaveBeenCalledWith('Estado desconocido en agenda: on_hold')
  })
})
