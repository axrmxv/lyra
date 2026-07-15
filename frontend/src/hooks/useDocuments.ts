// Документы: список и удаление (editor).

import { useCallback, useEffect, useState } from 'react'

import { ApiError, deleteDocument, listDocuments } from '../api/client'
import type { DocumentItem } from '../api/types'

interface DocumentsState {
  documents: DocumentItem[]
  loading: boolean
  error: string | null
  refresh: () => Promise<void>
  remove: (documentId: string) => Promise<void>
}

export function useDocuments(onApiError: (message: string) => void): DocumentsState {
  const [documents, setDocuments] = useState<DocumentItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const response = await listDocuments()
      setDocuments(response.items)
      setError(null)
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : 'Не удалось загрузить документы')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const remove = useCallback(
    async (documentId: string) => {
      try {
        await deleteDocument(documentId)
        await refresh()
      } catch (cause) {
        onApiError(cause instanceof ApiError ? cause.message : 'Не удалось удалить документ')
      }
    },
    [refresh, onApiError],
  )

  return { documents, loading, error, refresh, remove }
}
