const configuredUrl = import.meta.env.VITE_API_BASE_URL as string | undefined

export const apiBaseUrl = (configuredUrl || 'http://127.0.0.1:8000').replace(/\/$/, '')
let pairingToken = ''

export function setPairingToken(token: string): void {
  pairingToken = token
}

function connectionError(): Error {
  const hosted = window.location.hostname.endsWith('github.io')
  if (hosted) {
    return new Error(
      'Could not reach the local backend. Start FastAPI at http://127.0.0.1:8000, allow local-network access for this GitHub Pages site in your browser, and check the pairing token.'
    )
  }
  return new Error(
    'Could not reach the backend at ' + apiBaseUrl + '. Start FastAPI and confirm it is listening on this address.'
  )
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
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
