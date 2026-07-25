import { renderHook, waitFor } from '@testing-library/react'
import { act } from 'react'
import { describe, expect, it, vi } from 'vitest'
import type { Mock } from 'vitest'

import type { ChatSessionItem } from '../api/types'

vi.mock('../api/client', () => ({
  ApiError: class ApiError extends Error {},
  listSessions: vi.fn(),
  createSession: vi.fn(async () => ({ session_id: 'new' })),
}))

import * as api from '../api/client'
import { useSessions } from './useSessions'

const listMock = api.listSessions as unknown as Mock

const session = (n: number): ChatSessionItem => ({
  id: `s${n}`,
  title: `Чат ${n}`,
  created_at: '2026-07-20T10:00:00Z',
})

describe('useSessions — ленивая подгрузка', () => {
  it('грузит первую страницу, hasMore по total, loadMore расширяет окно', async () => {
    const db = Array.from({ length: 30 }, (_, i) => session(i))
    listMock.mockImplementation(async ({ limit }: { limit: number }) => ({
      items: db.slice(0, limit),
      total: db.length,
    }))

    const { result } = renderHook(() => useSessions())

    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.sessions).toHaveLength(20)
    expect(result.current.total).toBe(30)
    expect(result.current.hasMore).toBe(true)
    expect(listMock).toHaveBeenLastCalledWith({ limit: 20 })

    await act(async () => {
      await result.current.loadMore()
    })
    expect(result.current.sessions).toHaveLength(30)
    expect(result.current.hasMore).toBe(false)
    expect(result.current.loadingMore).toBe(false)
    expect(listMock).toHaveBeenLastCalledWith({ limit: 40 })
  })
})
