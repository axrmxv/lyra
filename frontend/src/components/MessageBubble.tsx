// Сообщение чата: пользовательское или ответ ассистента с цитатами,
// confidence, refusal-состоянием и degraded-предупреждением.

import type { ChatMessageItem, FinalEvent } from '../api/types'
import { CitationText } from './CitationText'
import { ConfidenceBadge } from './ConfidenceBadge'
import { FeedbackControls } from './FeedbackControls'
import type { FeedbackRating } from '../api/types'

interface MessageBubbleProps {
  message: ChatMessageItem
  final?: FinalEvent
  feedbackSent?: boolean
  onFeedback?: (rating: FeedbackRating, comment?: string) => Promise<boolean>
}

export function MessageBubble({ message, final, feedbackSent, onFeedback }: MessageBubbleProps) {
  if (message.role === 'user') {
    return <div className="bubble bubble-user">{message.content}</div>
  }

  const refusal = message.refusal
  return (
    <div className={`bubble bubble-assistant ${refusal ? 'bubble-refusal' : ''}`}>
      {refusal && <strong>Ответ не найден в базе знаний</strong>}
      <div>
        <CitationText content={message.content} citations={message.citations} />
      </div>
      {refusal && final && final.nearest_documents.length > 0 && (
        <>
          <div>Возможно, будут полезны:</div>
          <ul className="nearest-docs">
            {final.nearest_documents.map((doc) => (
              <li key={doc.document_id}>
                {doc.url ? (
                  <a href={doc.url} target="_blank" rel="noopener noreferrer">
                    {doc.title || 'Без названия'}
                  </a>
                ) : (
                  doc.title || 'Без названия'
                )}
              </li>
            ))}
          </ul>
        </>
      )}
      <div className="bubble-meta">
        {message.confidence && <ConfidenceBadge confidence={message.confidence} />}
        {final?.degraded && (
          <span className="degraded-note">
            ⚠ Ранжирование работало в упрощённом режиме — качество может быть ниже
          </span>
        )}
        {onFeedback && <FeedbackControls sent={feedbackSent ?? false} onSubmit={onFeedback} />}
      </div>
    </div>
  )
}
