import api from './api'

const TOKEN_KEY = 'auth_token'

export const authService = {
  async login(email: string, password: string): Promise<string> {
    const { data } = await api.post<{ token: string }>('/auth/login', { email, password })
    localStorage.setItem(TOKEN_KEY, data.token)
    return data.token
  },

  async signup(email: string, password: string): Promise<string> {
    const { data } = await api.post<{ token: string }>('/auth/signup', { email, password })
    localStorage.setItem(TOKEN_KEY, data.token)
    return data.token
  },

  logout(): void {
    localStorage.removeItem(TOKEN_KEY)
  },

  getToken(): string | null {
    return localStorage.getItem(TOKEN_KEY)
  },

  isAuthenticated(): boolean {
    const token = localStorage.getItem(TOKEN_KEY)
    if (!token) return false
    try {
      // Decode payload (no verification — server validates on every request)
      const payload = JSON.parse(atob(token.split('.')[1]))
      return payload.exp * 1000 > Date.now()
    } catch {
      return false
    }
  },

  getEmail(): string | null {
    const token = localStorage.getItem(TOKEN_KEY)
    if (!token) return null
    try {
      const payload = JSON.parse(atob(token.split('.')[1]))
      return payload.email ?? null
    } catch {
      return null
    }
  },
}
