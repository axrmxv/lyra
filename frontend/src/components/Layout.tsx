import { NavLink, Outlet } from 'react-router-dom'

import { useAuth } from '../hooks/useAuth'
import { Toasts } from './Toasts'

const ROLE_LABEL: Record<string, string> = {
  viewer: 'наблюдатель',
  editor: 'редактор',
  admin: 'администратор',
}

export function Layout() {
  const { user, logout } = useAuth()
  return (
    <div className="layout">
      <header className="topbar">
        <span className="topbar-brand">LYRA</span>
        <nav>
          <NavLink to="/chat">Чат</NavLink>
          <NavLink to="/documents">Документы</NavLink>
          <NavLink to="/sources">Источники</NavLink>
        </nav>
        <span className="topbar-user">
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
      <main className="layout-main">
        <Outlet />
      </main>
      <Toasts />
    </div>
  )
}
