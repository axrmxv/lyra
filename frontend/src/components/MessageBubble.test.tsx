import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { ChatMessageItem, FinalEvent } from '../api/types'
import { MessageBubble } from './MessageBubble'

const REFUSAL_MESSAGE: ChatMessageItem = {
  id: 'm1',
  role: 'assistant',
  content: 'В базе знаний нет информации по этому вопросу.',
  confidence: { label: 'low', score: 0.1 },
  refusal: true,
  created_at: '2026-07-15T10:00:00Z',
  citations: [],
}

const REFUSAL_FINAL: FinalEvent = {
  message_id: 'm1',
  answer: REFUSAL_MESSAGE.content,
  refusal: true,
  citations: [],
  confidence: { label: 'low', score: 0.1 },
  degraded: false,
  trace_id: 'tr_1',
  usage: { llm_calls: 2, prompt_tokens: 50, completion_tokens: 10, took_ms: 500 },
  nearest_documents: [
    { document_id: 'd1', title: 'Политика отпусков', url: 'https://kb/vacation' },
  ],
}

describe('MessageBubble', () => {
  it('refusal — отдельное состояние с ближайшими документами', () => {
    render(<MessageBubble message={REFUSAL_MESSAGE} final={REFUSAL_FINAL} />)
    expect(screen.getByText('Ответ не найден в базе знаний')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Политика отпусков' })).toBeInTheDocument()
    expect(screen.getByText(/Уверенность: низкая/)).toBeInTheDocument()
  })

  it('обычный ответ показывает confidence-бейдж без refusal-блока', () => {
    const message: ChatMessageItem = {
      ...REFUSAL_MESSAGE,
      refusal: false,
      content: 'Отпуск 28 дней [1].',
      confidence: { label: 'high', score: 0.87 },
    }
    render(<MessageBubble message={message} />)
    expect(screen.queryByText('Ответ не найден в базе знаний')).not.toBeInTheDocument()
    expect(screen.getByText(/Уверенность: высокая \(0.87\)/)).toBeInTheDocument()
  })

  it('degraded показывает предупреждение', () => {
    const message: ChatMessageItem = { ...REFUSAL_MESSAGE, refusal: false }
    render(
      <MessageBubble
        message={message}
        final={{ ...REFUSAL_FINAL, refusal: false, degraded: true }}
      />,
    )
    expect(screen.getByText(/упрощённом режиме/)).toBeInTheDocument()
  })
})
