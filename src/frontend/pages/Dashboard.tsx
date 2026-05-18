import { useState, useEffect } from 'react'
import { PageHeader } from '../components/PageHeader'
import { fetchWithAuth } from '../utils/fetchWithAuth'

function InfoRow({ label, value, status }: { label: string; value: string; status?: 'ok' | 'warn' | 'err' }) {
  const color = status === 'ok' ? '#66ffcc' : status === 'warn' ? '#ffaa3c' : status === 'err' ? '#ff4444' : undefined
  return (
    <div className="info-row">
      <span className="info-label">{label}</span>
      <span style={color ? { color } : undefined}>{value}</span>
    </div>
  )
}

function StatCard({ label, value, sub }: { label: string; value: string | number; sub?: string }) {
  return (
    <div className="card" style={{ textAlign: 'center', padding: '1.5rem 1rem' }}>
      <div style={{ fontSize: '0.75rem', letterSpacing: '0.2rem', textTransform: 'uppercase', color: 'rgba(var(--alt), 0.9)', marginBottom: '0.5rem' }}>{label}</div>
      <div style={{ fontSize: '2rem', fontWeight: 'bold', color: 'rgb(var(--main))', textShadow: '0 0 0.8rem rgba(var(--main), 0.2)' }}>{value}</div>
      {sub && <div style={{ fontSize: '0.8rem', color: 'rgba(var(--main), 0.5)', marginTop: '0.25rem' }}>{sub}</div>}
    </div>
  )
}

interface DashboardData {
  documents: number
  chatSessions: number
  chatMessages: number
  notes: number
  llmStatus: 'ok' | 'err'
  qdrantStatus: 'ok' | 'err'
  kiwixStatus: 'ok' | 'err'
  embedStatus: 'ok' | 'err'
}

export function DashboardPage() {
  const [data, setData] = useState<DashboardData | null>(null)

  useEffect(() => {
    async function load() {
      const results: DashboardData = {
        documents: 0,
        chatSessions: 0,
        chatMessages: 0,
        notes: 0,
        llmStatus: 'err',
        qdrantStatus: 'err',
        kiwixStatus: 'err',
        embedStatus: 'err',
      }

      const checks = [
        fetchWithAuth('/api/chat/sessions?limit=1').then(async r => {
          if (r.ok) { const d = await r.json(); results.chatSessions = d.total || 0 }
        }).catch(() => {}),
        fetchWithAuth('/api/notes?limit=1').then(async r => {
          if (r.ok) { const d = await r.json(); results.notes = d.total || 0 }
        }).catch(() => {}),
        fetch('http://localhost:8081/health').then(r => { if (r.ok) results.llmStatus = 'ok' }).catch(() => {}),
        fetch('http://localhost:6333/collections/elfin_docs').then(async r => {
          if (r.ok) {
            const d = await r.json()
            results.qdrantStatus = 'ok'
            results.documents = d.result?.points_count || 0
          }
        }).catch(() => {}),
        fetch('http://localhost:8083/catalog/v2/root.xml').then(r => { if (r.ok) results.kiwixStatus = 'ok' }).catch(() => {}),
        fetch('http://localhost:8082/health').then(r => { if (r.ok) results.embedStatus = 'ok' }).catch(() => {}),
      ]

      await Promise.allSettled(checks)
      setData(results)
    }
    load()
    const interval = setInterval(load, 30_000)
    return () => clearInterval(interval)
  }, [])

  return (
    <>
      <PageHeader title="Status" />

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: '1rem', marginBottom: '1.5rem' }}>
        <StatCard label="Indexed Chunks" value={data?.documents ?? '...'} sub="in Qdrant" />
        <StatCard label="Chat Sessions" value={data?.chatSessions ?? '...'} />
        <StatCard label="Notes" value={data?.notes ?? '...'} />
        <StatCard label="Services" value={data ? [data.llmStatus, data.qdrantStatus, data.kiwixStatus, data.embedStatus].filter(s => s === 'ok').length + '/4' : '...'} sub="online" />
      </div>

      <div className="section-header">Services</div>
      <div className="card" style={{ marginBottom: '1.5rem' }}>
        <InfoRow label="LLM (llama-server)" value={data?.llmStatus === 'ok' ? 'Online' : 'Offline'} status={data?.llmStatus} />
        <InfoRow label="Embeddings (llama-embed)" value={data?.embedStatus === 'ok' ? 'Online' : 'Offline'} status={data?.embedStatus} />
        <InfoRow label="Vector DB (Qdrant)" value={data?.qdrantStatus === 'ok' ? 'Online' : 'Offline'} status={data?.qdrantStatus} />
        <InfoRow label="Encyclopedia (Kiwix)" value={data?.kiwixStatus === 'ok' ? 'Online' : 'Offline'} status={data?.kiwixStatus} />
      </div>

      <div className="section-header">Quick Actions</div>
      <div style={{ display: 'flex', gap: '1rem' }}>
        <a href="/chat" style={{ textDecoration: 'none', flex: 1 }}>
          <button className="btn" style={{ width: '100%', padding: '1rem' }}>AI CHAT</button>
        </a>
        <a href="/notes" style={{ textDecoration: 'none', flex: 1 }}>
          <button className="btn" style={{ width: '100%', padding: '1rem' }}>NOTEPAD</button>
        </a>
        <a href="/encyclopedia" style={{ textDecoration: 'none', flex: 1 }}>
          <button className="btn" style={{ width: '100%', padding: '1rem' }}>ENCYCLOPEDIA</button>
        </a>
      </div>
    </>
  )
}
