// Управление темой: data-theme на <html>. Режим (выбор пользователя) — в
// localStorage; хранить там JWT запрещено, предпочтение темы — не секрет.
// 'system' = следовать prefers-color-scheme; хранится как отсутствие ключа.

// Применённая тема (то, что стоит в data-theme)
export type Theme = 'light' | 'dark'
// Выбор пользователя: явная тема или «как в системе»
export type ThemeMode = 'light' | 'dark' | 'system'

const STORAGE_KEY = 'lyra-theme'

function isExplicit(value: unknown): value is 'light' | 'dark' {
  return value === 'light' || value === 'dark'
}

/** Сохранённый режим: явный выбор из localStorage, иначе — system. */
export function storedMode(): ThemeMode {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return isExplicit(raw) ? raw : 'system'
  } catch {
    return 'system'
  }
}

export function systemTheme(): Theme {
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

/** Режим → конкретная тема (system резолвится по prefers-color-scheme). */
export function resolveTheme(mode: ThemeMode): Theme {
  return mode === 'system' ? systemTheme() : mode
}

export function applyTheme(theme: Theme): void {
  document.documentElement.dataset.theme = theme
}

export function currentTheme(): Theme {
  return document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light'
}

/** Вызывается до первого рендера (main.tsx), чтобы избежать вспышки темы. */
export function initTheme(): void {
  applyTheme(resolveTheme(storedMode()))
}

/** Сохраняет режим и применяет тему. system = удаление ключа (снова следуем ОС). */
export function saveMode(mode: ThemeMode): void {
  try {
    if (mode === 'system') {
      localStorage.removeItem(STORAGE_KEY)
    } else {
      localStorage.setItem(STORAGE_KEY, mode)
    }
  } catch {
    // Приватный режим: выбор просто не переживёт перезагрузку
  }
  applyTheme(resolveTheme(mode))
}
