// Ingest-jobs: постранично (растущее окно) + поллинг активных каждые 3с.
// total у /ingest/jobs — длина страницы, поэтому «есть ещё» определяем по
// заполненности окна (items.length === limit), а не по total.

import { useCallback, useEffect, useRef, useState } from 'react'

import { ApiError, listJobs } from '../api/client'
import type { IngestJob } from '../api/types'

const POLL_INTERVAL_MS = 3000
const PAGE_SIZE = 20

const ACTIVE_STATUSES = new Set(['queued', 'processing'])

interface JobsState {
  jobs: IngestJob[]
  loading: boolean
  error: string | null
  hasMore: boolean
  refresh: () => Promise<void>
  loadMore: () => Promise<void>
}

export function useJobs(enabled: boolean): JobsState {
  const [jobs, setJobs] = useState<IngestJob[]>([])
  const [limit, setLimit] = useState(PAGE_SIZE)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const timerRef = useRef<number | null>(null)

  const load = useCallback(async (nextLimit: number) => {
    try {
      const response = await listJobs({ limit: nextLimit })
      setJobs(response.items)
      setLimit(nextLimit)
      setError(null)
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : 'Не удалось загрузить задачи')
    } finally {
      setLoading(false)
    }
  }, [])

  const refresh = useCallback(() => load(limit), [load, limit])
  const loadMore = useCallback(() => load(limit + PAGE_SIZE), [load, limit])

  useEffect(() => {
    if (!enabled) return
    void load(PAGE_SIZE)
    return () => {
      if (timerRef.current !== null) window.clearTimeout(timerRef.current)
    }
  }, [enabled, load])

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

  return { jobs, loading, error, hasMore: jobs.length === limit, refresh, loadMore }
}
