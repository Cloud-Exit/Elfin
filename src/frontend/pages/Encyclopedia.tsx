import { useState, useEffect } from 'react'
import { PageHeader } from '../components/PageHeader'

export function EncyclopediaPage() {
  const [token, setToken] = useState<string | null>(null)

  useEffect(() => {
    const t = localStorage.getItem('token')
    if (t) setToken(t)
  }, [])

  return (
    <>
      <PageHeader title="Encyclopedia" />
      <div className="card" style={{ height: 'calc(100% - 60px)', marginTop: '1rem', padding: 0, overflow: 'hidden' }}>
        {token ? (
          <iframe 
            src={`/api/kiwix?token=${token}`} 
            style={{ width: '100%', height: '100%', border: 'none', background: '#fff' }}
            title="Kiwix Encyclopedia"
          />
        ) : (
          <div className="placeholder" style={{ padding: '2rem' }}>Loading token...</div>
        )}
      </div>
    </>
  )
}
