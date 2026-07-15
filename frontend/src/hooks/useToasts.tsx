// Тосты ошибок/уведомлений: ошибки API показываются пользователю осмысленно.

import { createContext, useCallback, useContext, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'

export interface Toast {
  id: number
  kind: 'error' | 'info'
  message: string
}

interface ToastState {
  toasts: Toast[]
  pushToast: (message: string, kind?: Toast['kind']) => void
  dismissToast: (id: number) => void
}

const ToastContext = createContext<ToastState | null>(null)

const TOAST_TTL_MS = 6000

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])
  const nextId = useRef(1)

  const dismissToast = useCallback((id: number) => {
    setToasts((current) => current.filter((toast) => toast.id !== id))
  }, [])

  const pushToast = useCallback(
    (message: string, kind: Toast['kind'] = 'error') => {
      const id = nextId.current++
      setToasts((current) => [...current, { id, kind, message }])
      window.setTimeout(() => dismissToast(id), TOAST_TTL_MS)
    },
    [dismissToast],
  )

  const value = useMemo(
    () => ({ toasts, pushToast, dismissToast }),
    [toasts, pushToast, dismissToast],
  )
  return <ToastContext.Provider value={value}>{children}</ToastContext.Provider>
}

export function useToasts(): ToastState {
  const context = useContext(ToastContext)
  if (!context) throw new Error('useToasts вне ToastProvider')
  return context
}
