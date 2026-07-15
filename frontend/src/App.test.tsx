import { render, screen } from '@testing-library/react'
import { expect, test } from 'vitest'
import { App } from './App'

test('без авторизации показывает страницу входа', () => {
  render(<App />)
  expect(screen.getByRole('heading', { name: 'LYRA' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Войти' })).toBeInTheDocument()
})
