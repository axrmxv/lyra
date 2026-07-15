import type { ChatStage } from '../api/types'

const STAGE_TEXT: Record<ChatStage, string> = {
  retrieving: 'Ищу источники…',
  grading: 'Проверяю достаточность контекста…',
  corrective_retrieve: 'Уточняю поиск…',
  generating: 'Отвечаю…',
  self_check: 'Проверяю ответ по источникам…',
}

export function StageIndicator({ stage }: { stage: ChatStage }) {
  return <span className="stage-indicator">{STAGE_TEXT[stage]}</span>
}
