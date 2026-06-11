import { createContext, useCallback, useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { authService } from '../services/auth'

interface AuthContextValue {
  isAuthenticated: boolean
  email: string | null
  login: (email: string, password: string) => Promise<void>
  signup: (email: string, password: string) => Promise<void>
  logout: () => void
}

export const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [isAuthenticated, setIsAuthenticated] = useState(authService.isAuthenticated())
  const [email, setEmail] = useState<string | null>(authService.getEmail())

  // Re-check on mount in case token expired while tab was closed
  useEffect(() => {
    const ok = authService.isAuthenticated()
    setIsAuthenticated(ok)
    setEmail(ok ? authService.getEmail() : null)
  }, [])

  const login = useCallback(async (email: string, password: string) => {
    await authService.login(email, password)
    setIsAuthenticated(true)
    setEmail(authService.getEmail())
  }, [])

  const signup = useCallback(async (email: string, password: string) => {
    await authService.signup(email, password)
    setIsAuthenticated(true)
    setEmail(authService.getEmail())
  }, [])

  const logout = useCallback(() => {
    authService.logout()
    setIsAuthenticated(false)
    setEmail(null)
  }, [])

  return (
    <AuthContext.Provider value={{ isAuthenticated, email, login, signup, logout }}>
      {children}
    </AuthContext.Provider>
  )
}
