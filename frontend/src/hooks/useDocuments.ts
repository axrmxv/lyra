// Документы: постранично (растущее окно от offset 0) + удаление (editor).

import { useCallback, useEffect, useState } from 'react'

import { ApiError, deleteDocument, listDocuments } from '../api/client'
import type { DocumentItem } from '../api/types'

const PAGE_SIZE = 20

interface DocumentsState {
  documents: DocumentItem[]
  total: number
  loading: boolean
  error: string | null
  hasMore: boolean
  refresh: () => Promise<void>
  loadMore: () => Promise<void>
  remove: (documentId: string) => Promise<void>
}

export function useDocuments(onApiError: (message: string) => void): DocumentsState {
  const [documents, setDocuments] = useState<DocumentItem[]>([])
  const [total, setTotal] = useState(0)
  const [limit, setLimit] = useState(PAGE_SIZE)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async (nextLimit: number) => {
    setLoading(true)
    try {
      const response = await listDocuments({ limit: nextLimit })
      setDocuments(response.items)
      setTotal(response.total)
      setLimit(nextLimit)
      setError(null)
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : 'Не удалось загрузить документы')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load(PAGE_SIZE)
  }, [load])

  const refresh = useCallback(() => load(limit), [load, limit])
  const loadMore = useCallback(() => load(limit + PAGE_SIZE), [load, limit])

  const remove = useCallback(
    async (documentId: string) => {
      try {
        await deleteDocument(documentId)
        await load(limit)
      } catch (cause) {
        onApiError(cause instanceof ApiError ? cause.message : 'Не удалось удалить документ')
      }
    },
    [load, limit, onApiError],
  )

  return {
    documents,
    total,
    loading,
    error,
    hasMore: documents.length < total,
    refresh,
    loadMore,
    remove,
  }
}
