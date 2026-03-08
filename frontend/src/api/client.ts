import axios from 'axios'

let accessToken: string | null = null
let refreshPromise: Promise<string | null> | null = null

export function setAccessToken(token: string | null) {
  accessToken = token
}

export function getAccessToken(): string | null {
  return accessToken
}

const apiClient = axios.create({
  baseURL: '/api/v1',
  headers: { 'Content-Type': 'application/json' },
  withCredentials: true, // send httpOnly refresh cookie
})

apiClient.interceptors.request.use((config) => {
  if (accessToken) {
    config.headers.Authorization = `Bearer ${accessToken}`
  }

  // Fix v2 URL paths: calls using `/api/v2/...` would get double-prefixed
  // as `/api/v1/api/v2/...` because baseURL is `/api/v1`.
  // Strip the baseURL for absolute API paths so they resolve correctly.
  const url = config.url ?? ''
  if (url.startsWith('/api/')) {
    config.baseURL = ''
  }

  return config
})

async function refreshAccessToken(): Promise<string | null> {
  try {
    // Refresh token is sent automatically via httpOnly cookie (withCredentials: true)
    const res = await axios.post<{ access_token: string }>(
      '/api/v1/auth/token/refresh',
      {},
      { withCredentials: true },
    )
    const newToken = res.data.access_token
    setAccessToken(newToken)
    return newToken
  } catch {
    setAccessToken(null)
    return null
  }
}

apiClient.interceptors.response.use(
  (response) => response,
  async (error) => {
    const original = error.config
    if (error.response?.status === 401 && !original._retry) {
      original._retry = true

      // Deduplicate concurrent refresh calls
      if (!refreshPromise) {
        refreshPromise = refreshAccessToken().finally(() => {
          refreshPromise = null
        })
      }

      const newToken = await refreshPromise
      if (newToken) {
        original.headers.Authorization = `Bearer ${newToken}`
        return apiClient(original)
      }
    }
    return Promise.reject(error)
  },
)

export default apiClient
