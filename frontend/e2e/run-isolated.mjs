import { randomBytes, randomUUID } from 'node:crypto'
import { createServer } from 'node:net'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { readFile, rm, writeFile } from 'node:fs/promises'
import { spawn } from 'node:child_process'
import { fileURLToPath } from 'node:url'

const frontendDir = resolve(fileURLToPath(new URL('..', import.meta.url)))
const repoRoot = resolve(frontendDir, '..')
const composeFile = join(repoRoot, 'docker-compose.yml')
const e2eComposeFile = join(repoRoot, 'docker-compose.e2e.yml')
const runId = process.env.E2E_ISOLATED_RUN_ID ?? `local-${randomUUID().replaceAll('-', '')}`
const project = process.env.E2E_COMPOSE_PROJECT ?? `shifty-qa-${runId}`
const ci = process.env.CI === 'true'
const tempDir = process.env.RUNNER_TEMP ?? tmpdir()
const envPath = join(tempDir, `${project}.env`)
const composePrefix = [
  'compose',
  '--project-name',
  project,
  '--env-file',
  envPath,
  '-f',
  composeFile,
  '-f',
  e2eComposeFile
]

if (!/^[a-z0-9-]{8,80}$/.test(runId) || project !== `shifty-qa-${runId}`) {
  throw new Error('Identificador del proyecto E2E inválido')
}

const randomHex = (size = 32) => randomBytes(size).toString('hex')
const superadminEmail = `e2e-${runId.replaceAll('-', '')}@example.com`
const superadminPassword = `Qa${randomHex(16)}7x`
const storeAdminEmail = `store-${runId.replaceAll('-', '')}@example.com`
const storeAdminPassword = `Qa${randomHex(16)}8y`
const slug = `qa-e2e-${runId}`
const postgresUser = `shifty_${randomHex(4)}`

const envFile =
  [
    'ENV=development',
    `APP_VERSION=e2e-${runId}`,
    `SECRET_KEY=${randomHex()}`,
    `FIELD_ENCRYPTION_KEY=${randomHex()}`,
    `POSTGRES_USER=${postgresUser}`,
    `POSTGRES_PASSWORD=${randomHex()}`,
    'POSTGRES_DB=shifty_qa',
    'APP_DB_USER=shifty_app',
    `APP_DB_PASSWORD=${randomHex()}`,
    'RABBITMQ_DEFAULT_USER=shifty',
    `RABBITMQ_DEFAULT_PASS=${randomHex()}`,
    'POSTGRES_SSL=disable',
    'FRONTEND_URL=http://127.0.0.1:13000',
    'PUBLIC_API_URL=http://127.0.0.1:13000/api',
    'CORS_ORIGINS=http://127.0.0.1:13000',
    'VITE_API_URL=/api',
    'OTP_PROVIDER=console',
    'OTP_DEBUG_EXPOSE_CODE=false',
    'SMTP_HOST=127.0.0.1',
    'SMTP_PORT=1',
    'SMTP_USER=',
    'SMTP_PASS=',
    'EMAILS_FROM_EMAIL=qa@example.com',
    'MERCADOPAGO_OAUTH_CLIENT_ID=',
    'MERCADOPAGO_OAUTH_CLIENT_SECRET=',
    'MERCADOPAGO_OAUTH_REDIRECT_URI=',
    'MERCADOPAGO_WEBHOOK_SECRET=',
    'SENTRY_DSN=',
    'EXPOSE_API_DOCS=false',
    'RATE_LIMIT_ENABLED=true',
    'LOG_LEVEL=WARNING'
  ].join('\n') + '\n'

function run(command, args, { cwd = repoRoot, env = process.env, silent = false } = {}) {
  return new Promise((resolveRun, rejectRun) => {
    const child = spawn(command, args, {
      cwd,
      env,
      stdio: silent ? 'ignore' : 'inherit',
      shell: false
    })
    child.once('error', rejectRun)
    child.once('exit', (code) => {
      if (code === 0) resolveRun()
      else rejectRun(new Error(`Falló ${command} (código ${code ?? 'desconocido'})`))
    })
  })
}

async function assertLoopbackPortFree(port) {
  await new Promise((resolvePort, rejectPort) => {
    const server = createServer()
    server.once('error', () => rejectPort(new Error(`El puerto loopback ${port} ya está ocupado`)))
    server.listen(port, '127.0.0.1', () =>
      server.close((error) => (error ? rejectPort(error) : resolvePort()))
    )
  })
}

