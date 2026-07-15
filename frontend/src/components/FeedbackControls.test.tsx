import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { FeedbackControls } from './FeedbackControls'

describe('FeedbackControls', () => {
  it('👍 отправляет rating up без комментария', async () => {
    const user = userEvent.setup()
    const onSubmit = vi.fn().mockResolvedValue(true)
    render(<FeedbackControls sent={false} onSubmit={onSubmit} />)
    await user.click(screen.getByRole('button', { name: 'Полезный ответ' }))
    expect(onSubmit).toHaveBeenCalledWith('up', undefined)
  })

  it('👎 открывает форму комментария и отправляет down с текстом', async () => {
    const user = userEvent.setup()
    const onSubmit = vi.fn().mockResolvedValue(true)
    render(<FeedbackControls sent={false} onSubmit={onSubmit} />)
    await user.click(screen.getByRole('button', { name: 'Плохой ответ' }))
    await user.type(screen.getByPlaceholderText(/Что не так/), 'ответ про старую версию политики')
    await user.click(screen.getByRole('button', { name: 'Отправить' }))
    expect(onSubmit).toHaveBeenCalledWith('down', 'ответ про старую версию политики')
  })

  it('после отправки показывает благодарность', () => {
    render(<FeedbackControls sent onSubmit={vi.fn()} />)
    expect(screen.getByText('Спасибо за отзыв!')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Полезный ответ' })).not.toBeInTheDocument()
  })
})
