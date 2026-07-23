import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { initTheme } from '../theme'
import { useTheme } from './useTheme'

const KEY = 'lyra-theme'

describe('useTheme', () => {
  beforeEach(() => {
    localStorage.clear()
    delete document.documentElement.dataset.theme
  })

  afterEach(() => {
    localStorage.clear()
    delete document.documentElement.dataset.theme
  })

  it('по умолчанию режим system, тема светлая (jsdom без matchMedia)', () => {
    initTheme()
    const { result } = renderHook(() => useTheme())
    expect(result.current.mode).toBe('system')
    expect(result.current.theme).toBe('light')
    expect(document.documentElement.dataset.theme).toBe('light')
  })

  it('cycle идёт light → dark → system и возвращается к light', () => {
    initTheme()
    const { result } = renderHook(() => useTheme())

    act(() => result.current.cycle())
    expect(result.current.mode).toBe('light')
    expect(result.current.theme).toBe('light')
    expect(localStorage.getItem(KEY)).toBe('light')

    act(() => result.current.cycle())
    expect(result.current.mode).toBe('dark')
    expect(document.documentElement.dataset.theme).toBe('dark')
    expect(localStorage.getItem(KEY)).toBe('dark')

    act(() => result.current.cycle())
    expect(result.current.mode).toBe('system')
    // system = отсутствие ключа, снова следуем за ОС
    expect(localStorage.getItem(KEY)).toBeNull()
    expect(document.documentElement.dataset.theme).toBe('light')

    act(() => result.current.cycle())
    expect(result.current.mode).toBe('light')
  })

  it('initTheme уважает сохранённый явный режим', () => {
    localStorage.setItem(KEY, 'dark')
    initTheme()
    const { result } = renderHook(() => useTheme())
    expect(result.current.mode).toBe('dark')
    expect(document.documentElement.dataset.theme).toBe('dark')
  })

  it('initTheme трактует мусор в localStorage как system', () => {
    localStorage.setItem(KEY, 'neon')
    initTheme()
    const { result } = renderHook(() => useTheme())
    expect(result.current.mode).toBe('system')
    expect(document.documentElement.dataset.theme).toBe('light')
  })
})
