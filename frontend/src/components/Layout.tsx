import { NavLink, Outlet } from 'react-router-dom'

import { useAuth } from '../hooks/useAuth'
import { useTheme } from '../hooks/useTheme'
import type { ThemeMode } from '../theme'
import { Toasts } from './Toasts'

const ROLE_LABEL: Record<string, string> = {
  viewer: 'наблюдатель',
  editor: 'редактор',
  admin: 'администратор',
}

// Иконка и подпись по режиму; клик циклит light → dark → system
const THEME_META: Record<ThemeMode, { icon: string; label: string }> = {
  light: { icon: '☀', label: 'Тема: светлая' },
  dark: { icon: '☾', label: 'Тема: тёмная' },
  system: { icon: '◐', label: 'Тема: системная' },
}

const navClass = ({ isActive }: { isActive: boolean }) =>
  isActive
    ? 'bg-accent-soft text-accent rounded-lg px-3 py-1.5 text-sm font-semibold'
    : 'text-ink-muted hover:bg-canvas hover:text-ink rounded-lg px-3 py-1.5 text-sm'

export function Layout() {
  const { user, logout } = useAuth()
  const { mode, cycle } = useTheme()
  const themeMeta = THEME_META[mode]
  return (
    <div className="flex h-dvh flex-col">
      <header className="border-line bg-surface flex items-center gap-6 border-b px-5 py-2.5">
        <span className="text-sm font-bold tracking-[0.18em]">LYRA</span>
        <nav className="flex gap-1">
          <NavLink to="/chat" className={navClass}>
            Чат
          </NavLink>
          <NavLink to="/documents" className={navClass}>
            Документы
          </NavLink>
          <NavLink to="/sources" className={navClass}>
            Источники
          </NavLink>
        </nav>
        <span className="text-ink-muted ml-auto flex items-center gap-3 text-sm">
          <button
            type="button"
            className="btn btn-icon"
            aria-label={`${themeMeta.label}. Переключить тему.`}
            title={themeMeta.label}
            onClick={cycle}
          >
            {themeMeta.icon}
          </button>
          {user && (
            <>
              <span>
                {user.email} · {ROLE_LABEL[user.role] ?? user.role}
              </span>
              <button type="button" className="btn" onClick={logout}>
                Выйти
              </button>
            </>
          )}
        </span>
      </header>
      <main className="flex min-h-0 flex-1">
        <Outlet />
      </main>
      <Toasts />
    </div>
  )
}
