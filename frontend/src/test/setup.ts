/**
 * Jest Setup File
 * Runs before all tests
 */

declare var require: any;

// Setup global crypto polyfill for Node.js / JSDOM test environments
const customGlobal = globalThis as any;

if (typeof customGlobal.crypto === 'undefined') {
  try {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const nodeCrypto = require('crypto');
    Object.defineProperty(customGlobal, 'crypto', {
      value: nodeCrypto.webcrypto || nodeCrypto,
      writable: true,
    });
  } catch (e) {
    // Fail-safe fallback if not in a Node environment
  }
}

if (customGlobal.crypto && typeof customGlobal.crypto.randomUUID === 'undefined') {
  try {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const nodeCrypto = require('crypto');
    Object.defineProperty(customGlobal.crypto, 'randomUUID', {
      value: () => {
        const crypt = nodeCrypto.webcrypto || nodeCrypto;
        return crypt.randomUUID ? crypt.randomUUID() : 'test-uuid-random-fallback';
      },
      writable: true,
    });
  } catch (e) {
    // Fail-safe fallback if not in a Node environment
  }
}
