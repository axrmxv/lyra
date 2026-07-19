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

const sessionClass = (active: boolean) =>
  active
    ? 'bg-accent-soft text-accent truncate rounded-lg px-3 py-2 text-left text-sm font-medium'
    : 'text-ink hover:bg-canvas truncate rounded-lg px-3 py-2 text-left text-sm'

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
    <div className="flex min-h-0 flex-1">
      <aside className="border-line bg-surface flex w-64 shrink-0 flex-col gap-1.5 overflow-y-auto p-3">
        <button type="button" className="btn btn-primary w-full" onClick={() => setSessionId(null)}>
          + Новый диалог
        </button>
        {sessionsLoading && <span className="empty-note">Загрузка…</span>}
        {sessions.map((session) => (
          <button
            key={session.id}
            type="button"
            className={sessionClass(session.id === sessionId)}
            onClick={() => setSessionId(session.id)}
            title={session.title ?? 'Без названия'}
          >
            {session.title ?? 'Без названия'}
          </button>
        ))}
      </aside>

      <section className="flex min-w-0 flex-1 flex-col">
        <div className="flex-1 overflow-y-auto">
          <div className="mx-auto flex w-full max-w-3xl flex-col gap-6 px-4 py-6">
            {loadingHistory && <span className="empty-note">Загружаю историю…</span>}
            {!loadingHistory && messages.length === 0 && !streaming && (
              <p className="text-ink-muted mx-auto mt-16 max-w-md text-center">
                Задайте вопрос по базе знаний — ответ придёт со ссылками на источники.
              </p>
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
            <div ref={bottomRef} />
          </div>
        </div>

        <div className="border-line bg-surface border-t">
          <form
            className="mx-auto flex w-full max-w-3xl items-end gap-2 px-4 py-3"
            onSubmit={(event) => void handleSend(event)}
          >
            <textarea
              rows={1}
              className="border-line bg-surface focus:border-accent max-h-40 min-h-[2.75rem] flex-1 resize-none rounded-xl border px-3.5 py-2.5 focus:outline-none"
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
        </div>
      </section>
    </div>
  )
}
