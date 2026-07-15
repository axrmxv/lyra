import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import type { Citation } from '../api/types'
import { CitationText } from './CitationText'

const CITATION: Citation = {
  id: 1,
  chunk_id: 'chunk-1',
  document_id: 'doc-1',
  document_title: 'Политика отпусков',
  url: 'https://kb/vacation',
  quote: 'Сотрудникам предоставляется 28 дней отпуска.',
  relevance_score: 0.93,
}

describe('CitationText', () => {
  it('рендерит маркер [n] сноской-чипом', () => {
    render(<CitationText content="Отпуск 28 дней [1]." citations={[CITATION]} />)
    expect(screen.getByRole('button', { name: /Источник 1/ })).toBeInTheDocument()
    expect(screen.getByText('Отпуск 28 дней', { exact: false })).toBeInTheDocument()
  })

  it('маркер без citation не падает и рендерится текстом', () => {
    render(<CitationText content="Ответ с битым маркером [7]." citations={[CITATION]} />)
    expect(screen.queryByRole('button', { name: /Источник 7/ })).not.toBeInTheDocument()
    expect(screen.getByText('[7]', { exact: false })).toBeInTheDocument()
  })

  it('клик по чипу открывает popover с цитатой и ссылкой', async () => {
    const user = userEvent.setup()
    render(<CitationText content="Отпуск 28 дней [1]." citations={[CITATION]} />)
    await user.click(screen.getByRole('button', { name: /Источник 1/ }))
    expect(screen.getByText('Политика отпусков')).toBeInTheDocument()
    expect(screen.getByText(CITATION.quote)).toBeInTheDocument()
    const link = screen.getByRole('link', { name: 'Открыть источник' })
    expect(link).toHaveAttribute('href', CITATION.url)
    expect(link).toHaveAttribute('rel', 'noopener noreferrer')
  })
})
