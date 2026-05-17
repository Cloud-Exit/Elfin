import { Outlet, useLocation } from 'react-router'
import { Sidebar } from './Sidebar'
import { useState, useEffect } from 'react'
import { LoginPage } from '../pages/Login'

export function Shell() {
  const [hasToken, setHasToken] = useState<boolean | null>(null)
  const location = useLocation()
  const showCrt = location.pathname !== '/encyclopedia'

  useEffect(() => {
    setHasToken(!!localStorage.getItem('token'))
  }, [])

  if (hasToken === null) return null

  if (!hasToken) {
    return (
      <>
        <div className="crt-scanlines" />
        <div className="crt-glow" />
        <LoginPage />
      </>
    )
  }

  return (
    <>
      {showCrt && <div className="crt-scanlines" />}
      {showCrt && <div className="crt-glow" />}
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
