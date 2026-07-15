// Источники: список (viewer), создание Confluence и ручной sync (editor).

import { useCallback, useEffect, useState } from 'react'

import { ApiError, createSource, listSources, syncSource } from '../api/client'
import type { SourceCreateRequest, SourceItem } from '../api/types'

interface SourcesState {
  sources: SourceItem[]
  loading: boolean
  error: string | null
  // collection_id по умолчанию для upload: у корпуса MVP одна коллекция
  defaultCollectionId: string | null
  refresh: () => Promise<void>
  create: (body: SourceCreateRequest) => Promise<void>
  sync: (sourceId: string) => Promise<void>
}

export function useSources(onApiError: (message: string) => void): SourcesState {
  const [sources, setSources] = useState<SourceItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const response = await listSources()
      setSources(response.items)
      setError(null)
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : 'Не удалось загрузить источники')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const create = useCallback(
    async (body: SourceCreateRequest) => {
      try {
        await createSource(body)
        await refresh()
      } catch (cause) {
        onApiError(cause instanceof ApiError ? cause.message : 'Не удалось создать источник')
        throw cause
      }
    },
    [refresh, onApiError],
  )

  const sync = useCallback(
    async (sourceId: string) => {
      try {
        await syncSource(sourceId)
      } catch (cause) {
        onApiError(cause instanceof ApiError ? cause.message : 'Не удалось запустить синхронизацию')
      }
    },
    [onApiError],
  )

  return {
    sources,
    loading,
    error,
    defaultCollectionId: sources[0]?.collection_id ?? null,
    refresh,
    create,
    sync,
  }
}
