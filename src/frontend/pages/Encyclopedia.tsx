import { PageHeader } from '../components/PageHeader'
import { useState, useEffect } from 'react'

export function EncyclopediaPage() {
  const [kiwixUrl, setKiwixUrl] = useState<string | null>(null)

  useEffect(() => {
    fetch('/api/config').then(r => r.json()).then(c => {
      setKiwixUrl(c.kiwixPublicUrl || '/kiwix/')
    }).catch(() => setKiwixUrl('/kiwix/'))
  }, [])

  return (
    <>
      <PageHeader title="Encyclopedia" />
      <div style={{ flex: 1, minHeight: 0, marginTop: '1rem', overflow: 'hidden', border: '1px solid rgba(var(--main), 0.2)' }}>
        {kiwixUrl ? (
          <iframe
            src={kiwixUrl}
            style={{ width: '100%', height: '100%', border: 'none', background: '#fff' }}
            title="Kiwix Encyclopedia"
          />
        ) : (
          <div className="placeholder">Loading encyclopedia...</div>
        )}
      </div>
    </>
  )
}
