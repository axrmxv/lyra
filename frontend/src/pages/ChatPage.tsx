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
  const { messages, loadingHistory, stream, finalById, send, stop } = useChat(sessionId, onApiError)
  const feedback = useFeedback(onApiError)
  const [draft, setDraft] = useState('')
  const scrollRef = useRef<HTMLDivElement | null>(null)
  const bottomRef = useRef<HTMLDivElement | null>(null)
  // Держим ленту у низа только если пользователь уже внизу — чтение выше
  // не перебивается автоскроллом во время стрима
  const [atBottom, setAtBottom] = useState(true)

  const streaming = stream.phase === 'streaming'

  const onScroll = () => {
    const el = scrollRef.current
    if (!el) return
    setAtBottom(el.scrollHeight - el.scrollTop - el.clientHeight < 80)
  }

  const scrollToBottom = () => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
    setAtBottom(true)
  }

  useEffect(() => {
    if (atBottom) bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, stream.text, stream.stage, atBottom])

  const runSend = async (content: string) => {
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
    setAtBottom(true)
    await send(targetId, content)
    // Заголовок сессии появляется после первого сообщения
    void refreshSessions()
  }

  const handleSend = async (event: FormEvent) => {
    event.preventDefault()
    const content = draft.trim()
    if (!content || streaming) return
    setDraft('')
    await runSend(content)
  }

  // Регенерация: повторно задаём последний вопрос пользователя новым ходом
  const lastAssistantId = [...messages].reverse().find((m) => m.role === 'assistant')?.id
  const lastUserContent = [...messages].reverse().find((m) => m.role === 'user')?.content

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

      <section className="relative flex min-w-0 flex-1 flex-col">
        <div ref={scrollRef} className="flex-1 overflow-y-auto" onScroll={onScroll}>
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
                onRegenerate={
                  message.id === lastAssistantId && !streaming && lastUserContent
                    ? () => void runSend(lastUserContent)
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

        {!atBottom && (
          <button
            type="button"
            aria-label="Вниз к последнему сообщению"
            onClick={scrollToBottom}
            className="border-line bg-surface text-ink hover:bg-canvas absolute bottom-24 left-1/2 -translate-x-1/2 rounded-full border px-3 py-1.5 shadow-md"
          >
            ↓
          </button>
        )}

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
            {streaming ? (
              <button type="button" className="btn" onClick={stop}>
                Стоп
              </button>
            ) : (
              <button type="submit" className="btn btn-primary" disabled={!draft.trim()}>
                Отправить
              </button>
            )}
          </form>
        </div>
      </section>
    </div>
  )
}
