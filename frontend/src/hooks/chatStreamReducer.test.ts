import { describe, expect, it } from 'vitest'

import type { FinalEvent } from '../api/types'
import { chatStreamReducer, initialStreamState } from './chatStreamReducer'
import type { StreamState } from './chatStreamReducer'

const FINAL: FinalEvent = {
  message_id: 'm1',
  answer: 'Отпуск 28 дней [1].',
  refusal: false,
  citations: [],
  confidence: { label: 'high', score: 0.9 },
  degraded: false,
  trace_id: 'tr_1',
  usage: { llm_calls: 3, prompt_tokens: 100, completion_tokens: 20, took_ms: 900 },
  nearest_documents: [],
}

function run(actions: Parameters<typeof chatStreamReducer>[1][]): StreamState {
  return actions.reduce(chatStreamReducer, initialStreamState)
}

describe('chatStreamReducer', () => {
  it('start → статусы → токены → final', () => {
    const state = run([
      { type: 'start' },
      { type: 'status', data: { stage: 'retrieving' } },
      { type: 'status', data: { stage: 'grading' } },
      { type: 'status', data: { stage: 'generating' } },
      { type: 'token', data: { text: 'Отпуск ' } },
      { type: 'token', data: { text: '28 дней.' } },
      { type: 'status', data: { stage: 'self_check' } },
      { type: 'final', data: FINAL },
    ])
    expect(state.phase).toBe('done')
    expect(state.final?.message_id).toBe('m1')
    // final заменяет стриминговый черновик каноническим текстом
    expect(state.text).toBe(FINAL.answer)
  })

  it('накапливает токены и хранит текущую стадию', () => {
    const state = run([
      { type: 'start' },
      { type: 'status', data: { stage: 'generating' } },
      { type: 'token', data: { text: 'А' } },
      { type: 'token', data: { text: 'Б' } },
    ])
    expect(state.phase).toBe('streaming')
    expect(state.stage).toBe('generating')
    expect(state.text).toBe('АБ')
  })

  it('повторный generating (регенерация) сбрасывает черновик', () => {
    const state = run([
      { type: 'start' },
      { type: 'status', data: { stage: 'generating' } },
      { type: 'token', data: { text: 'плохой ответ' } },
      { type: 'status', data: { stage: 'self_check' } },
      { type: 'status', data: { stage: 'generating' } },
      { type: 'token', data: { text: 'хороший' } },
    ])
    expect(state.text).toBe('хороший')
  })

  it('error завершает поток с ошибкой без final', () => {
    const state = run([
      { type: 'start' },
      { type: 'status', data: { stage: 'retrieving' } },
      { type: 'error', data: { code: 'llm_unavailable', message: 'LLM недоступна' } },
    ])
    expect(state.phase).toBe('error')
    expect(state.error?.code).toBe('llm_unavailable')
    expect(state.final).toBeNull()
  })

  it('reset возвращает исходное состояние', () => {
    const state = run([
      { type: 'start' },
      { type: 'token', data: { text: 'x' } },
      { type: 'reset' },
    ])
    expect(state).toEqual(initialStreamState)
  })
})
