import { PageHeader } from '../components/PageHeader'

function StatBar({ label, value, max = 10 }: { label: string; value: number; max?: number }) {
  const pct = Math.round((value / max) * 100)
  return (
    <div style={{ marginBottom: 12 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
        <span className="section-label">{label}</span>
        <span>{value}/{max}</span>
      </div>
      <div className="stat-bar-bg">
        <div className="stat-bar-fill" style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="info-row">
      <span className="info-label">{label}</span>
      <span>{value}</span>
    </div>
  )
}

export function DashboardPage() {
  return (
    <>
      <PageHeader title="Status" />

      <div className="grid-2col">
        <div>
          <div className="section-header">Health Overview</div>
          <StatBar label="Mental Health" value={7} />
          <StatBar label="Physical Health" value={8} />
          <StatBar label="Stamina" value={6} />
          <StatBar label="Nutrition" value={5} />
          <StatBar label="Hydration" value={9} />
        </div>

        <div>
          <div className="section-header">System Info</div>
          <InfoRow label="User" value="admin" />
          <InfoRow label="Uptime" value="3h 42m" />
          <InfoRow label="Battery" value="74 Wh" />
          <InfoRow label="Storage" value="236 GB / 4 TB" />
          <InfoRow label="LLM" value="Gemma 4 E4B" />
          <InfoRow label="Qdrant" value="Connected" />
          <InfoRow label="Kiwix" value="Connected" />

          <div className="card" style={{ marginTop: 20 }}>
            <div className="section-label" style={{ marginBottom: 8 }}>Daily Check-in</div>
            <p className="text-dim">No check-in recorded today. How are you feeling?</p>
            <button className="btn" style={{ marginTop: 10 }}>Start Check-in</button>
          </div>
        </div>
      </div>

      <div style={{ marginTop: 24 }}>
        <div className="section-header">Recent Journal</div>
        {[
          { date: '2026-04-10', summary: 'Found clean water source near the ridge. Boiled and stored 4L.' },
          { date: '2026-04-09', summary: 'Solar panel output dropping — cloudy for three days. Rationing power.' },
          { date: '2026-04-08', summary: 'Minor cut on left hand from salvage. Cleaned and bandaged.' },
        ].map((entry) => (
          <div key={entry.date} className="journal-row">
            <span className="journal-date">{entry.date}</span>
            <span className="text-dim">{entry.summary}</span>
          </div>
        ))}
      </div>
    </>
  )
}
