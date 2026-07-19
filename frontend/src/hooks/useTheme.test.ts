import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { initTheme } from '../theme'
import { useTheme } from './useTheme'

describe('useTheme', () => {
  beforeEach(() => {
    localStorage.clear()
    delete document.documentElement.dataset.theme
  })

  afterEach(() => {
    localStorage.clear()
    delete document.documentElement.dataset.theme
  })

  it('по умолчанию светлая тема (jsdom без matchMedia)', () => {
    initTheme()
    const { result } = renderHook(() => useTheme())
    expect(result.current.theme).toBe('light')
    expect(document.documentElement.dataset.theme).toBe('light')
  })

  it('toggle переключает тему, ставит data-theme и сохраняет выбор', () => {
    initTheme()
    const { result } = renderHook(() => useTheme())

    act(() => result.current.toggle())
    expect(result.current.theme).toBe('dark')
    expect(document.documentElement.dataset.theme).toBe('dark')
    expect(localStorage.getItem('lyra-theme')).toBe('dark')

    act(() => result.current.toggle())
    expect(result.current.theme).toBe('light')
    expect(document.documentElement.dataset.theme).toBe('light')
    expect(localStorage.getItem('lyra-theme')).toBe('light')
  })

  it('initTheme уважает сохранённый выбор', () => {
    localStorage.setItem('lyra-theme', 'dark')
    initTheme()
    const { result } = renderHook(() => useTheme())
    expect(result.current.theme).toBe('dark')
    expect(document.documentElement.dataset.theme).toBe('dark')
  })

  it('initTheme игнорирует мусор в localStorage', () => {
    localStorage.setItem('lyra-theme', 'neon')
    initTheme()
    expect(document.documentElement.dataset.theme).toBe('light')
  })
})
