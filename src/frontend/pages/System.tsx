import { useState, useEffect, useRef } from 'react'
import { PageHeader } from '../components/PageHeader'
import { fetchWithAuth } from '../utils/fetchWithAuth'

const SPECS = [
  { label: 'Device', value: 'Turing RK1' },
  { label: 'SoC', value: 'Rockchip RK3588' },
  { label: 'CPU', value: '8-core ARM Cortex (4x A76 + 4x A55)' },
  { label: 'NPU', value: '6 TOPS RKNPU2' },
  { label: 'Memory', value: '16 GB LPDDR4X' },
  { label: 'Storage', value: 'NVMe SSD' },
  { label: 'Inference', value: 'Local, on-device (llama.cpp)' },
  { label: 'Model', value: 'Google Gemma 4' },
  { label: 'Connectivity', value: 'Offline-first, no cloud required' },
]

const ZONE_LABELS: Record<string, string> = {
  'soc-thermal': 'SoC',
  'bigcore0-thermal': 'Big Core 0',
  'bigcore1-thermal': 'Big Core 1',
  'littlecore-thermal': 'Little Core',
  'center-thermal': 'Center',
  'gpu-thermal': 'GPU',
  'npu-thermal': 'NPU',
}

const MAX_HISTORY = 60

interface ThermalReading { zone: string; temp: number }
interface ServiceStatus { llm: string; embed: string; qdrant: string; kiwix: string; documents: number }

function tempColor(t: number): string {
  if (t >= 80) return '#ff4444'
  if (t >= 65) return 'rgb(var(--main))'
  return '#66ffcc'
}

function TempChart({ history, zone }: { history: number[]; zone: string }) {
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas || history.length < 2) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const w = canvas.width
    const h = canvas.height
    const min = 30
    const max = 95

    ctx.clearRect(0, 0, w, h)

    // threshold line at 80C
    const y80 = h - ((80 - min) / (max - min)) * h
    ctx.strokeStyle = 'rgba(255, 68, 68, 0.25)'
    ctx.setLineDash([4, 4])
    ctx.beginPath()
    ctx.moveTo(0, y80)
    ctx.lineTo(w, y80)
    ctx.stroke()
    ctx.setLineDash([])

    // temp line
    ctx.strokeStyle = tempColor(history[history.length - 1] ?? 50)
    ctx.lineWidth = 1.5
    ctx.beginPath()
    for (let i = 0; i < history.length; i++) {
      const x = (i / (MAX_HISTORY - 1)) * w
      const y = h - ((history[i]! - min) / (max - min)) * h
      if (i === 0) ctx.moveTo(x, y)
      else ctx.lineTo(x, y)
    }
    ctx.stroke()

    // glow
    ctx.globalAlpha = 0.15
    ctx.strokeStyle = tempColor(history[history.length - 1] ?? 50)
    ctx.lineWidth = 4
    ctx.beginPath()
    for (let i = 0; i < history.length; i++) {
      const x = (i / (MAX_HISTORY - 1)) * w
      const y = h - ((history[i]! - min) / (max - min)) * h
      if (i === 0) ctx.moveTo(x, y)
      else ctx.lineTo(x, y)
    }
    ctx.stroke()
    ctx.globalAlpha = 1
  }, [history, zone])

  return (
    <canvas
      ref={canvasRef}
      width={200}
      height={40}
      style={{ width: '100%', height: '40px', display: 'block' }}
    />
  )
}

export function SystemPage() {
  const [status, setStatus] = useState<ServiceStatus | null>(null)
  const [temps, setTemps] = useState<ThermalReading[]>([])
  const [history, setHistory] = useState<Record<string, number[]>>({})

  useEffect(() => {
    fetchWithAuth('/api/status')
      .then(r => r.ok ? r.json() : null)
      .then(setStatus)
      .catch(() => {})
  }, [])

  useEffect(() => {
    const poll = () => {
      fetchWithAuth('/api/thermals')
        .then(r => r.ok ? r.json() : null)
        .then(data => {
          if (!data?.temps) return
          setTemps(data.temps)
          setHistory(prev => {
            const next = { ...prev }
            for (const t of data.temps) {
              const arr = [...(next[t.zone] || [])]
              arr.push(t.temp)
              if (arr.length > MAX_HISTORY) arr.shift()
              next[t.zone] = arr
            }
            return next
          })
        })
        .catch(() => {})
    }
    poll()
    const id = setInterval(poll, 5000)
    return () => clearInterval(id)
  }, [])

  const online = status
    ? [status.llm, status.embed, status.qdrant, status.kiwix].filter(s => s === 'ok').length
    : null

  const socTemp = temps.find(t => t.zone === 'soc-thermal')

  return (
    <>
      <PageHeader title="System" />

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1.5rem' }}>
        <div>
          <div className="section-header">Hardware</div>
          <div className="card" style={{ marginBottom: '1.5rem' }}>
            {SPECS.map(s => (
              <div key={s.label} className="info-row">
                <span className="info-label">{s.label}</span>
                <span>{s.value}</span>
              </div>
            ))}
          </div>

          <div className="section-header">About</div>
          <div className="card">
            <div className="info-row">
              <span className="info-label">Project</span>
              <span>Elfin</span>
            </div>
            <div className="info-row">
              <span className="info-label">Purpose</span>
              <span>Offline survival companion</span>
            </div>
            <div className="info-row" style={{ borderBottom: 'none' }}>
              <span className="info-label">Hackathon</span>
              <span>Gemma 4 Good</span>
            </div>
          </div>
        </div>

        <div>
          <div className="section-header">
            Thermals
            {socTemp && (
              <span style={{ float: 'right', color: tempColor(socTemp.temp), letterSpacing: 0, textTransform: 'none', fontSize: '11px' }}>
                SoC {socTemp.temp}C
              </span>
            )}
          </div>
          <div className="card" style={{ marginBottom: '1.5rem' }}>
            {temps.length === 0 && (
              <div className="info-row" style={{ borderBottom: 'none' }}>
                <span className="info-label">Status</span>
                <span style={{ color: 'rgba(var(--main), 0.4)' }}>Reading sensors...</span>
              </div>
            )}
            {temps.map(t => (
              <div key={t.zone} style={{ marginBottom: '0.5rem' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px', marginBottom: '2px' }}>
                  <span className="info-label">{ZONE_LABELS[t.zone] || t.zone}</span>
                  <span style={{ color: tempColor(t.temp) }}>{t.temp}C</span>
                </div>
                <TempChart history={history[t.zone] || []} zone={t.zone} />
              </div>
            ))}
          </div>

          <div className="section-header">Services</div>
          <div className="card">
            <ServiceRow label="LLM Server" ok={status?.llm === 'ok'} />
            <ServiceRow label="Embeddings" ok={status?.embed === 'ok'} />
            <ServiceRow label="Vector DB" ok={status?.qdrant === 'ok'} />
            <ServiceRow label="Encyclopedia" ok={status?.kiwix === 'ok'} />
            <div className="info-row" style={{ borderBottom: 'none' }}>
              <span className="info-label">Overall</span>
              <span>{online !== null ? `${online}/4 online` : '...'}</span>
            </div>
          </div>
        </div>
      </div>
    </>
  )
}

function ServiceRow({ label, ok }: { label: string; ok?: boolean }) {
  return (
    <div className="info-row">
      <span className="info-label">{label}</span>
      <span style={{ color: ok ? '#66ffcc' : '#ff4444' }}>
        {ok === undefined ? '...' : ok ? 'Online' : 'Offline'}
      </span>
    </div>
  )
}
