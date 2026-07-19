// Финальный ответ ассистента: markdown → React-узлы (injection-safe,
// без dangerouslySetInnerHTML — react-markdown не рендерит сырой HTML).
// Маркеры [n] превращаются в сноски-цитаты через rehype-плагин; маркер без
// citation деградирует в обычный текст [n] (.claude/rules/frontend.md).

import type { ReactNode } from 'react'
import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { Components } from 'react-markdown'
import type { Plugin } from 'unified'

import type { Citation } from '../api/types'
import { CitationChip } from './CitationChip'

const MARKER_RE = /\[(\d+)\]/g

// Минимальные типы hast-узлов, которых касается плагин.
interface HastText {
  type: 'text'
  value: string
}
interface HastElement {
  type: 'element'
  tagName: string
  properties?: Record<string, unknown>
  children: HastChild[]
}
type HastChild = HastText | HastElement | { type: string; children?: HastChild[] }
interface HastRoot {
  type: 'root'
  children: HastChild[]
}

function isText(node: HastChild): node is HastText {
  return node.type === 'text' && typeof (node as HastText).value === 'string'
}

function isParent(node: HastChild): node is HastElement {
  return node.type === 'element' && Array.isArray((node as HastElement).children)
}

// Разбивает текст на text + <lyra-cite id="n"> по маркерам [n].
function splitCitations(value: string): HastChild[] {
  const out: HastChild[] = []
  let cursor = 0
  for (const match of value.matchAll(MARKER_RE)) {
    const start = match.index ?? 0
    if (start > cursor) out.push({ type: 'text', value: value.slice(cursor, start) })
    out.push({
      type: 'element',
      tagName: 'lyra-cite',
      properties: { id: match[1] },
      children: [{ type: 'text', value: match[0] }],
    })
    cursor = start + match[0].length
  }
  if (out.length === 0) return [{ type: 'text', value }]
  if (cursor < value.length) out.push({ type: 'text', value: value.slice(cursor) })
  return out
}

// rehype-плагин: заменяет маркеры [n] на элементы lyra-cite, кроме кода.
const rehypeCitations: Plugin<[], HastRoot> = () => {
  const transform = (node: HastElement | HastRoot, insideCode: boolean): void => {
    const next: HastChild[] = []
    for (const child of node.children) {
      if (isText(child) && !insideCode) {
        next.push(...splitCitations(child.value))
      } else {
        if (isParent(child)) {
          transform(child, insideCode || child.tagName === 'code' || child.tagName === 'pre')
        }
        next.push(child)
      }
    }
    node.children = next
  }
  return (tree) => transform(tree, false)
}

function buildComponents(citations: Citation[]): Components {
  const byId = new Map(citations.map((citation) => [citation.id, citation]))
  return {
    // Кастомный узел сноски: ищем citation по id, иначе — текст [n]
    'lyra-cite': ({ node, children }: { node?: HastElement; children?: ReactNode }) => {
      const raw = node?.properties?.id
      const citation = byId.get(Number(raw))
      return citation ? <CitationChip citation={citation} /> : <>{children}</>
    },
    // Внешние ссылки из ответа — безопасно в новой вкладке
    a: ({ href, children }: { href?: string; children?: ReactNode }) => (
      <a href={href} target="_blank" rel="noopener noreferrer">
        {children}
      </a>
    ),
  } as Components
}

export function MarkdownText({ content, citations }: { content: string; citations: Citation[] }) {
  return (
    <div className="markdown">
      <Markdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeCitations]}
        components={buildComponents(citations)}
      >
        {content}
      </Markdown>
    </div>
  )
}
