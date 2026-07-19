import { NavLink, Outlet } from 'react-router-dom'

import { useAuth } from '../hooks/useAuth'
import { useTheme } from '../hooks/useTheme'
import { Toasts } from './Toasts'

const ROLE_LABEL: Record<string, string> = {
  viewer: 'наблюдатель',
  editor: 'редактор',
  admin: 'администратор',
}

const navClass = ({ isActive }: { isActive: boolean }) =>
  isActive
    ? 'bg-accent-soft text-accent rounded-lg px-3 py-1.5 text-sm font-semibold'
    : 'text-ink-muted hover:bg-canvas hover:text-ink rounded-lg px-3 py-1.5 text-sm'

export function Layout() {
  const { user, logout } = useAuth()
  const { theme, toggle } = useTheme()
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
            aria-label={theme === 'dark' ? 'Светлая тема' : 'Тёмная тема'}
            title={theme === 'dark' ? 'Светлая тема' : 'Тёмная тема'}
            onClick={toggle}
          >
            {theme === 'dark' ? '☀' : '☾'}
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