async function waitFor(command, args, description, attempts = 120) {
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    try {
      await run(command, args, { silent: true })
      return
    } catch {
      await new Promise((resolveWait) => setTimeout(resolveWait, 1_000))
    }
  }
  throw new Error(`No quedó listo el servicio descartable: ${description}`)
}

async function waitForHttp(url, description, attempts = 120) {
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    try {
      const response = await fetch(url, { signal: AbortSignal.timeout(3_000) })
      if (response.ok) return
    } catch {
      // Espera acotada: nunca se sustituye la URL local por otro entorno.
    }
    await new Promise((resolveWait) => setTimeout(resolveWait, 1_000))
  }
  throw new Error(`No quedó listo el servicio descartable: ${description}`)
}

const apiBaseUrl = 'http://127.0.0.1:13000/api'

async function api(path, { token, method = 'GET', body } = {}) {
  const response = await fetch(`${apiBaseUrl}${path}`, {
    method,
    headers: {
      ...(body === undefined ? {} : { 'content-type': 'application/json' }),
      ...(token ? { authorization: `Bearer ${token}` } : {})
    },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal: AbortSignal.timeout(15_000)
  })
  if (!response.ok) {
    throw new Error(
      `Falló la preparación del fixture en ${method} ${path} (HTTP ${response.status})`
    )
  }
  if (response.status === 204) return null
  const value = await response.json()
  return value && typeof value === 'object' && 'data' in value ? value.data : value
}

// El fixture viaja a Playwright por el entorno del proceso hijo, nunca por un
// archivo. De la respuesta de la API solo se toman ids con forma de ULID;
// nombres, duraciones y precios son los que este script mandó, y se comparan
// con lo que devolvió la API antes de usarlos.
const ULID = /^[0-9A-HJKMNP-TV-Z]{26}$/

function assertUlid(value, what) {
  if (typeof value !== 'string' || !ULID.test(value)) {
    throw new Error(`La API aislada devolvió un id inválido para ${what}`)
  }
  return value
}

async function prepareFixture() {
  const globalLogin = await api('/auth/login', {
    method: 'POST',
    body: { email: superadminEmail, password: superadminPassword }
  })
  const store = await api('/superadmin/stores', {
    method: 'POST',
    token: globalLogin.access_token,
    body: { name: `Tienda QA ${runId}`, slug }
  })
  await api(`/superadmin/stores/${store.public_id}/admins`, {
    method: 'POST',
    token: globalLogin.access_token,
    body: {
      email: storeAdminEmail,
      password: storeAdminPassword,
      first_name: 'Admin',
      last_name: 'QA'
    }
  })
  const storeLogin = await api('/auth/login', {
    method: 'POST',
    body: { email: storeAdminEmail, password: storeAdminPassword }
  })
  const token = storeLogin.access_token
  const businessHours = Object.fromEntries(
    ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'].map((day) => [
      day,
      [{ open: '09:00', close: '18:00' }]
    ])
  )
  await api('/stores/me', {
    method: 'PATCH',
    token,
    body: {
      allow_manual_coordination: true,
      min_booking_notice_hours: 0,
      business_hours: businessHours,
      send_email_confirmation: false,
      send_email_reminders: false
    }
  })
  await api('/stores/me/feature-flags', {
    method: 'PUT',
    token,
    body: { multi_service_booking: true, otp_booking: false, payments: false }
  })

  const services = []
  for (const [baseName, durationMinutes, price] of [
    ['QA Corte', 30, 1111],
    ['QA Barba', 20, 2222]
  ]) {
    const name = `${baseName} ${runId.slice(-6)}`
    const created = await api('/services/', {
      method: 'POST',
      token,
      body: {
        name,
        duration_minutes: durationMinutes,
        price,
        deposit_mode: 'none',
        deposit_type: 'percent',
        deposit_amount: null
      }
    })
    if (
      created.name !== name ||
      created.duration_minutes !== durationMinutes ||
      created.price !== price
    ) {
      throw new Error(`La API aislada no devolvió el servicio pedido (${baseName})`)
    }
    services.push({ id: assertUlid(created.public_id, baseName), name, durationMinutes, price })
  }
  const staff = await api('/staff/', {
    method: 'POST',
    token,
    body: {
      kind: 'resource',
      display_name: 'Recurso QA',
      service_ids: services.map((service) => service.id)
    }
  })
  const staffId = assertUlid(staff.public_id, 'el profesional')
  for (let day = 0; day <= 6; day += 1) {
    await api(`/staff/${staffId}/schedules`, {
      method: 'POST',
      token,
      body: { day_of_week: day, start_time: '09:00:00', end_time: '18:00:00' }
    })
  }

  return JSON.stringify({
    kind: 'shifty-isolated-e2e-v1',
    runId,
    storeSlug: slug,
    staffId,
    services
  })
}

