import { useState, useEffect } from 'react'

export function LoginPage() {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [demoMode, setDemoMode] = useState(false)

  useEffect(() => {
    fetch('/api/auth/config')
      .then(res => res.json())
      .then(data => {
        if (data.demoMode) setDemoMode(true)
      })
      .catch(console.error)
  }, [])

  const handleDemo = async () => {
    setError('')
    try {
      const res = await fetch('/api/auth/demo', { method: 'POST' })
      if (res.ok) {
        const data = await res.json()
        localStorage.setItem('token', data.token)
        window.location.href = '/'
      } else {
        const data = await res.json()
        setError(data.error || 'Failed to start demo')
      }
    } catch (err) {
      setError('Network error')
    }
  }

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')

    try {
      const res = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password })
      })

      if (res.ok) {
        const data = await res.json()
        localStorage.setItem('token', data.token)
        window.location.href = '/'
      } else {
        const data = await res.json()
        setError(data.error || 'Login failed')
      }
    } catch (err) {
      setError('Network error')
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100%', width: '100%', padding: 'clamp(1rem, 3vmin, 2rem)', overflowY: 'auto' }}>
      <h1 style={{ fontSize: 'clamp(1.2rem, 4vmin, 2rem)', marginBottom: 'clamp(1rem, 3vmin, 2rem)', textShadow: '0 0 1rem rgba(var(--main), 0.8)' }}>Elfin OS</h1>

      <form onSubmit={handleLogin} className="card" style={{ display: 'flex', flexDirection: 'column', gap: 'clamp(0.5rem, 2vmin, 1rem)', width: '100%', maxWidth: 'min(400px, 90vw)', padding: 'clamp(1rem, 3vmin, 2rem)' }}>
        <h2 style={{ marginBottom: 'clamp(0.5rem, 2vmin, 1rem)', borderBottom: '1px solid rgba(var(--main), 0.2)', paddingBottom: '0.5rem', width: '100%', textAlign: 'center', fontSize: 'clamp(0.9rem, 2.5vmin, 1.2rem)' }}>Authentication Required</h2>

        {error && <div style={{ color: '#f44', marginBottom: '0.5rem', textAlign: 'center' }}>{error}</div>}

        <div style={{ textAlign: 'center' }}>
          <label style={{ display: 'block', marginBottom: '0.5rem', textAlign: 'center' }}>USERNAME</label>
          <input
            type="text"
            value={username}
            onChange={e => setUsername(e.target.value)}
            style={{ width: '100%', padding: 'clamp(0.4rem, 1.5vmin, 0.75rem)', background: 'rgba(0,0,0,0.5)', color: 'rgb(var(--main))', border: '1px solid rgba(var(--main), 0.4)', fontFamily: 'inherit', textAlign: 'center', fontSize: 'clamp(12px, 2vmin, 14px)' }}
            autoFocus
          />
        </div>

        <div style={{ textAlign: 'center' }}>
          <label style={{ display: 'block', marginBottom: '0.5rem', textAlign: 'center' }}>PASSWORD</label>
          <input
            type="password"
            value={password}
            onChange={e => setPassword(e.target.value)}
            style={{ width: '100%', padding: 'clamp(0.4rem, 1.5vmin, 0.75rem)', background: 'rgba(0,0,0,0.5)', color: 'rgb(var(--main))', border: '1px solid rgba(var(--main), 0.4)', fontFamily: 'inherit', textAlign: 'center', fontSize: 'clamp(12px, 2vmin, 14px)' }}
          />
        </div>

        <button type="submit" className="btn" style={{ marginTop: '0.5rem', padding: 'clamp(0.5rem, 1.5vmin, 0.75rem)' }}>LOGIN</button>
      </form>

      {demoMode && (
        <div className="card" style={{ marginTop: 'clamp(1rem, 3vmin, 2rem)', display: 'flex', flexDirection: 'column', alignItems: 'center', width: '100%', maxWidth: 'min(400px, 90vw)', padding: 'clamp(1rem, 3vmin, 2rem)' }}>
          <h2 style={{ marginBottom: 'clamp(0.5rem, 2vmin, 1rem)', borderBottom: '1px solid rgba(var(--main), 0.2)', paddingBottom: '0.5rem', width: '100%', textAlign: 'center', fontSize: 'clamp(0.9rem, 2.5vmin, 1.2rem)' }}>Demo Mode</h2>
          <p style={{ marginBottom: 'clamp(0.75rem, 2vmin, 1.5rem)', textAlign: 'center', color: 'rgba(var(--main), 0.7)', fontSize: 'clamp(11px, 1.8vmin, 13px)' }}>
            Try Elfin instantly. Demo accounts and data are automatically deleted after 24 hours.
          </p>
          <button onClick={handleDemo} className="btn" style={{ width: '100%', padding: 'clamp(0.5rem, 1.5vmin, 0.75rem)' }}>START DEMO</button>
        </div>
      )}
    </div>
  )
}
