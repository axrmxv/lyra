// 👍/👎 с опциональным комментарием (UC-7).

import { useState } from 'react'

import type { FeedbackRating } from '../api/types'

interface FeedbackControlsProps {
  sent: boolean
  onSubmit: (rating: FeedbackRating, comment?: string) => Promise<boolean>
}

export function FeedbackControls({ sent, onSubmit }: FeedbackControlsProps) {
  const [commentOpen, setCommentOpen] = useState(false)
  const [comment, setComment] = useState('')
  const [busy, setBusy] = useState(false)

  if (sent) return <span className="empty-note">Спасибо за отзыв!</span>

  const submit = async (rating: FeedbackRating, withComment?: string) => {
    setBusy(true)
    const ok = await onSubmit(rating, withComment || undefined)
    setBusy(false)
    if (ok) setCommentOpen(false)
  }

  return (
    <span className="feedback">
      <button
        type="button"
        aria-label="Полезный ответ"
        disabled={busy}
        onClick={() => void submit('up')}
      >
        👍
      </button>
      <button
        type="button"
        aria-label="Плохой ответ"
        disabled={busy}
        onClick={() => setCommentOpen((current) => !current)}
      >
        👎
      </button>
      {commentOpen && (
        <span className="feedback-form">
          <textarea
            rows={2}
            placeholder="Что не так с ответом? (необязательно)"
            value={comment}
            onChange={(event) => setComment(event.target.value)}
          />
          <button
            type="button"
            className="btn"
            disabled={busy}
            onClick={() => void submit('down', comment)}
          >
            Отправить
          </button>
        </span>
      )}
    </span>
  )
}
