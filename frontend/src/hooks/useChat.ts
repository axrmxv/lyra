// История сообщений сессии + отправка с SSE-стримингом через редьюсер.

import { useCallback, useEffect, useReducer, useRef, useState } from 'react'

import { ApiError, listMessages, streamChatMessage } from '../api/client'
import type { ChatMessageItem, FinalEvent } from '../api/types'
import { chatStreamReducer, initialStreamState } from './chatStreamReducer'
import type { StreamState } from './chatStreamReducer'

interface ChatState {
  messages: ChatMessageItem[]
  loadingHistory: boolean
  stream: StreamState
  // Полные final-payload'ы этой сессии просмотра: degraded, nearest_documents,
  // trace_id — история их не хранит, живой стрим — да
  finalById: Record<string, FinalEvent>
  send: (sessionId: string, content: string) => Promise<void>
}

export function useChat(
  sessionId: string | null,
  onApiError: (message: string) => void,
): ChatState {
  const [messages, setMessages] = useState<ChatMessageItem[]>([])
  const [finalById, setFinalById] = useState<Record<string, FinalEvent>>({})
  const [loadingHistory, setLoadingHistory] = useState(false)
  const [stream, dispatch] = useReducer(chatStreamReducer, initialStreamState)
  const abortRef = useRef<AbortController | null>(null)
  // Сессия, в которую прямо сейчас идёт send: смена sessionId на неё
  // (первое сообщение в новую сессию) не должна рвать собственный стрим
  const streamingSessionRef = useRef<string | null>(null)

  useEffect(() => {
    if (sessionId !== null && sessionId === streamingSessionRef.current) return
    // Смена сессии: рвём активный стрим и грузим историю
    abortRef.current?.abort()
    dispatch({ type: 'reset' })
    if (!sessionId) {
      setMessages([])
      return
    }
    let cancelled = false
    setLoadingHistory(true)
    listMessages(sessionId)
      .then((response) => {
        if (!cancelled) setMessages(response.items)
      })
      .catch((cause: unknown) => {
        if (!cancelled) {
          onApiError(cause instanceof ApiError ? cause.message : 'Не удалось загрузить историю')
        }
      })
      .finally(() => {
        if (!cancelled) setLoadingHistory(false)
      })
    return () => {
      cancelled = true
      abortRef.current?.abort()
    }
  }, [sessionId, onApiError])

  const send = useCallback(
    async (targetSessionId: string, content: string) => {
      const controller = new AbortController()
      abortRef.current = controller
      streamingSessionRef.current = targetSessionId
      const localUserMessage: ChatMessageItem = {
        id: `local-${Date.now()}`,
        role: 'user',
        content,
        confidence: null,
        refusal: false,
        created_at: new Date().toISOString(),
        citations: [],
      }
      setMessages((current) => [...current, localUserMessage])
      dispatch({ type: 'start' })
      try {
        await streamChatMessage(
          targetSessionId,
          content,
          (event) => {
            dispatch(event)
            if (event.type === 'final') {
              const assistantMessage: ChatMessageItem = {
                id: event.data.message_id,
                role: 'assistant',
                content: event.data.answer,
                confidence: event.data.confidence,
                refusal: event.data.refusal,
                created_at: new Date().toISOString(),
                citations: event.data.citations,
              }
              setMessages((current) => [...current, assistantMessage])
              setFinalById((current) => ({ ...current, [event.data.message_id]: event.data }))
            }
          },
          controller.signal,
        )
        dispatch({ type: 'reset' })
      } catch (cause) {
        dispatch({ type: 'reset' })
        if (controller.signal.aborted) return
        onApiError(cause instanceof ApiError ? cause.message : 'Ошибка отправки сообщения')
      } finally {
        if (streamingSessionRef.current === targetSessionId) {
          streamingSessionRef.current = null
        }
      }
    },
    [onApiError],
  )

  return { messages, loadingHistory, stream, finalById, send }
}
