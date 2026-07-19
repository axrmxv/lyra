// Сноска-цитата [n]: чип + popover с источником. Используется и в
// CitationText (стриминг), и в MarkdownText (финальный ответ).

import { useState } from 'react'

import type { Citation } from '../api/types'

export function CitationChip({ citation }: { citation: Citation }) {
  const [open, setOpen] = useState(false)
  return (
    <span className="citation-anchor">
      <button
        type="button"
        className="citation-chip"
        aria-expanded={open}
        aria-label={`Источник ${citation.id}: ${citation.document_title}`}
        onClick={() => setOpen((current) => !current)}
        onBlur={() => setOpen(false)}
      >
        {citation.id}
      </button>
      {open && (
        <span className="citation-popover" role="tooltip">
          <strong>{citation.document_title || 'Без названия'}</strong>
          <blockquote>{citation.quote}</blockquote>
          <span>Релевантность: {citation.relevance_score.toFixed(2)}</span>
          {citation.url && (
            <>
              {' · '}
              {/* onMouseDown раньше onBlur — переход по ссылке не съедается закрытием */}
              <a
                href={citation.url}
                target="_blank"
                rel="noopener noreferrer"
                onMouseDown={(event) => event.stopPropagation()}
              >
                Открыть источник
              </a>
            </>
          )}
        </span>
      )}
    </span>
  )
}
