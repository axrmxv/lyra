import { useCallback, useEffect, useState } from 'react'

import { applyTheme, currentTheme, saveTheme, storedTheme, systemTheme } from '../theme'
import type { Theme } from '../theme'

export function useTheme(): { theme: Theme; toggle: () => void } {
  const [theme, setTheme] = useState<Theme>(() => currentTheme())

  // Пока пользователь не выбрал тему явно — следуем за системной
  useEffect(() => {
    const media = window.matchMedia?.('(prefers-color-scheme: dark)')
    if (!media) return
    const onChange = () => {
      if (storedTheme() === null) {
        const next = systemTheme()
        applyTheme(next)
        setTheme(next)
      }
    }
    media.addEventListener('change', onChange)
    return () => media.removeEventListener('change', onChange)
  }, [])

  const toggle = useCallback(() => {
    setTheme((prev) => {
      const next: Theme = prev === 'dark' ? 'light' : 'dark'
      saveTheme(next)
      return next
    })
  }, [])

  return { theme, toggle }
}
