// Auth-контекст: JWT только в памяти (правило .claude/rules/frontend.md).
// Перезагрузка страницы = перелогин (refresh-токенов в MVP нет).

import { createContext, useCallback, useContext, useMemo, useState } from 'react'
import type { ReactNode } from 'react'

import { login as apiLogin, setAccessToken } from '../api/client'
import type { ApiUser } from '../api/types'

interface AuthState {
  user: ApiUser | null
  login: (email: string, password: string) => Promise<void>
  logout: () => void
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<ApiUser | null>(null)

  const login = useCallback(async (email: string, password: string) => {
    const response = await apiLogin(email, password)
    setAccessToken(response.access_token)
    setUser(response.user)
  }, [])

  const logout = useCallback(() => {
    setAccessToken(null)
    setUser(null)
  }, [])

  const value = useMemo(() => ({ user, login, logout }), [user, login, logout])
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthState {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth вне AuthProvider')
  return context
}
