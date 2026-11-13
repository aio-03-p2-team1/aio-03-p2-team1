const BASE = (import.meta.env?.VITE_API_BASE_URL || '/api/v1').replace(/\/$/, '')
export const API_BASE = BASE

export class ApiError extends Error {
  constructor(status, detail) {
    super(detail?.message || '요청을 처리하지 못했어요.')
    this.status = status
    this.code = detail?.code || (status ? `http_${status}` : 'network')
    this.detail = detail
  }
}

let onUnauthorized = () => {}
export function setUnauthorizedHandler(fn) {
  onUnauthorized = fn
}

export async function api(path, { method = 'GET', body, auth = true, signal } = {}) {
  let res
  try {
    res = await fetch(BASE + path, {
      method,
      credentials: 'include',
      headers: body ? { 'Content-Type': 'application/json' } : undefined,
      body: body ? JSON.stringify(body) : undefined,
      signal
    })
  } catch (err) {
    if (err?.name === 'AbortError') throw err
    throw new ApiError(0, { code: 'network', message: '서버에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.' })
  }
  if (res.status === 204) return null
  const type = res.headers.get('content-type') || ''
  const data = type.includes('application/json') ? await res.json() : null
  if (!res.ok || data === null) {
    const detail = data?.detail && typeof data.detail === 'object' ? data.detail : { code: res.ok ? 'bad_response' : `http_${res.status}` }
    if (res.status === 401 && auth) onUnauthorized()
    throw new ApiError(res.status, detail)
  }
  return data
}
