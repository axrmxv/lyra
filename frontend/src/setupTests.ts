import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

// Авто-cleanup RTL не срабатывает без test.globals — чистим DOM явно
afterEach(() => {
  cleanup()
})
