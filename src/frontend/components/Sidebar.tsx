import { NavLink } from 'react-router'
import { useState } from 'react'
import { NAV_ITEMS } from '@shared/types'
import { fetchWithAuth } from '../utils/fetchWithAuth'

function useThemeToggle() {
  const [light, setLight] = useState(() => document.documentElement.getAttribute('data-theme') === 'light')
  const toggle = () => {
    const next = !light
    setLight(next)
    document.documentElement.setAttribute('data-theme', next ? 'light' : 'dark')
    localStorage.setItem('elfin-theme', next ? 'light' : 'dark')
  }
  return { light, toggle }
}

export function Sidebar() {
  const { light, toggle } = useThemeToggle()

  const handleLogout = async () => {
    try {
      await fetchWithAuth('/api/auth/logout', { method: 'POST' })
    } finally {
      localStorage.removeItem('token')
      window.location.href = '/'
    }
  }

  return (
    <aside className="sidebar" style={{ display: 'flex', flexDirection: 'column' }}>
      <div className="sidebar-logo">Elfin OS</div>
      <nav className="sidebar-nav" style={{ flex: 1, overflowY: 'auto' }}>
        {NAV_ITEMS.map((item) => (
          <NavLink
            key={item.id}
            to={item.path}
            className={({ isActive }) =>
              `nav-link${isActive ? ' active' : ''}`
            }
          >
            {item.label}
          </NavLink>
        ))}
      </nav>
      <div style={{ padding: '0.5rem 1rem' }}>
        <button onClick={toggle} className="btn" style={{ width: '100%' }}>
          {light ? 'DARK MODE' : 'LIGHT MODE'}
        </button>
      </div>
      <div style={{ padding: '0.5rem 1rem' }}>
        <button
          onClick={handleLogout}
          className="btn"
          style={{ width: '100%', borderColor: 'rgba(255, 68, 68, 0.4)', color: 'rgba(255, 68, 68, 0.8)' }}
        >
          LOGOUT
        </button>
      </div>
      <div className="sidebar-status">
        <span className="status-dot" /> Systems Online
      </div>
    </aside>
  )
}
