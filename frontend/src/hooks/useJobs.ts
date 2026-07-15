// Ingest-jobs с поллингом: пока есть активные job — опрос каждые 3 секунды.

import { useCallback, useEffect, useRef, useState } from 'react'

import { ApiError, listJobs } from '../api/client'
import type { IngestJob } from '../api/types'

const POLL_INTERVAL_MS = 3000

const ACTIVE_STATUSES = new Set(['queued', 'processing'])

interface JobsState {
  jobs: IngestJob[]
  loading: boolean
  error: string | null
  refresh: () => Promise<void>
}

export function useJobs(enabled: boolean): JobsState {
  const [jobs, setJobs] = useState<IngestJob[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const timerRef = useRef<number | null>(null)

  const refresh = useCallback(async () => {
    try {
      const response = await listJobs()
      setJobs(response.items)
      setError(null)
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : 'Не удалось загрузить задачи')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (!enabled) return
    void refresh()
    return () => {
      if (timerRef.current !== null) window.clearTimeout(timerRef.current)
    }
  }, [enabled, refresh])

  useEffect(() => {
    if (!enabled) return
    const hasActive = jobs.some((job) => ACTIVE_STATUSES.has(job.status))
    if (!hasActive) return
    timerRef.current = window.setTimeout(() => {
      void refresh()
    }, POLL_INTERVAL_MS)
    return () => {
      if (timerRef.current !== null) window.clearTimeout(timerRef.current)
    }
  }, [enabled, jobs, refresh])

  return { jobs, loading, error, refresh }
}
