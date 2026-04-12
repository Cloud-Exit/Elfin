import { Outlet } from 'react-router'
import { Sidebar } from './Sidebar'

export function Shell() {
  return (
    <>
      <div className="crt-scanlines" />
      <div className="crt-glow" />
      <div className="shell">
        <Sidebar />
        <main className="main">
          <div className="main-content">
            <Outlet />
          </div>
        </main>
      </div>
    </>
  )
}
