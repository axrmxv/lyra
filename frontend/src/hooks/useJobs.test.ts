import { renderHook, waitFor } from '@testing-library/react'
import { act } from 'react'
import { describe, expect, it, vi } from 'vitest'
import type { Mock } from 'vitest'

import type { IngestJob } from '../api/types'

vi.mock('../api/client', () => ({
  ApiError: class ApiError extends Error {},
  listJobs: vi.fn(),
}))

import * as api from '../api/client'
import { useJobs } from './useJobs'

const listMock = api.listJobs as unknown as Mock

const job = (n: number): IngestJob => ({
  id: `j${n}`,
  kind: 'upload',
  status: 'completed', // не active — поллинг не запускается, таймеров в тесте нет
  steps: {},
  error: null,
  source_id: 's1',
  document_version_id: `v${n}`,
  created_at: '2026-07-20T10:00:00Z',
})

describe('useJobs — пагинация', () => {
  it('hasMore по заполненности окна (total ненадёжен); loadMore расширяет', async () => {
    const db = Array.from({ length: 30 }, (_, i) => job(i))
    // Бэкенд отдаёт total = длине страницы — сознательно воспроизводим
    listMock.mockImplementation(async ({ limit }: { limit: number }) => {
      const items = db.slice(0, limit)
      return { items, total: items.length }
    })

    const { result } = renderHook(() => useJobs(true))

    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.jobs).toHaveLength(20)
    expect(result.current.hasMore).toBe(true) // окно заполнено → возможно есть ещё

    await act(async () => {
      await result.current.loadMore()
    })
    expect(result.current.jobs).toHaveLength(30)
    expect(result.current.hasMore).toBe(false) // 30 !== 40 → больше нет
    expect(listMock).toHaveBeenLastCalledWith({ limit: 40 })
  })
})
