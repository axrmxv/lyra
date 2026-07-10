import { render, screen } from '@testing-library/react'
import { expect, test } from 'vitest'
import { App } from './App'

test('рендерит заглавную страницу LYRA', () => {
  render(<App />)
  expect(screen.getByRole('heading', { name: 'LYRA' })).toBeInTheDocument()
  expect(screen.getByText('Гармония знаний')).toBeInTheDocument()
})
