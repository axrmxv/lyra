import { useCallback, useEffect, useState } from 'react'

import { applyTheme, currentTheme, resolveTheme, saveMode, storedMode, systemTheme } from '../theme'
import type { Theme, ThemeMode } from '../theme'

const NEXT_MODE: Record<ThemeMode, ThemeMode> = {
  light: 'dark',
  dark: 'system',
  system: 'light',
}

export function useTheme(): { mode: ThemeMode; theme: Theme; cycle: () => void } {
  const [mode, setMode] = useState<ThemeMode>(() => storedMode())
  const [theme, setTheme] = useState<Theme>(() => currentTheme())

  // В режиме system следуем за сменой системной темы вживую
  useEffect(() => {
    const media = window.matchMedia?.('(prefers-color-scheme: dark)')
    if (!media) return
    const onChange = () => {
      if (storedMode() === 'system') {
        const next = systemTheme()
        applyTheme(next)
        setTheme(next)
      }
    }
    media.addEventListener('change', onChange)
    return () => media.removeEventListener('change', onChange)
  }, [])

  const cycle = useCallback(() => {
    setMode((prev) => {
      const next = NEXT_MODE[prev]
      saveMode(next)
      setTheme(resolveTheme(next))
      return next
    })
  }, [])

  return { mode, theme, cycle }
}
