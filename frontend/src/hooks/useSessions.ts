// Список chat-сессий: постранично (растущее окно от offset 0) — sidebar
// догружает историю по мере скролла, а не тянет всё сразу.

import { useCallback, useEffect, useState } from 'react'

import { ApiError, createSession, listSessions } from '../api/client'
import type { ChatSessionItem } from '../api/types'

const PAGE_SIZE = 20

interface SessionsState {
  sessions: ChatSessionItem[]
  total: number
  loading: boolean
  loadingMore: boolean
  error: string | null
  hasMore: boolean
  refresh: () => Promise<void>
  loadMore: () => Promise<void>
  createNew: () => Promise<string>
}

export function useSessions(): SessionsState {
  const [sessions, setSessions] = useState<ChatSessionItem[]>([])
  const [total, setTotal] = useState(0)
  const [limit, setLimit] = useState(PAGE_SIZE)
  const [loading, setLoading] = useState(true)
  const [loadingMore, setLoadingMore] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async (nextLimit: number, more = false) => {
    if (more) setLoadingMore(true)
    try {
      const response = await listSessions({ limit: nextLimit })
      setSessions(response.items)
      setTotal(response.total)
      setLimit(nextLimit)
      setError(null)
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : 'Не удалось загрузить сессии')
    } finally {
      if (more) setLoadingMore(false)
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load(PAGE_SIZE)
  }, [load])

  const refresh = useCallback(() => load(limit), [load, limit])
  const loadMore = useCallback(() => load(limit + PAGE_SIZE, true), [load, limit])

  const createNew = useCallback(async () => {
    const response = await createSession()
    await load(limit)
    return response.session_id
  }, [load, limit])

  return {
    sessions,
    total,
    loading,
    loadingMore,
    error,
    hasMore: sessions.length < total,
    refresh,
    loadMore,
    createNew,
  }
}
