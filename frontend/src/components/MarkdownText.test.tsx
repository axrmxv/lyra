import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { MarkdownText } from './MarkdownText'
import type { Citation } from '../api/types'

const citation = (id: number): Citation => ({
  id,
  chunk_id: `c${id}`,
  document_id: `d${id}`,
  document_title: `Документ ${id}`,
  url: 'https://example.com',
  quote: 'Цитата',
  relevance_score: 0.9,
})

describe('MarkdownText', () => {
  it('рендерит markdown-структуру: заголовок, список, таблицу, код', () => {
    const md = [
      '# Заголовок',
      '',
      '- пункт один',
      '- пункт два',
      '',
      '`inline` и **жирный**',
      '',
      '| A | B |',
      '| - | - |',
      '| 1 | 2 |',
    ].join('\n')
    const { container } = render(<MarkdownText content={md} citations={[]} />)

    expect(screen.getByRole('heading', { name: 'Заголовок' })).toBeInTheDocument()
    expect(screen.getAllByRole('listitem')).toHaveLength(2)
    expect(screen.getByRole('table')).toBeInTheDocument()
    expect(container.querySelector('code')).not.toBeNull()
    expect(container.querySelector('strong')?.textContent).toBe('жирный')
  })

  it('маркер [n] с citation превращается в кликабельную сноску', () => {
    render(<MarkdownText content="Ответ [1] здесь." citations={[citation(1)]} />)
    const chip = screen.getByRole('button', { name: /Источник 1: Документ 1/ })
    expect(chip).toBeInTheDocument()
    expect(chip.tagName).toBe('BUTTON')
  })

  it('маркер [n] без citation деградирует в текст и не падает', () => {
    const { container } = render(<MarkdownText content="Текст [7] без источника." citations={[]} />)
    expect(container.textContent).toContain('[7]')
    expect(screen.queryByRole('button')).toBeNull()
  })

  it('маркер [n] внутри кода не превращается в сноску', () => {
    render(<MarkdownText content="Индекс `arr[1]` в коде." citations={[citation(1)]} />)
    expect(screen.queryByRole('button', { name: /Источник 1/ })).toBeNull()
    expect(screen.getByText(/arr\[1\]/)).toBeInTheDocument()
  })

  it('сырой HTML не рендерится как разметка (защита от инъекций)', () => {
    const evil = 'До <img src=x onerror="alert(1)"> и <script>alert(2)</script> после.'
    const { container } = render(<MarkdownText content={evil} citations={[]} />)
    expect(container.querySelector('img')).toBeNull()
    expect(container.querySelector('script')).toBeNull()
  })
})
