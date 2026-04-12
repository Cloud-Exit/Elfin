import { NavLink } from 'react-router'
import { NAV_ITEMS } from '@shared/types'

export function Sidebar() {
  return (
    <aside className="sidebar">
      <div className="sidebar-logo">LefinOS</div>
      <nav className="sidebar-nav">
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
      <div className="sidebar-status">
        <span className="status-dot" /> Systems Online
      </div>
    </aside>
  )
}