let composeStarted = false
let cleanupError
try {
  const packageJson = JSON.parse(await readFile(join(frontendDir, 'package.json'), 'utf8'))
  const supportedVersions = (range) =>
    typeof range === 'string' ? range.split('||').map((version) => version.trim()) : []
  const supportedNodeVersions = supportedVersions(packageJson.engines?.node)
  if (!supportedNodeVersions.includes(process.versions.node)) {
    throw new Error(
      `Se requiere una versión de Node declarada en package.json (${supportedNodeVersions.join(' o ')}); ` +
        `se encontró ${process.versions.node}`
    )
  }
  const npmVersion = process.env.npm_config_user_agent?.match(/(?:^|\s)npm\/([^\s]+)/)?.[1]
  if (!npmVersion) throw new Error('Ejecutá el E2E con npm run e2e:isolated para verificar npm')
  const supportedNpmVersions = supportedVersions(packageJson.engines?.npm)
  if (!supportedNpmVersions.includes(npmVersion)) {
    throw new Error(
      `Se requiere una versión de npm declarada en package.json (${supportedNpmVersions.join(' o ')}); ` +
        `se encontró ${npmVersion}`
    )
  }

  await assertLoopbackPortFree(13000)
  await assertLoopbackPortFree(18000)
  await writeFile(envPath, envFile, { mode: 0o600 })
  console.log('Preparando stack Docker descartable y aislado para Playwright...')
  await run('docker', [...composePrefix, 'build', 'backend', 'frontend'])
  composeStarted = true
  await run('docker', [
    ...composePrefix,
    'up',
    '-d',
    'db',
    'redis_cache',
    'redis_state',
    'rabbitmq'
  ])
  await waitFor(
    'docker',
    [...composePrefix, 'exec', '-T', 'db', 'pg_isready', '-U', postgresUser, '-d', 'shifty_qa'],
    'PostgreSQL'
  )
  await waitFor(
    'docker',
    [...composePrefix, 'exec', '-T', 'redis_cache', 'redis-cli', 'ping'],
    'Redis de caché'
  )
  await waitFor(
    'docker',
    [...composePrefix, 'exec', '-T', 'redis_state', 'redis-cli', 'ping'],
    'Redis de estado'
  )
  await waitFor(
    'docker',
    [...composePrefix, 'exec', '-T', 'rabbitmq', 'rabbitmq-diagnostics', '-q', 'check_running'],
    'RabbitMQ'
  )

  await run(
    'docker',
    [...composePrefix, 'run', '--rm', '--no-deps', 'backend', 'alembic', 'upgrade', 'head'],
    {
      silent: true
    }
  )
  await run(
    'docker',
    [
      ...composePrefix,
      'run',
      '--rm',
      '--no-deps',
      '-e',
      'SUPERADMIN_EMAIL',
      '-e',
      'SUPERADMIN_PASSWORD',
      'backend',
      'python',
      'scripts/bootstrap_superadmin.py'
    ],
    {
      env: {
        ...process.env,
        SUPERADMIN_EMAIL: superadminEmail,
        SUPERADMIN_PASSWORD: superadminPassword
      },
      silent: true
    }
  )
  await run('docker', [...composePrefix, 'up', '-d', 'backend', 'frontend', 'nginx'])
  await waitForHttp(`${apiBaseUrl}/ops/health/ready`, 'API')
  await waitForHttp('http://127.0.0.1:13000/', 'frontend')
  const fixtureJson = await prepareFixture()

  const playwrightEnv = {
    ...process.env,
    E2E_ISOLATED: '1',
    E2E_ISOLATED_RUN_ID: runId,
    E2E_FIXTURE_JSON: fixtureJson,
    E2E_BASE_URL: 'http://127.0.0.1:13000',
    E2E_API_URL: apiBaseUrl
  }
  await run(process.execPath, ['node_modules/@playwright/test/cli.js', 'test'], {
    cwd: frontendDir,
    env: playwrightEnv
  })
} finally {
  if (composeStarted) {
    try {
      await run('docker', [...composePrefix, 'down', '--volumes', '--remove-orphans'], {
        silent: true
      })
    } catch (error) {
      cleanupError = error
    }
  }
  if (!ci || !composeStarted) await rm(envPath, { force: true })
}

if (cleanupError) throw cleanupError
