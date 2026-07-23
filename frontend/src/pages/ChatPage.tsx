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

function ArrowUpIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      width="18"
      height="18"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M12 20V5" />
      <path d="M6 11l6-6 6 6" />
    </svg>
  )
}

function StopIcon() {
  return (
    <svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true">
      <rect x="6" y="6" width="12" height="12" rx="2" fill="currentColor" />
    </svg>
  )
}

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
  // Новый пустой чат: инпут по центру
  const isEmpty = !loadingHistory && messages.length === 0 && !streaming

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

  const inputBox = (
    <form onSubmit={(event) => void handleSend(event)} className="mx-auto w-full max-w-3xl px-4">
      <div className="border-line bg-surface focus-within:border-accent flex items-end gap-2 rounded-3xl border py-2 pr-2 pl-4 shadow-sm transition-colors">
        <textarea
          rows={1}
          className="text-ink placeholder:text-ink-muted max-h-40 min-h-[1.5rem] flex-1 resize-none bg-transparent py-1.5 focus:outline-none"
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
          <button
            type="button"
            aria-label="Остановить генерацию"
            title="Остановить"
            onClick={stop}
            className="bg-ink text-surface grid h-8 w-8 shrink-0 place-items-center rounded-full"
          >
            <StopIcon />
          </button>
        ) : (
          <button
            type="submit"
            aria-label="Отправить"
            title="Отправить"
            disabled={!draft.trim()}
            className="bg-ink text-surface grid h-8 w-8 shrink-0 place-items-center rounded-full transition-opacity disabled:opacity-30"
          >
            <ArrowUpIcon />
          </button>
        )}
      </div>
    </form>
  )

  return (
    <div className="flex min-h-0 flex-1">
      <aside className="border-line bg-surface flex w-64 shrink-0 flex-col gap-1.5 overflow-y-auto border-r p-3">
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
        {isEmpty ? (
          <div className="flex flex-1 flex-col items-center justify-center px-4">
            <h2 className="text-ink mb-6 text-center text-2xl font-semibold">Чем могу помочь?</h2>
            {inputBox}
            <p className="text-ink-muted mt-3 text-center text-sm">
              Ответ придёт со ссылками на источники.
            </p>
          </div>
        ) : (
          <>
            <div ref={scrollRef} className="flex-1 overflow-y-auto" onScroll={onScroll}>
              <div className="mx-auto flex w-full max-w-3xl flex-col gap-6 px-4 py-6">
                {loadingHistory && <span className="empty-note">Загружаю историю…</span>}
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

            <div className="pt-2 pb-4">{inputBox}</div>
          </>
        )}
      </section>
    </div>
  )
}
