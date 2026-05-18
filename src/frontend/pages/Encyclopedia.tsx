import { PageHeader } from '../components/PageHeader'

const KIWIX_PORT = 8083

export function EncyclopediaPage() {
  const kiwixUrl = `http://${window.location.hostname}:${KIWIX_PORT}`

  return (
    <>
      <PageHeader title="Encyclopedia" />
      <div style={{ flex: 1, minHeight: 0, marginTop: '1rem', overflow: 'hidden', border: '1px solid rgba(var(--main), 0.2)' }}>
        <iframe
          src={kiwixUrl}
          style={{ width: '100%', height: '100%', border: 'none', background: '#fff' }}
          title="Kiwix Encyclopedia"
        />
      </div>
    </>
  )
}
