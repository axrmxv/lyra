// Редьюсер SSE-потока чата (правило .claude/rules/frontend.md):
// все события status/token/final/error проходят через него, не ad-hoc в компоненте.

import type { ChatStreamEvent } from '../api/client'
import type { ChatStage, ErrorEvent, FinalEvent } from '../api/types'

export interface StreamState {
  phase: 'idle' | 'streaming' | 'done' | 'error'
  stage: ChatStage | null
  text: string
  final: FinalEvent | null
  error: ErrorEvent | null
}

export const initialStreamState: StreamState = {
  phase: 'idle',
  stage: null,
  text: '',
  final: null,
  error: null,
}

export type StreamAction = ChatStreamEvent | { type: 'start' } | { type: 'reset' }

export function chatStreamReducer(state: StreamState, action: StreamAction): StreamState {
  switch (action.type) {
    case 'start':
      return { ...initialStreamState, phase: 'streaming' }
    case 'reset':
      return initialStreamState
    case 'status':
      // Повторный generating = регенерация после self_check — стираем черновик
      return {
        ...state,
        stage: action.data.stage,
        text: action.data.stage === 'generating' ? '' : state.text,
      }
    case 'token':
      return { ...state, text: state.text + action.data.text }
    case 'final':
      // Ответ сервера — канонический текст (заменяет стриминговый черновик)
      return { ...state, phase: 'done', stage: null, text: action.data.answer, final: action.data }
    case 'error':
      return { ...state, phase: 'error', stage: null, error: action.data }
  }
}
