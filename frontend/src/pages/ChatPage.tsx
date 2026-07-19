// Главный экран: список сессий, поток сообщений, SSE-стриминг ответа.

import { useCallback, useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'

import { MessageBubble } from '../components/MessageBubble'
import { StageIndicator } from '../components/StageIndicator'
import { CitationText } from '../components/CitationText'
import { useChat } from '../hooks/useChat'
import { useFeedback } from '../hooks/useFeedback'
import { useSessions } from '../hooks/useSessions'
import { useToasts } from '../hooks/useToasts'

export function ChatPage() {
  const { pushToast } = useToasts()
  const onApiError = useCallback((message: string) => pushToast(message), [pushToast])

  const { sessions, loading: sessionsLoading, refresh: refreshSessions, createNew } = useSessions()
  const [sessionId, setSessionId] = useState<string | null>(null)
  const { messages, loadingHistory, stream, finalById, send } = useChat(sessionId, onApiError)
  const feedback = useFeedback(onApiError)
  const [draft, setDraft] = useState('')
  const bottomRef = useRef<HTMLDivElement | null>(null)

  const streaming = stream.phase === 'streaming'

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, stream.text, stream.stage])

  const handleSend = async (event: FormEvent) => {
    event.preventDefault()
    const content = draft.trim()
    if (!content || streaming) return
    setDraft('')
    let targetId = sessionId
    if (!targetId) {
      try {
        targetId = await createNew()
        setSessionId(targetId)
      } catch {
        pushToast('Не удалось создать сессию')
        return
      }
    }
    await send(targetId, content)
    // Заголовок сессии появляется после первого сообщения
    void refreshSessions()
  }

  return (
    <div className="chat-page">
      <aside className="chat-sidebar">
        <button type="button" className="btn btn-primary" onClick={() => setSessionId(null)}>
          + Новый диалог
        </button>
        {sessionsLoading && <span className="empty-note">Загрузка…</span>}
        {sessions.map((session) => (
          <button
            key={session.id}
            type="button"
            className={`chat-session-item ${session.id === sessionId ? 'active' : ''}`}
            onClick={() => setSessionId(session.id)}
            title={session.title ?? 'Без названия'}
          >
            {session.title ?? 'Без названия'}
          </button>
        ))}
      </aside>
      <section className="chat-main">
        <div className="chat-messages">
          {loadingHistory && <span className="empty-note">Загружаю историю…</span>}
          {!loadingHistory && messages.length === 0 && !streaming && (
            <span className="empty-note">
              Задайте вопрос по базе знаний — ответ придёт со ссылками на источники.
            </span>
          )}
          {messages.map((message) => (
            <MessageBubble
              key={message.id}
              message={message}
              final={finalById[message.id]}
              feedbackSent={feedback.sentFor.has(message.id)}
              onFeedback={
                message.role === 'assistant' && !message.id.startsWith('local-')
                  ? (rating, comment) => feedback.submit(message.id, rating, comment)
                  : undefined
              }
            />
          ))}
          {streaming && (
            <div className="bubble bubble-assistant">
              {stream.text ? <CitationText content={stream.text} citations={[]} /> : null}
              {stream.stage && (
                <div className="bubble-meta">
                  <StageIndicator stage={stream.stage} />
                </div>
              )}
            </div>
          )}
        </div>
        <form className="chat-input" onSubmit={(event) => void handleSend(event)}>
          <textarea
            rows={1}
            placeholder="Вопрос к базе знаний…"
            value={draft}
            disabled={streaming}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault()
                event.currentTarget.form?.requestSubmit()
              }
            }}
          />
          <button type="submit" className="btn btn-primary" disabled={streaming || !draft.trim()}>
            {streaming ? 'Отвечаю…' : 'Отправить'}
          </button>
        </form>
      </section>
    </div>
  )
}
