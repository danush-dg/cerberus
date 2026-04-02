import { useEffect, useState } from 'react'

const API_BASE = '/api'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface SecurityFlag {
  flag_id: string
  flag_type: 'OVER_PERMISSIONED' | 'GHOST_RESOURCE' | 'BUDGET_BREACH'
  identity_or_resource: string
  project_id: string
  detected_at: string
  detail: string
  status: string
}

interface BudgetStatus {
  project_id: string
  current_month_usd: number
  threshold_usd: number
  breached: boolean
  percent_used: number
}

// ---------------------------------------------------------------------------
// Styles
// ---------------------------------------------------------------------------

const card: React.CSSProperties = {
  background: '#fff',
  border: '1px solid #dee2e6',
  borderRadius: 8,
  padding: '20px 24px',
  marginBottom: 16,
  boxShadow: '0 1px 3px rgba(0,0,0,0.06)',
}

const thStyle: React.CSSProperties = {
  textAlign: 'left',
  padding: '8px 12px',
  background: '#f8f9fa',
  borderBottom: '2px solid #dee2e6',
  fontWeight: 700,
  color: '#495057',
  fontSize: 12,
  textTransform: 'uppercase',
  letterSpacing: 0.5,
}

const tdStyle: React.CSSProperties = {
  padding: '9px 12px',
  borderBottom: '1px solid #f0f0f0',
  verticalAlign: 'top',
  fontSize: 13,
}

const FLAG_BADGE: Record<string, React.CSSProperties> = {
  OVER_PERMISSIONED: { background: '#ffebee', color: '#c62828', border: '1px solid #ef9a9a', borderRadius: 4, padding: '2px 8px', fontSize: 11, fontWeight: 700 },
  GHOST_RESOURCE:    { background: '#fff8e1', color: '#e65100', border: '1px solid #ffcc80', borderRadius: 4, padding: '2px 8px', fontSize: 11, fontWeight: 700 },
  BUDGET_BREACH:     { background: '#ffebee', color: '#c62828', border: '1px solid #ef9a9a', borderRadius: 4, padding: '2px 8px', fontSize: 11, fontWeight: 700 },
}

// ---------------------------------------------------------------------------
// SecurityHub
// ---------------------------------------------------------------------------

