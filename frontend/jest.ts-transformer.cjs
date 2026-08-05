/**
 * Transformer de Jest = ts-jest + neutralizacion de `import.meta`.
 *
 * react-router v8 (y cookie-es) se distribuyen solo como ESM y usan
 * `import.meta.hot` (hook HMR de Vite). ts-jest emite CommonJS para Jest, donde
 * `import.meta` es sintaxis invalida y rompe la carga del modulo. Como el unico
 * uso real es el guard de HMR (siempre undefined fuera de Vite), lo reemplazamos
 * en los archivos de node_modules antes de delegar en ts-jest.
 */
const { createTransformer } = require('ts-jest').default

const tsJest = createTransformer({
  tsconfig: {
    module: 'esnext',
    moduleResolution: 'bundler',
    jsx: 'react-jsx',
    esModuleInterop: true,
    allowSyntheticDefaultImports: true,
    allowJs: true
  }
})

function neutralizeImportMeta(sourceText, sourcePath) {
  if (!sourcePath.includes('node_modules')) return sourceText
  return sourceText
    .replace(/import\.meta\.hot/g, 'undefined')
    .replace(/import\.meta/g, '({ url: __filename })')
}

module.exports = {
  canInstrument: tsJest.canInstrument,
  getCacheKey(sourceText, sourcePath, options) {
    return tsJest.getCacheKey(neutralizeImportMeta(sourceText, sourcePath), sourcePath, options)
  },
  getCacheKeyAsync(sourceText, sourcePath, options) {
    return tsJest.getCacheKeyAsync(
      neutralizeImportMeta(sourceText, sourcePath),
      sourcePath,
      options
    )
  },
  process(sourceText, sourcePath, options) {
    return tsJest.process(neutralizeImportMeta(sourceText, sourcePath), sourcePath, options)
  },
  processAsync(sourceText, sourcePath, options) {
    return tsJest.processAsync(neutralizeImportMeta(sourceText, sourcePath), sourcePath, options)
  }
}
