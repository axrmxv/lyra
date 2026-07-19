// Управление темой: data-theme на <html>, выбор пользователя — в localStorage
// (хранить там JWT запрещено, предпочтение темы — не секрет). Без явного
// выбора действует системная тема (prefers-color-scheme).

export type Theme = 'light' | 'dark'

const STORAGE_KEY = 'lyra-theme'

function isTheme(value: unknown): value is Theme {
  return value === 'light' || value === 'dark'
}

export function storedTheme(): Theme | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return isTheme(raw) ? raw : null
  } catch {
    return null
  }
}

export function systemTheme(): Theme {
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

export function applyTheme(theme: Theme): void {
  document.documentElement.dataset.theme = theme
}

export function currentTheme(): Theme {
  return document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light'
}

/** Вызывается до первого рендера (main.tsx), чтобы избежать вспышки темы. */
export function initTheme(): void {
  applyTheme(storedTheme() ?? systemTheme())
}

export function saveTheme(theme: Theme): void {
  try {
    localStorage.setItem(STORAGE_KEY, theme)
  } catch {
    // Приватный режим: тема просто не переживёт перезагрузку
  }
  applyTheme(theme)
}
