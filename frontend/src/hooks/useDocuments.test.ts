import { renderHook, waitFor } from '@testing-library/react'
import { act } from 'react'
import { describe, expect, it, vi } from 'vitest'
import type { Mock } from 'vitest'

import type { DocumentItem } from '../api/types'

vi.mock('../api/client', () => ({
  ApiError: class ApiError extends Error {},
  listDocuments: vi.fn(),
  deleteDocument: vi.fn(async () => undefined),
}))

import * as api from '../api/client'
import { useDocuments } from './useDocuments'

const listMock = api.listDocuments as unknown as Mock

const doc = (n: number): DocumentItem => ({
  id: `d${n}`,
  source_id: 's1',
  external_id: `e${n}`,
  title: `Документ ${n}`,
  url: null,
  author: null,
  status: 'active',
  active_version_id: `v${n}`,
  created_at: '2026-07-20T10:00:00Z',
})

describe('useDocuments — пагинация', () => {
  it('hasMore по total; loadMore расширяет окно и закрывает пагинацию', async () => {
    const db = Array.from({ length: 30 }, (_, i) => doc(i))
    listMock.mockImplementation(async ({ limit }: { limit: number }) => ({
      items: db.slice(0, limit),
      total: db.length,
    }))

    const { result } = renderHook(() => useDocuments(vi.fn()))

    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.documents).toHaveLength(20)
    expect(result.current.total).toBe(30)
    expect(result.current.hasMore).toBe(true)

    await act(async () => {
      await result.current.loadMore()
    })
    expect(result.current.documents).toHaveLength(30)
    expect(result.current.hasMore).toBe(false)
    expect(listMock).toHaveBeenLastCalledWith({ limit: 40 })
  })
})
