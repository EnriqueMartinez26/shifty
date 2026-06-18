declare global {
  namespace jest {
    interface Matchers<R> {
      toHaveFocus(): R
      toBeDisabled(): R
      toBeInTheDocument(): R
      toHaveAttribute(attribute: string, value?: string): R
      toHaveTextContent(text: string | RegExp): R
    }
  }
}

expect.extend({
  toHaveFocus(received: HTMLElement) {
    const pass = document.activeElement === received

    return {
      pass,
      message: () =>
        pass
          ? 'Expected element not to have focus.'
          : 'Expected element to have focus, but document.activeElement pointed elsewhere.'
    }
  },
  toBeDisabled(received: HTMLElement) {
    const pass =
      received instanceof HTMLElement &&
      (received.hasAttribute('disabled') || (received as HTMLButtonElement).disabled === true)

    return {
      pass,
      message: () => (pass ? 'Expected element to be enabled.' : 'Expected element to be disabled.')
    }
  },
  toBeInTheDocument(received: HTMLElement | null) {
    const pass = received !== null && document.body.contains(received)

    return {
      pass,
      message: () =>
        pass
          ? 'Expected element not to be in the document.'
          : 'Expected element to be present in the document.'
    }
  },
  toHaveAttribute(received: HTMLElement, attribute: string, value?: string) {
    const actual = received.getAttribute(attribute)
    const pass = value === undefined ? actual !== null : actual === value

    return {
      pass,
      message: () =>
        pass
          ? `Expected element not to have attribute ${attribute}.`
          : `Expected element to have attribute ${attribute}${value === undefined ? '' : ` with value ${value}`}.`
    }
  },
  toHaveTextContent(received: HTMLElement, text: string | RegExp) {
    const actual = received.textContent ?? ''
    const pass = typeof text === 'string' ? actual.includes(text) : text.test(actual)

    return {
      pass,
      message: () =>
        pass
          ? 'Expected element not to have matching text content.'
          : `Expected element to have text content matching ${String(text)}.`
    }
  }
})

export {}
