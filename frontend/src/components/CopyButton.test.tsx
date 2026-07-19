import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { CopyButton } from './CopyButton'

describe('CopyButton', () => {
  it('копирует текст в буфер и показывает подтверждение', async () => {
    const writeText = vi.fn(async () => undefined)
    // navigator.clipboard в jsdom отсутствует — подставляем мок
    Object.assign(navigator, { clipboard: { writeText } })

    render(<CopyButton text="Текст ответа [1]." />)
    const button = screen.getByRole('button', { name: 'Копировать' })
    await userEvent.click(button)

    expect(writeText).toHaveBeenCalledWith('Текст ответа [1].')
    await waitFor(() => expect(screen.getByText('✓ Скопировано')).toBeInTheDocument())
  })
})
