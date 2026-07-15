// Отправка фидбека (UC-7) с обработкой ошибок тостом.

import { useCallback, useState } from 'react'

import { ApiError, sendFeedback } from '../api/client'
import type { FeedbackRating } from '../api/types'

interface FeedbackState {
  sentFor: Set<string>
  submit: (messageId: string, rating: FeedbackRating, comment?: string) => Promise<boolean>
}

export function useFeedback(onApiError: (message: string) => void): FeedbackState {
  const [sentFor, setSentFor] = useState<Set<string>>(new Set())

  const submit = useCallback(
    async (messageId: string, rating: FeedbackRating, comment?: string) => {
      try {
        await sendFeedback({ message_id: messageId, rating, comment })
        setSentFor((current) => new Set(current).add(messageId))
        return true
      } catch (cause) {
        onApiError(cause instanceof ApiError ? cause.message : 'Не удалось отправить фидбек')
        return false
      }
    },
    [onApiError],
  )

  return { sentFor, submit }
}
