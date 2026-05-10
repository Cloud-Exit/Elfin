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
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100%', width: '100%', padding: '2rem' }}>
      <h1 style={{ fontSize: '2rem', marginBottom: '2rem', textShadow: '0 0 1rem rgba(var(--main), 0.8)' }}>Elfin OS</h1>
      
      <form onSubmit={handleLogin} className="card" style={{ display: 'flex', flexDirection: 'column', gap: '1rem', width: '100%', maxWidth: '400px', padding: '2rem' }}>
        <h2 style={{ marginBottom: '1rem', borderBottom: '1px solid rgba(var(--main), 0.2)', paddingBottom: '0.5rem', width: '100%', textAlign: 'center' }}>Authentication Required</h2>
        
        {error && <div style={{ color: '#f44', marginBottom: '1rem', textAlign: 'center' }}>{error}</div>}
        
        <div style={{ textAlign: 'center' }}>
          <label style={{ display: 'block', marginBottom: '0.5rem', textAlign: 'center' }}>USERNAME</label>
          <input 
            type="text" 
            value={username} 
            onChange={e => setUsername(e.target.value)} 
            style={{ width: '100%', padding: '0.5rem', background: 'rgba(0,0,0,0.5)', color: 'rgb(var(--main))', border: '1px solid rgba(var(--main), 0.4)', fontFamily: 'inherit', textAlign: 'center' }}
            autoFocus
          />
        </div>
        
        <div style={{ textAlign: 'center' }}>
          <label style={{ display: 'block', marginBottom: '0.5rem', textAlign: 'center' }}>PASSWORD</label>
          <input 
            type="password" 
            value={password} 
            onChange={e => setPassword(e.target.value)} 
            style={{ width: '100%', padding: '0.5rem', background: 'rgba(0,0,0,0.5)', color: 'rgb(var(--main))', border: '1px solid rgba(var(--main), 0.4)', fontFamily: 'inherit', textAlign: 'center' }}
          />
        </div>
        
        <button type="submit" className="btn" style={{ marginTop: '1rem', padding: '0.75rem' }}>LOGIN</button>
      </form>
      
      {demoMode && (
        <div className="card" style={{ marginTop: '2rem', display: 'flex', flexDirection: 'column', alignItems: 'center', width: '100%', maxWidth: '400px', padding: '2rem' }}>
          <h2 style={{ marginBottom: '1rem', borderBottom: '1px solid rgba(var(--main), 0.2)', paddingBottom: '0.5rem', width: '100%', textAlign: 'center' }}>Demo Mode</h2>
          <p style={{ marginBottom: '1.5rem', textAlign: 'center', color: 'rgba(var(--main), 0.7)' }}>
            Try Elfin instantly. Demo accounts and data are automatically deleted after 24 hours.
          </p>
          <button onClick={handleDemo} className="btn" style={{ width: '100%', padding: '0.75rem' }}>START DEMO</button>
        </div>
      )}
    </div>
  )
}
