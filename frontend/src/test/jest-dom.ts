declare global {
  namespace jest {
    interface Matchers<R> {
      toHaveFocus(): R
      toBeDisabled(): R
      toBeInTheDocument(): R
      toHaveAttribute(attribute: string, value?: string): R
      toHaveTextContent(text: string | RegExp): R
      toHaveClass(...classNames: string[]): R
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
  },
  // Mismo criterio que @testing-library/jest-dom: pasa si tiene TODAS.
  // Sin elemento falla siempre, tambien con `.not`.
  toHaveClass(received: Element | null, ...classNames: string[]) {
    if (!(received instanceof Element)) {
      throw new Error('toHaveClass necesita un elemento y recibio null.')
    }
    const actual = [...received.classList]
    const pass = classNames.every((name) => actual.includes(name))

    return {
      pass,
      message: () =>
        pass
          ? `Expected element not to have classes ${classNames.join(' ')}.`
          : `Expected element to have classes ${classNames.join(' ')}, got "${actual.join(' ')}".`
    }
  }
})

export {}
