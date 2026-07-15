import type { Confidence } from '../api/types'

const LABELS: Record<Confidence['label'], string> = {
  high: 'высокая',
  medium: 'средняя',
  low: 'низкая',
}

export function ConfidenceBadge({ confidence }: { confidence: Confidence }) {
  return (
    <span className={`badge badge-${confidence.label}`}>
      Уверенность: {LABELS[confidence.label]} ({confidence.score.toFixed(2)})
    </span>
  )
}
