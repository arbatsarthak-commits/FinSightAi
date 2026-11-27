const configuredUrl = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.trim()

export let apiBaseUrl = (configuredUrl || '').replace(/\/$/, '')
let pairingToken = ''

export function setApiBaseUrl(value: string): void {
  const parsed = new URL(value.trim())
  const localHosts = new Set(['localhost', '127.0.0.1', '[::1]'])
  if (parsed.protocol !== 'https:' && !(parsed.protocol === 'http:' && localHosts.has(parsed.hostname))) {
    throw new Error('Remote backends must use HTTPS. HTTP is allowed only for a local loopback backend.')
  }
  apiBaseUrl = parsed.toString().replace(/\/$/, '')
}

if (configuredUrl) setApiBaseUrl(configuredUrl)

export function setPairingToken(token: string): void {
  pairingToken = token
}

function connectionError(): Error {
  return new Error(
    'Could not reach the backend at ' + apiBaseUrl +
    '. Confirm the configured API URL is reachable and the backend is listening.'
  )
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  if (!apiBaseUrl) throw new Error('Configure VITE_API_BASE_URL or enter a backend URL when connecting.')
  const headers = new Headers(options.headers)
  if (pairingToken) headers.set('X-Pairing-Token', pairingToken)
  let response: Response
  try {
    response = await fetch(`${apiBaseUrl}${path}`, { ...options, headers })
  } catch (error) {
    if (error instanceof TypeError) throw connectionError()
    throw error
  }
  if (!response.ok) {
    let message = `Request failed (${response.status})`
    try {
      const body = await response.json()
      message = body.detail || message
    } catch {
      // The response has no JSON body.
    }
    throw new Error(message)
  }
  return response.json() as Promise<T>
}

export async function downloadReport(): Promise<void> {
  if (!apiBaseUrl) throw new Error('Configure VITE_API_BASE_URL or enter a backend URL when connecting.')
  const headers = new Headers()
  headers.set('X-Pairing-Token', pairingToken)
  let response: Response
  try {
    response = await fetch(`${apiBaseUrl}/api/reports/export`, { headers })
  } catch (error) {
    if (error instanceof TypeError) throw connectionError()
    throw error
  }
  if (!response.ok) throw new Error('Report export failed. Check backend connection.')
  const blob = await response.blob()
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = 'invoice_report.csv'
  link.click()
  URL.revokeObjectURL(url)
}
