import { act, renderHook, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { Mock } from 'vitest'

import type { FinalEvent } from '../api/types'

vi.mock('../api/client', () => ({
  ApiError: class ApiError extends Error {},
  listMessages: vi.fn(async () => ({ items: [], total: 0 })),
  streamChatMessage: vi.fn(),
}))

import * as api from './../api/client'
import { useChat } from './useChat'

const FINAL: FinalEvent = {
  message_id: 'm1',
  answer: 'Ответ [1].',
  refusal: false,
  citations: [],
  confidence: { label: 'high', score: 0.9 },
  degraded: false,
  trace_id: 'tr_1',
  usage: { llm_calls: 3, prompt_tokens: 10, completion_tokens: 5, took_ms: 100 },
  nearest_documents: [],
}

const streamMock = api.streamChatMessage as unknown as Mock

describe('useChat', () => {
  it('первое сообщение в новую сессию не абортится сменой sessionId', async () => {
    let sawAbort: boolean | null = null
    streamMock.mockImplementation(
      async (
        _sid: string,
        _content: string,
        onEvent: (event: api.ChatStreamEvent) => void,
        signal: AbortSignal,
      ) => {
        onEvent({ type: 'status', data: { stage: 'generating' } })
        onEvent({ type: 'token', data: { text: 'Ответ ' } })
        // Даём эффекту смены sessionId шанс сработать до финала
        await new Promise((resolve) => setTimeout(resolve, 20))
        sawAbort = signal.aborted
        onEvent({ type: 'final', data: FINAL })
      },
    )
    const onError = vi.fn()
    const { result, rerender } = renderHook(
      ({ sid }: { sid: string | null }) => useChat(sid, onError),
      { initialProps: { sid: null as string | null } },
    )

    let sendPromise: Promise<void> | undefined
    act(() => {
      sendPromise = result.current.send('s1', 'вопрос')
    })
    // ChatPage делает setSessionId сразу после createNew — воспроизводим
    rerender({ sid: 's1' })
    await act(async () => {
      await sendPromise
    })

    expect(sawAbort).toBe(false)
    expect(onError).not.toHaveBeenCalled()
    expect(result.current.messages.map((message) => message.role)).toEqual(['user', 'assistant'])
    expect(result.current.finalById['m1']?.trace_id).toBe('tr_1')
  })

  it('переключение на другую сессию абортит активный стрим', async () => {
    let signalRef: AbortSignal | null = null
    streamMock.mockImplementation(
      async (
        _sid: string,
        _content: string,
        _onEvent: (event: api.ChatStreamEvent) => void,
        signal: AbortSignal,
      ) => {
        signalRef = signal
        await new Promise((resolve) => setTimeout(resolve, 1000))
      },
    )
    const onError = vi.fn()
    const { result, rerender } = renderHook(
      ({ sid }: { sid: string | null }) => useChat(sid, onError),
      { initialProps: { sid: 's1' as string | null } },
    )
    await waitFor(() => expect(result.current.loadingHistory).toBe(false))

    act(() => {
      void result.current.send('s1', 'вопрос')
    })
    rerender({ sid: 's2' })

    await waitFor(() => expect(signalRef?.aborted).toBe(true))
  })
})
