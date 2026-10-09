import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import { mkdtempSync, readFileSync, rmSync, existsSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { test } from 'node:test'
import { fileURLToPath } from 'node:url'

const source = fileURLToPath(new URL('./security-headers.conf', import.meta.url))
const script = fileURLToPath(new URL('./configure-analytics-csp.mjs', import.meta.url))

function buildPolicy(id, check) {
  const directory = mkdtempSync(join(tmpdir(), 'shifty-csp-'))
  const output = join(directory, 'headers.conf')
  try {
    const result = spawnSync(process.execPath, [script, source, output], {
      env: { ...process.env, VITE_GA4_MEASUREMENT_ID: id },
      encoding: 'utf8'
    })
    check(result, output)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
}

test('GA4 apagado conserva todos los headers byte por byte', () => {
  buildPolicy('', (result, output) => {
    assert.equal(result.status, 0, result.stderr)
    assert.equal(readFileSync(output, 'utf8'), readFileSync(source, 'utf8'))
  })
})

test('GA4 habilitado agrega solo destinos exactos y mantiene las guardas', () => {
  buildPolicy('G-ABC1234567', (result, output) => {
    assert.equal(result.status, 0, result.stderr)
    const policy = readFileSync(output, 'utf8')
    assert.match(policy, /script-src 'self' https:\/\/www\.googletagmanager\.com;/)
    assert.match(
      policy,
      /connect-src 'self' https:\/\/www\.google-analytics\.com https:\/\/region1\.google-analytics\.com;/
    )
    assert.match(
      policy,
      /frame-ancestors 'none'; base-uri 'none'; object-src 'none'; form-action 'self'/
    )
    assert.doesNotMatch(policy, /script-src[^;]*unsafe|\*\.google/)
  })
})

test('Un ID malformado no genera una politica permisiva', () => {
  buildPolicy('G-ABC; script-src *', (result, output) => {
    assert.notEqual(result.status, 0)
    assert.equal(existsSync(output), false)
  })
})