export function SecurityHub({ projectId }: { projectId?: string }) {
  const pid = projectId?.trim() || ''

  const [flags, setFlags] = useState<SecurityFlag[]>([])
  const [flagsLoading, setFlagsLoading] = useState(false)
  const [flagsError, setFlagsError] = useState<string | null>(null)

  const [budget, setBudget] = useState<BudgetStatus | null>(null)
  const [budgetLoading, setBudgetLoading] = useState(false)
  const [budgetError, setBudgetError] = useState<string | null>(null)

  const [pdfLoading, setPdfLoading] = useState(false)
  const [pdfError, setPdfError] = useState<string | null>(null)

  useEffect(() => {
    if (!pid) return
    fetchFlags()
    fetchBudget()
  }, [pid])

  async function fetchFlags() {
    setFlagsLoading(true)
    setFlagsError(null)
    try {
      const res = await fetch(`${API_BASE}/security/flags?project_id=${encodeURIComponent(pid)}`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setFlags(await res.json())
    } catch (err) {
      setFlagsError(err instanceof Error ? err.message : 'Failed to load flags')
    } finally {
      setFlagsLoading(false)
    }
  }

  async function fetchBudget() {
    setBudgetLoading(true)
    setBudgetError(null)
    try {
      const res = await fetch(`${API_BASE}/security/budget-status?project_id=${encodeURIComponent(pid)}`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setBudget(await res.json())
    } catch (err) {
      setBudgetError(err instanceof Error ? err.message : 'Failed to load budget status')
    } finally {
      setBudgetLoading(false)
    }
  }

  async function handleDownloadReport() {
    setPdfLoading(true)
    setPdfError(null)
    try {
      const res = await fetch(
        `${API_BASE}/security/report/download?project_id=${encodeURIComponent(pid)}`,
        { method: 'GET' },
      )
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      const date = new Date().toISOString().slice(0, 10)
      a.href = url
      a.download = `cerberus-audit-${pid}-${date}.pdf`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
    } catch (err) {
      setPdfError('Report generation failed. Try again.')
    } finally {
      setPdfLoading(false)
    }
  }

  return (
    <div>
      <h1 style={{ margin: '0 0 4px', fontSize: 24, fontWeight: 700 }}>Security Hub</h1>
      <p style={{ margin: '0 0 20px', color: '#6c757d', fontSize: 14 }}>
        Monitors over-permissioning, ghost resources, and budget breaches.
      </p>

      {!pid && (
        <div style={{ ...card, color: '#6c757d', textAlign: 'center', padding: 32 }}>
          Enter a project ID in the Dashboard to load security data.
        </div>
      )}

      {/* Section 1: Security Flags */}
      {pid && (
        <div style={card}>
          <h2 style={{ margin: '0 0 16px', fontSize: 16 }}>Active Security Flags</h2>
          {flagsLoading && <div style={{ color: '#1f77b4', fontSize: 13 }}>Loading flags…</div>}
          {flagsError && (
            <div style={{ color: '#c62828', fontSize: 13, marginBottom: 12 }}>{flagsError}</div>
          )}
          {!flagsLoading && (
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
              <thead>
                <tr>
                  <th style={thStyle}>Flag Type</th>
                  <th style={thStyle}>Resource/Identity</th>
                  <th style={thStyle}>Detected</th>
                  <th style={thStyle}>Detail</th>
                </tr>
              </thead>
              <tbody>
                {flags.map((f) => (
                  <tr key={f.flag_id}>
                    <td style={tdStyle}>
                      <span style={FLAG_BADGE[f.flag_type] ?? {}}>
                        {f.flag_type.replace(/_/g, ' ')}
                      </span>
                    </td>
                    <td style={{ ...tdStyle, fontFamily: 'monospace', fontSize: 12 }}>
                      {f.identity_or_resource || '—'}
                    </td>
                    <td style={{ ...tdStyle, color: '#6c757d', fontSize: 12 }}>
                      {f.detected_at ? f.detected_at.slice(0, 19).replace('T', ' ') : '—'}
                    </td>
                    <td style={tdStyle}>{f.detail || '—'}</td>
                  </tr>
                ))}
                {flags.length === 0 && !flagsLoading && !flagsError && (
                  <tr>
                    <td colSpan={4} style={{ ...tdStyle, color: '#6c757d', textAlign: 'center', padding: 24 }}>
                      No active security flags.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          )}
        </div>
      )}

      {/* Section 2: Budget Status */}
      {pid && (
        <div style={card}>
          <h2 style={{ margin: '0 0 16px', fontSize: 16 }}>Budget Status</h2>
          {budgetLoading && <div style={{ color: '#1f77b4', fontSize: 13 }}>Loading budget status…</div>}
          {budgetError && (
            <div style={{ color: '#c62828', fontSize: 13 }}>{budgetError}</div>
          )}
          {budget && !budgetLoading && (
            <div>
              <div style={{ marginBottom: 8, fontSize: 13, color: budget.breached ? '#c62828' : '#495057' }}>
                ${budget.current_month_usd.toFixed(2)} of ${budget.threshold_usd.toFixed(2)} threshold used ({budget.percent_used}%)
                {budget.breached && (
                  <span style={{ marginLeft: 10, fontWeight: 700, color: '#c62828' }}>
                    Budget threshold exceeded
                  </span>
                )}
              </div>
              <div style={{ background: '#e9ecef', borderRadius: 4, height: 12, overflow: 'hidden' }}>
                <div style={{
                  width: `${Math.min(budget.percent_used, 100)}%`,
                  height: '100%',
                  background: budget.breached ? '#f44336' : budget.percent_used > 80 ? '#ff9800' : '#4caf50',
                  transition: 'width 0.4s ease',
                }} />
              </div>
            </div>
          )}
        </div>
      )}

      {/* Section 3: Audit Report Download */}
      {pid && (
        <div style={card}>
          <h2 style={{ margin: '0 0 12px', fontSize: 16 }}>Audit Report</h2>
          <button
            onClick={handleDownloadReport}
            disabled={pdfLoading}
            style={{
              background: '#1f77b4',
              color: '#fff',
              border: 'none',
              borderRadius: 6,
              padding: '9px 20px',
              fontSize: 14,
              fontWeight: 600,
              cursor: pdfLoading ? 'not-allowed' : 'pointer',
              opacity: pdfLoading ? 0.6 : 1,
            }}
          >
            {pdfLoading ? 'Generating…' : 'Download Audit Report (PDF)'}
          </button>
          {pdfError && (
            <div style={{ marginTop: 10, color: '#c62828', fontSize: 13 }}>{pdfError}</div>
          )}
        </div>
      )}
    </div>
  )
}
