// Список chat-сессий пользователя (серверное состояние: loading/error/data).

import { useCallback, useEffect, useState } from 'react'

import { ApiError, createSession, listSessions } from '../api/client'
import type { ChatSessionItem } from '../api/types'

interface SessionsState {
  sessions: ChatSessionItem[]
  loading: boolean
  error: string | null
  refresh: () => Promise<void>
  createNew: () => Promise<string>
}

export function useSessions(): SessionsState {
  const [sessions, setSessions] = useState<ChatSessionItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const response = await listSessions()
      setSessions(response.items)
      setError(null)
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : 'Не удалось загрузить сессии')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const createNew = useCallback(async () => {
    const response = await createSession()
    await refresh()
    return response.session_id
  }, [refresh])

  return { sessions, loading, error, refresh, createNew }
}
