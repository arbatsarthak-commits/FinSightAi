const configuredUrl = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.trim()
const TOKEN_IN_URL_MESSAGE =
  'You entered a pairing token in the Backend API URL field. Enter http://127.0.0.1:8000 as the backend URL and paste your token in the Pairing Token field.'

export let apiBaseUrl = ''
let pairingToken = ''
let configurationError = ''

export class BackendRequestError extends Error {
  readonly status?: number

  constructor(message: string, status?: number) {
    super(message)
    this.name = 'BackendRequestError'
    this.status = status
  }
}

function isLoopbackHost(hostname: string): boolean {
  const host = hostname.toLowerCase().replace(/^\[|\]$/g, '').replace(/\.$/, '')
  if (host === 'localhost' || host.endsWith('.localhost') || host === '::1') {
    return true
  }
  const octets = host.split('.')
  return octets.length === 4 &&
    octets[0] === '127' &&
    octets.every((octet) => /^\d{1,3}$/.test(octet) && Number(octet) <= 255)
}

export function normalizeApiBaseUrl(value: string): string {
  const candidate = typeof value === 'string' ? value.trim() : ''
  if (!candidate) {
    throw new Error('Enter the Backend API URL.')
  }
  if (/^[A-Za-z0-9_-]{32,}$/.test(candidate)) {
    throw new Error(TOKEN_IN_URL_MESSAGE)
  }
  if (!/^[A-Za-z][A-Za-z0-9+.-]*:\/\//.test(candidate)) {
    throw new Error('Enter a valid backend URL including http:// or https://.')
  }

  let parsed: URL
  try {
    parsed = new URL(candidate)
  } catch {
    throw new Error('Invalid backend URL. Check the address and try again.')
  }

  if (parsed.username || parsed.password || parsed.search || parsed.hash) {
    throw new Error('Enter the backend base URL without credentials, query parameters, or a fragment.')
  }
  if (parsed.protocol !== 'https:' && !(parsed.protocol === 'http:' && isLoopbackHost(parsed.hostname))) {
    throw new Error('Remote backends must use HTTPS. HTTP is allowed only for a loopback backend.')
  }

  parsed.pathname = parsed.pathname.replace(/\/+$/, '') || '/'
  return parsed.toString().replace(/\/+$/, '')
}

if (configuredUrl) {
  try {
    apiBaseUrl = normalizeApiBaseUrl(configuredUrl)
  } catch (error) {
    configurationError = error instanceof Error ? error.message : 'The configured backend URL is invalid.'
  }
}

export function getApiConfigurationError(): string {
  return configurationError
}

export function setApiBaseUrl(value: string): void {
  apiBaseUrl = normalizeApiBaseUrl(value)
  configurationError = ''
}

export function setPairingToken(token: string): void {
  pairingToken = token.trim()
}

function unavailableMessage(url: string, phase: string): string {
  return `Could not reach the backend at ${url} during ${phase}. Check that the backend is running and that the URL and port are correct. If it is running, check that CORS allows this frontend origin. For the hosted GitHub Pages app, also allow this site to access your computer's local network in browser permissions.`
}

async function fetchWithTimeout(
  url: string,
  init: RequestInit,
  phase: string,
  timeoutMs = 8000,
): Promise<Response> {
  const controller = new AbortController()
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs)
  try {
    return await fetch(url, { ...init, signal: controller.signal })
  } catch (error) {
    if (controller.signal.aborted) {
      throw new BackendRequestError(`Connection timed out while checking ${phase}. Confirm the backend is running and try again.`)
    }
    if (error instanceof TypeError) {
      throw new BackendRequestError(unavailableMessage(url, phase))
    }
    throw new BackendRequestError(`The ${phase} request failed. Check the backend and try again.`)
  } finally {
    window.clearTimeout(timeout)
  }
}

async function checkBackendHealth(baseUrl: string): Promise<void> {
  const response = await fetchWithTimeout(
    `${baseUrl}/api/health`,
    { method: 'GET', headers: { Accept: 'application/json' }, credentials: 'omit' },
    'backend health check',
  )
  if (!response.ok) {
    throw new BackendRequestError(
      `Backend health check failed (HTTP ${response.status}). Verify that this URL and port point to the FinSightAI backend.`,
      response.status,
    )
  }
  try {
    const body = await response.json()
    if (body?.status !== 'ok') {
      throw new Error('Unexpected health response.')
    }
  } catch {
    throw new BackendRequestError('Backend health check failed: the response was not a valid FinSightAI health response.')
  }
}

export async function connectToBackend(
  url: string,
  token: string,
  onStatus: (status: string) => void = () => undefined,
): Promise<void> {
  setPairingToken('')
  const baseUrl = normalizeApiBaseUrl(url)
  const trimmedToken = token.trim()
  if (!trimmedToken) {
    throw new Error('Enter the pairing token printed in the backend terminal.')
  }

  onStatus('Checking backend health…')
  await checkBackendHealth(baseUrl)

  setApiBaseUrl(baseUrl)
  onStatus('Authenticating pairing token…')
  const response = await fetchWithTimeout(
    `${baseUrl}/api/system/status`,
    {
      method: 'GET',
      headers: { Accept: 'application/json', 'X-Pairing-Token': trimmedToken },
      credentials: 'omit',
    },
    'authenticated backend check',
    20000,
  )
  if (response.status === 401) {
    throw new Error('Incorrect pairing token (HTTP 401). Copy the token from the backend terminal and try again.')
  }
  if (!response.ok) {
    throw new BackendRequestError(
      `Authenticated backend check failed (HTTP ${response.status}). Verify that this URL points to the FinSightAI backend.`,
      response.status,
    )
  }
  try {
    await response.json()
  } catch {
    throw new BackendRequestError('The authenticated backend check returned an unreadable response.')
  }
  setPairingToken(trimmedToken)
  onStatus('Backend connected and authenticated.')
}

function connectionError(url: string): BackendRequestError {
  return new BackendRequestError(unavailableMessage(url, 'the API request'))
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  if (!apiBaseUrl) {
    throw new BackendRequestError(configurationError || 'Connect to a backend before making API requests.')
  }
  const headers = new Headers(options.headers)
  if (pairingToken) headers.set('X-Pairing-Token', pairingToken)
  let response: Response
  try {
    response = await fetch(`${apiBaseUrl}${path}`, { ...options, headers })
  } catch (error) {
    if (error instanceof TypeError) throw connectionError(apiBaseUrl)
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new BackendRequestError('The backend request timed out. Check that the backend is running and try again.')
    }
    throw error
  }
  if (!response.ok) {
    let message = `Request failed (HTTP ${response.status}).`
    try {
      const body = await response.json()
      if (typeof body.detail === 'string') message = body.detail
    } catch {
      // The response has no readable JSON body.
    }
    throw new BackendRequestError(message, response.status)
  }
  return response.json() as Promise<T>
}

export async function downloadReport(): Promise<void> {
  if (!apiBaseUrl) {
    throw new BackendRequestError(configurationError || 'Connect to a backend before exporting a report.')
  }
  const headers = new Headers()
  if (pairingToken) headers.set('X-Pairing-Token', pairingToken)
  let response: Response
  try {
    response = await fetch(`${apiBaseUrl}/api/reports/export`, { headers })
  } catch (error) {
    if (error instanceof TypeError) throw connectionError(apiBaseUrl)
    throw error
  }
  if (!response.ok) {
    throw new BackendRequestError(`Report export failed (HTTP ${response.status}).`, response.status)
  }
  const blob = await response.blob()
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = 'invoice_report.csv'
  link.click()
  URL.revokeObjectURL(url)
}
