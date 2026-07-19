import { useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import type { FormEvent } from 'react'

import { ApiError } from '../api/client'
import { useAuth } from '../hooks/useAuth'

export function LoginPage() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await login(email, password)
      const from = (location.state as { from?: string } | null)?.from ?? '/chat'
      navigate(from, { replace: true })
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : 'Не удалось войти')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="bg-canvas flex min-h-dvh items-center justify-center p-4">
      <div className="border-line bg-surface w-full max-w-sm rounded-2xl border p-8 shadow-sm">
        <h1 className="text-center text-2xl font-bold tracking-[0.18em]">LYRA</h1>
        <p className="text-ink-muted mt-1 mb-6 text-center text-sm">Вход в базу знаний</p>
        <form onSubmit={(event) => void handleSubmit(event)}>
          <label className="field">
            <span>Email</span>
            <input
              type="email"
              autoComplete="username"
              required
              value={email}
              onChange={(event) => setEmail(event.target.value)}
            />
          </label>
          <label className="field">
            <span>Пароль</span>
            <input
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          </label>
          {error && (
            <p className="text-danger mb-3 text-sm" role="alert">
              {error}
            </p>
          )}
          <button type="submit" className="btn btn-primary w-full" disabled={busy}>
            {busy ? 'Входим…' : 'Войти'}
          </button>
        </form>
      </div>
    </div>
  )
}
