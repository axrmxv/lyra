// Рендер потокового текста (стриминг): маркеры [n] → сноски-чипы.
// Маркер без citation рендерится как обычный текст (последняя линия защиты,
// .claude/rules/frontend.md); текст — только как текст, никакого HTML.
// Финальный ответ форматируется через MarkdownText.

import type { Citation } from '../api/types'
import { CitationChip } from './CitationChip'

const MARKER_RE = /\[(\d+)\]/g

interface Segment {
  key: string
  text?: string
  citation?: Citation
}

function splitByMarkers(content: string, citations: Citation[]): Segment[] {
  const byId = new Map(citations.map((citation) => [citation.id, citation]))
  const segments: Segment[] = []
  let cursor = 0
  let index = 0
  for (const match of content.matchAll(MARKER_RE)) {
    const markerStart = match.index ?? 0
    const markerText = match[0]
    const citation = byId.get(Number(match[1]))
    if (markerStart > cursor) {
      segments.push({ key: `t${index++}`, text: content.slice(cursor, markerStart) })
    }
    if (citation) {
      segments.push({ key: `c${index++}`, citation })
    } else {
      segments.push({ key: `t${index++}`, text: markerText })
    }
    cursor = markerStart + markerText.length
  }
  if (cursor < content.length) {
    segments.push({ key: `t${index++}`, text: content.slice(cursor) })
  }
  return segments
}

export function CitationText({ content, citations }: { content: string; citations: Citation[] }) {
  const segments = splitByMarkers(content, citations)
  return (
    <>
      {segments.map((segment) =>
        segment.citation ? (
          <CitationChip key={segment.key} citation={segment.citation} />
        ) : (
          <span key={segment.key}>{segment.text}</span>
        ),
      )}
    </>
  )
}
