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

interface IAMTicket {
  ticket_id: string
  status: string
  created_at: string
  reviewed_at: string | null
  reviewed_by: string | null
  plan: {
    requester_email: string
    project_id: string
    role: string
    permissions: string[]
    justification: string
    synthesized_at: string
    raw_request: string
  }
}

interface GhostResource {
  resource_id: string
  resource_type: string
  region: string
  owner_email: string
  decision: string
  estimated_monthly_cost: number
  estimated_monthly_savings: number
  reasoning: string | null
}

interface CostOwnerRow {
  owner_email: string
  cost_usd: number
}

interface ProjectCostSummary {
  project_id: string
  total_usd: number
  attributed_usd: number
  unattributed_usd: number
  breakdown: CostOwnerRow[]
  ghost_resources: GhostResource[]
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

const TICKET_BADGE: Record<string, React.CSSProperties> = {
  pending:     { background: '#fff8e1', color: '#e65100', border: '1px solid #ffcc80', borderRadius: 4, padding: '2px 8px', fontSize: 11, fontWeight: 700 },
  approved:    { background: '#e8f5e9', color: '#2e7d32', border: '1px solid #a5d6a7', borderRadius: 4, padding: '2px 8px', fontSize: 11, fontWeight: 700 },
  provisioned: { background: '#e3f2fd', color: '#1565c0', border: '1px solid #90caf9', borderRadius: 4, padding: '2px 8px', fontSize: 11, fontWeight: 700 },
  rejected:    { background: '#ffebee', color: '#c62828', border: '1px solid #ef9a9a', borderRadius: 4, padding: '2px 8px', fontSize: 11, fontWeight: 700 },
  revoked:     { background: '#f3e5f5', color: '#6a1b9a', border: '1px solid #ce93d8', borderRadius: 4, padding: '2px 8px', fontSize: 11, fontWeight: 700 },
}

const DECISION_BADGE: Record<string, React.CSSProperties> = {
  safe_to_stop:   { background: '#fff8e1', color: '#e65100', border: '1px solid #ffcc80', borderRadius: 4, padding: '2px 8px', fontSize: 11, fontWeight: 700 },
  safe_to_delete: { background: '#ffebee', color: '#c62828', border: '1px solid #ef9a9a', borderRadius: 4, padding: '2px 8px', fontSize: 11, fontWeight: 700 },
}

function emDash(v: string | null | undefined): string {
  return v ?? '—'
}

// ---------------------------------------------------------------------------
// SecurityHub
// ---------------------------------------------------------------------------

export function SecurityHub({ projectId }: { projectId?: string }) {
  const pid = projectId?.trim() || ''

  // Security flags
  const [flags, setFlags] = useState<SecurityFlag[]>([])
  const [flagsLoading, setFlagsLoading] = useState(false)
  const [flagsError, setFlagsError] = useState<string | null>(null)

  // Budget
  const [budget, setBudget] = useState<BudgetStatus | null>(null)
  const [budgetLoading, setBudgetLoading] = useState(false)
  const [budgetError, setBudgetError] = useState<string | null>(null)

  // IAM tickets
  const [tickets, setTickets] = useState<IAMTicket[]>([])
  const [ticketsLoading, setTicketsLoading] = useState(false)
  const [ticketsError, setTicketsError] = useState<string | null>(null)
  const [expandedTicket, setExpandedTicket] = useState<string | null>(null)

  // Cost billing
  const [costSummary, setCostSummary] = useState<ProjectCostSummary | null>(null)
  const [costLoading, setCostLoading] = useState(false)
  const [costError, setCostError] = useState<string | null>(null)

  // PDF
  const [pdfLoading, setPdfLoading] = useState(false)
  const [pdfError, setPdfError] = useState<string | null>(null)

  useEffect(() => {
    if (!pid) return
    fetchFlags()
    fetchBudget()
    fetchTickets()
    fetchCost()
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

  async function fetchTickets() {
    setTicketsLoading(true)
    setTicketsError(null)
    try {
      const res = await fetch(`${API_BASE}/tickets`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const all: IAMTicket[] = await res.json()
      setTickets(all.filter(t => t.plan.project_id === pid))
    } catch (err) {
      setTicketsError(err instanceof Error ? err.message : 'Failed to load IAM tickets')
    } finally {
      setTicketsLoading(false)
    }
  }

  async function fetchCost() {
    setCostLoading(true)
    setCostError(null)
    try {
      const res = await fetch(`${API_BASE}/cost/project/${encodeURIComponent(pid)}`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setCostSummary(await res.json())
    } catch (err) {
      setCostError(err instanceof Error ? err.message : 'Failed to load cost data')
    } finally {
      setCostLoading(false)
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
    } catch {
      setPdfError('Report generation failed. Try again.')
    } finally {
      setPdfLoading(false)
    }
  }

  return (
    <div>
      <h1 style={{ margin: '0 0 4px', fontSize: 24, fontWeight: 700 }}>Security Hub</h1>
      <p style={{ margin: '0 0 20px', color: '#6c757d', fontSize: 14 }}>
        Security flags, IAM provisioning history, and project cost billing.
      </p>

      {!pid && (
        <div style={{ ...card, color: '#6c757d', textAlign: 'center', padding: 32 }}>
          Enter a project ID in the Dashboard to load security data.
        </div>
      )}

      {/* ------------------------------------------------------------------ */}
      {/* Section 1: Security Flags                                           */}
      {/* ------------------------------------------------------------------ */}
      {pid && (
        <div style={card}>
          <h2 style={{ margin: '0 0 16px', fontSize: 16 }}>Active Security Flags</h2>
          {flagsLoading && <div style={{ color: '#1f77b4', fontSize: 13 }}>Loading flags…</div>}
          {flagsError && <div style={{ color: '#c62828', fontSize: 13, marginBottom: 12 }}>{flagsError}</div>}
          {!flagsLoading && (
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
              <thead>
                <tr>
                  <th style={thStyle}>Flag Type</th>
                  <th style={thStyle}>Resource / Identity</th>
                  <th style={thStyle}>Detected</th>
                  <th style={thStyle}>Detail</th>
                </tr>
              </thead>
              <tbody>
                {flags.map((f) => (
                  <tr key={f.flag_id}>
                    <td style={tdStyle}>
                      <span style={FLAG_BADGE[f.flag_type] ?? {}}>{f.flag_type.replace(/_/g, ' ')}</span>
                    </td>
                    <td style={{ ...tdStyle, fontFamily: 'monospace', fontSize: 12 }}>{f.identity_or_resource || '—'}</td>
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

      {/* ------------------------------------------------------------------ */}
      {/* Section 2: Budget Status                                            */}
      {/* ------------------------------------------------------------------ */}
      {pid && (
        <div style={card}>
          <h2 style={{ margin: '0 0 16px', fontSize: 16 }}>Budget Status</h2>
          {budgetLoading && <div style={{ color: '#1f77b4', fontSize: 13 }}>Loading budget status…</div>}
          {budgetError && <div style={{ color: '#c62828', fontSize: 13 }}>{budgetError}</div>}
          {budget && !budgetLoading && (
            <div>
              <div style={{ marginBottom: 8, fontSize: 13, color: budget.breached ? '#c62828' : '#495057' }}>
                ${budget.current_month_usd.toFixed(2)} of ${budget.threshold_usd.toFixed(2)} threshold used ({budget.percent_used}%)
                {budget.breached && (
                  <span style={{ marginLeft: 10, fontWeight: 700, color: '#c62828' }}>Budget threshold exceeded</span>
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

      {/* ------------------------------------------------------------------ */}
      {/* Section 3: IAM Provisioning Tickets                                 */}
      {/* ------------------------------------------------------------------ */}
      {pid && (
        <div style={card}>
          <h2 style={{ margin: '0 0 16px', fontSize: 16 }}>IAM Provisioning Tickets</h2>
          {ticketsLoading && <div style={{ color: '#1f77b4', fontSize: 13 }}>Loading tickets…</div>}
          {ticketsError && <div style={{ color: '#c62828', fontSize: 13, marginBottom: 12 }}>{ticketsError}</div>}
          {!ticketsLoading && (
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
              <thead>
                <tr>
                  <th style={thStyle}>Ticket ID</th>
                  <th style={thStyle}>Requester</th>
                  <th style={thStyle}>Role</th>
                  <th style={thStyle}>Status</th>
                  <th style={thStyle}>Created</th>
                  <th style={thStyle}>Reviewed By</th>
                  <th style={thStyle}>Details</th>
                </tr>
              </thead>
              <tbody>
                {tickets.map((t) => (
                  <>
                    <tr key={t.ticket_id}>
                      <td style={{ ...tdStyle, fontFamily: 'monospace', fontSize: 11 }}>
                        {t.ticket_id.slice(0, 8)}…
                      </td>
                      <td style={{ ...tdStyle, fontFamily: 'monospace', fontSize: 12 }}>
                        {emDash(t.plan.requester_email)}
                      </td>
                      <td style={{ ...tdStyle, fontFamily: 'monospace', fontSize: 12 }}>
                        {emDash(t.plan.role)}
                      </td>
                      <td style={tdStyle}>
                        <span style={TICKET_BADGE[t.status] ?? {}}>{t.status}</span>
                      </td>
                      <td style={{ ...tdStyle, color: '#6c757d', fontSize: 12 }}>
                        {t.created_at ? t.created_at.slice(0, 19).replace('T', ' ') : '—'}
                      </td>
                      <td style={{ ...tdStyle, fontFamily: 'monospace', fontSize: 12 }}>
                        {emDash(t.reviewed_by)}
                      </td>
                      <td style={tdStyle}>
                        <button
                          onClick={() => setExpandedTicket(expandedTicket === t.ticket_id ? null : t.ticket_id)}
                          style={{ background: 'none', border: '1px solid #dee2e6', borderRadius: 4, padding: '2px 8px', cursor: 'pointer', fontSize: 12 }}
                        >
                          {expandedTicket === t.ticket_id ? 'Hide' : 'Show'}
                        </button>
                      </td>
                    </tr>
                    {expandedTicket === t.ticket_id && (
                      <tr key={`${t.ticket_id}-detail`}>
                        <td colSpan={7} style={{ padding: '12px 16px', background: '#f8f9fa', borderBottom: '1px solid #dee2e6' }}>
                          <div style={{ fontSize: 12, display: 'grid', gap: 6 }}>
                            <div><b>Justification:</b> {emDash(t.plan.justification)}</div>
                            <div><b>Original request:</b> {emDash(t.plan.raw_request)}</div>
                            <div>
                              <b>Permissions ({t.plan.permissions.length}):</b>{' '}
                              {t.plan.permissions.length > 0
                                ? t.plan.permissions.map(p => (
                                    <span key={p} style={{ fontFamily: 'monospace', fontSize: 11, background: '#e3f2fd', borderRadius: 3, padding: '1px 5px', marginRight: 4 }}>{p}</span>
                                  ))
                                : '—'}
                            </div>
                            {t.reviewed_at && (
                              <div><b>Reviewed at:</b> {t.reviewed_at.slice(0, 19).replace('T', ' ')}</div>
                            )}
                          </div>
                        </td>
                      </tr>
                    )}
                  </>
                ))}
                {tickets.length === 0 && !ticketsLoading && !ticketsError && (
                  <tr>
                    <td colSpan={7} style={{ ...tdStyle, color: '#6c757d', textAlign: 'center', padding: 24 }}>
                      No IAM tickets for this project.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          )}
        </div>
      )}

      {/* ------------------------------------------------------------------ */}
      {/* Section 4: Cost Billing                                             */}
      {/* ------------------------------------------------------------------ */}
      {pid && (
        <div style={card}>
          <h2 style={{ margin: '0 0 16px', fontSize: 16 }}>Cost Billing</h2>
          {costLoading && <div style={{ color: '#1f77b4', fontSize: 13 }}>Loading cost data…</div>}
          {costError && <div style={{ color: '#c62828', fontSize: 13, marginBottom: 12 }}>{costError}</div>}
          {costSummary && !costLoading && (
            <div>
              {/* Cost totals */}
              <div style={{ display: 'flex', gap: 16, marginBottom: 16, flexWrap: 'wrap' }}>
                {[
                  { label: 'Total ($/mo)', value: `$${costSummary.total_usd.toFixed(2)}`, color: '#1f77b4' },
                  { label: 'Attributed', value: `$${costSummary.attributed_usd.toFixed(2)}`, color: '#2e7d32' },
                  { label: 'Unattributed', value: `$${costSummary.unattributed_usd.toFixed(2)}`, color: costSummary.unattributed_usd > 0 ? '#e65100' : '#6c757d' },
                  { label: 'Ghost Resources', value: String(costSummary.ghost_resources.length), color: costSummary.ghost_resources.length > 0 ? '#c62828' : '#6c757d' },
                ].map(item => (
                  <div key={item.label} style={{ border: '1px solid #dee2e6', borderRadius: 6, padding: '10px 18px', minWidth: 110, textAlign: 'center' }}>
                    <div style={{ fontSize: 11, color: '#6c757d', textTransform: 'uppercase', letterSpacing: 0.5 }}>{item.label}</div>
                    <div style={{ fontSize: 20, fontWeight: 700, color: item.color, marginTop: 2 }}>{item.value}</div>
                  </div>
                ))}
              </div>

              {/* Owner breakdown */}
              <div style={{ marginBottom: 12, fontWeight: 600, fontSize: 13 }}>Cost by Owner</div>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13, marginBottom: 20 }}>
                <thead>
                  <tr>
                    <th style={thStyle}>Owner</th>
                    <th style={{ ...thStyle, textAlign: 'right' }}>Cost ($/mo)</th>
                  </tr>
                </thead>
                <tbody>
                  {costSummary.breakdown.map((row) => (
                    <tr key={row.owner_email}>
                      <td style={{ ...tdStyle, fontFamily: 'monospace', fontSize: 12 }}>{row.owner_email}</td>
                      <td style={{ ...tdStyle, textAlign: 'right', fontWeight: 600 }}>${row.cost_usd.toFixed(2)}</td>
                    </tr>
                  ))}
                  {costSummary.breakdown.length === 0 && (
                    <tr>
                      <td colSpan={2} style={{ ...tdStyle, color: '#6c757d', textAlign: 'center' }}>No cost records.</td>
                    </tr>
                  )}
                </tbody>
              </table>

              {/* Ghost resources from cost scan */}
              {costSummary.ghost_resources.length > 0 && (
                <>
                  <div style={{ marginBottom: 8, fontWeight: 600, fontSize: 13, color: '#c62828' }}>
                    Ghost Resources from Cost Scan ({costSummary.ghost_resources.length})
                  </div>
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
                    <thead>
                      <tr>
                        <th style={thStyle}>Resource ID</th>
                        <th style={thStyle}>Type</th>
                        <th style={thStyle}>Region</th>
                        <th style={thStyle}>Owner</th>
                        <th style={thStyle}>Decision</th>
                        <th style={{ ...thStyle, textAlign: 'right' }}>Cost ($/mo)</th>
                        <th style={{ ...thStyle, textAlign: 'right' }}>Savings</th>
                      </tr>
                    </thead>
                    <tbody>
                      {costSummary.ghost_resources.map((r) => (
                        <tr key={r.resource_id}>
                          <td style={{ ...tdStyle, fontFamily: 'monospace', fontSize: 11 }}>{r.resource_id}</td>
                          <td style={tdStyle}>{r.resource_type}</td>
                          <td style={{ ...tdStyle, color: '#6c757d' }}>{r.region}</td>
                          <td style={{ ...tdStyle, fontFamily: 'monospace', fontSize: 11 }}>{r.owner_email}</td>
                          <td style={tdStyle}>
                            <span style={DECISION_BADGE[r.decision] ?? {}}>{r.decision.replace(/_/g, ' ')}</span>
                          </td>
                          <td style={{ ...tdStyle, textAlign: 'right', fontWeight: 600 }}>${r.estimated_monthly_cost.toFixed(2)}</td>
                          <td style={{ ...tdStyle, textAlign: 'right', color: '#2e7d32', fontWeight: 600 }}>${r.estimated_monthly_savings.toFixed(2)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </>
              )}
            </div>
          )}
        </div>
      )}

      {/* ------------------------------------------------------------------ */}
      {/* Section 5: Audit Report Download                                    */}
      {/* ------------------------------------------------------------------ */}
      {pid && (
        <div style={card}>
          <h2 style={{ margin: '0 0 6px', fontSize: 16 }}>Audit Report</h2>
          <p style={{ margin: '0 0 12px', fontSize: 13, color: '#6c757d' }}>
            PDF includes security flags, IAM bindings, IAM provisioning history, and cost breakdown.
          </p>
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
          {pdfError && <div style={{ marginTop: 10, color: '#c62828', fontSize: 13 }}>{pdfError}</div>}
        </div>
      )}
    </div>
  )
}
