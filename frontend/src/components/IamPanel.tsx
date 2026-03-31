import { useState } from 'react'
import type { IamPlan, IdentityRecord } from '../types'
import { MOCK_IDENTITY_DATA } from '../types'
import { submitTicket } from '../api'

interface IamPanelProps {
  onTicketCreated?: (plan: IamPlan) => void
}

type ActiveTab = 'request' | 'records'

const STATUS_STYLE: Record<IdentityRecord['status'], { bg: string; color: string; label: string }> = {
  active:   { bg: '#e8f5e9', color: '#2e7d32', label: 'Active' },
  stale:    { bg: '#fff3e0', color: '#e65100', label: 'Stale' },
  departed: { bg: '#ffebee', color: '#c62828', label: 'Departed' },
}

export function IamPanel({ onTicketCreated }: IamPanelProps) {
  // Tab
  const [activeTab, setActiveTab] = useState<ActiveTab>('request')

  // Request form state
  const [requesterEmail, setRequesterEmail] = useState('')
  const [projectId, setProjectId]           = useState('')
  const [requestText, setRequestText]       = useState('')
  const [loading, setLoading]               = useState(false)
  const [error, setError]                   = useState<string | null>(null)
  const [plan, setPlan]                     = useState<IamPlan | null>(null)
  const [submitted, setSubmitted]           = useState(false)

  // Identity records filter state
  const [searchEmail, setSearchEmail]     = useState('')
  const [filterStatus, setFilterStatus]   = useState<'all' | IdentityRecord['status']>('all')

  // ---------------------------------------------------------------------------
  // Request form logic
  // ---------------------------------------------------------------------------

  async function handleSynthesize() {
    if (!requesterEmail.trim() || !projectId.trim() || !requestText.trim()) return
    setLoading(true); setError(null); setPlan(null); setSubmitted(false)
    try {
      const res = await fetch('/api/iam/synthesize', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          requester_email: requesterEmail.trim(),
          project_id: projectId.trim(),
          request_text: requestText.trim(),
        }),
      })
      const data = await res.json()
      if (!res.ok) { setError(data.error ?? `HTTP ${res.status}`); return }
      setPlan(data)
    } catch (e) {
      setError(String(e))
    } finally {
      setLoading(false)
    }
  }

  async function handleSubmit() {
    if (!plan) return
    setLoading(true); setError(null)
    try {
      await submitTicket(plan as unknown as Record<string, unknown>)
      onTicketCreated?.(plan)
      setSubmitted(true)
    } catch (e) {
      setError(String(e))
    } finally {
      setLoading(false)
    }
  }

  function handleReset() {
    setPlan(null); setSubmitted(false); setError(null)
    setRequesterEmail(''); setProjectId(''); setRequestText('')
  }

  // ---------------------------------------------------------------------------
  // Derived identity data
  // ---------------------------------------------------------------------------

  const filteredIdentities = MOCK_IDENTITY_DATA.filter(id => {
    const matchEmail  = !searchEmail || id.email.toLowerCase().includes(searchEmail.toLowerCase())
    const matchStatus = filterStatus === 'all' || id.status === filterStatus
    return matchEmail && matchStatus
  })

  const issueCount = MOCK_IDENTITY_DATA.filter(i => i.status !== 'active').length

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div style={card}>
      {/* Tab bar */}
      <div style={{ display: 'flex', gap: 0, borderBottom: '2px solid #e0e0e0', marginBottom: 20 }}>
        <button style={tabBtn(activeTab === 'request')} onClick={() => setActiveTab('request')}>
          New Request
        </button>
        <button style={tabBtn(activeTab === 'records')} onClick={() => setActiveTab('records')}>
          Identity Records
          {issueCount > 0 && (
            <span style={{ marginLeft: 7, background: '#ffebee', color: '#c62828', borderRadius: 10, padding: '1px 6px', fontSize: 10, fontWeight: 700 }}>
              {issueCount} issues
            </span>
          )}
        </button>
      </div>

      {/* ── Access Request Tab ─────────────────────────────────────────────── */}
      {activeTab === 'request' && (
        <>
          <h2 style={{ marginTop: 0, fontSize: 18, color: '#1a237e' }}>IAM Access Request</h2>
          <p style={{ color: '#555', fontSize: 13, marginBottom: 16 }}>
            Describe access in plain English. Cerberus synthesizes the minimum GCP
            permissions via Gemini and routes to admin for approval.
          </p>

          {!plan && !submitted && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              <div style={row}>
                <label style={lbl}>Requester email</label>
                <input style={inp} placeholder="anurag@company.com" value={requesterEmail} onChange={e => setRequesterEmail(e.target.value)} />
              </div>
              <div style={row}>
                <label style={lbl}>Project ID</label>
                <input style={inp} placeholder="nexus-tech-dev-sandbox" value={projectId} onChange={e => setProjectId(e.target.value)} />
              </div>
              <div style={row}>
                <label style={lbl}>Access request</label>
                <textarea
                  style={{ ...inp, height: 72, resize: 'vertical' }}
                  placeholder="e.g. I need BigQuery write access and Cloud Storage read access for the ml-pipeline dataset"
                  value={requestText}
                  onChange={e => setRequestText(e.target.value)}
                />
              </div>
              <button
                style={{ ...btn, background: loading ? '#90a4ae' : '#1a237e', cursor: loading ? 'not-allowed' : 'pointer' }}
                disabled={loading || !requesterEmail.trim() || !projectId.trim() || !requestText.trim()}
                onClick={handleSynthesize}
              >
                {loading ? 'Synthesizing…' : 'Synthesize IAM Plan →'}
              </button>
              {error && <div style={errBox}>{error}</div>}
            </div>
          )}

          {plan && !submitted && (
            <div>
              <div style={planHeader}>
                <span style={{ fontWeight: 700, color: '#1a237e' }}>Plan synthesized — review before submitting</span>
              </div>
              <div style={section}>
                <div style={sectionTitle}>Requester</div>
                <div>{plan.requester_email}</div>
              </div>
              <div style={section}>
                <div style={sectionTitle}>Custom Role</div>
                <code style={pill}>{plan.custom_role_id}</code>
              </div>
              <div style={section}>
                <div style={sectionTitle}>Permissions ({plan.permissions.length})</div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 4 }}>
                  {plan.permissions.map(p => (
                    <code key={p} style={{ ...pill, background: '#e8f5e9', color: '#2e7d32' }}>{p}</code>
                  ))}
                </div>
              </div>
              <div style={section}>
                <div style={sectionTitle}>IAM Condition (CEL)</div>
                <code style={{ ...pill, background: '#fff8e1', color: '#6d4c41', fontSize: 12 }}>
                  {plan.binding_condition || '—'}
                </code>
              </div>
              <div style={section}>
                <div style={sectionTitle}>Reasoning</div>
                <p style={{ margin: 0, fontSize: 13, color: '#333', fontStyle: 'italic' }}>{plan.reasoning}</p>
              </div>
              <div style={section}>
                <div style={sectionTitle}>Provisioning Checklist</div>
                <ol style={{ margin: '6px 0 0 18px', padding: 0, fontSize: 13, lineHeight: 1.7 }}>
                  {plan.checklist.map((step, i) => <li key={i} style={{ color: '#333' }}>{step}</li>)}
                </ol>
              </div>
              <div style={section}>
                <div style={{ display: 'flex', gap: 6, fontSize: 12, color: '#666' }}>
                  <span>Budget alert: <strong>${plan.budget_alert_threshold_usd}/mo</strong></span>
                  <span>·</span>
                  <span>Review in: <strong>{plan.review_after_days} days</strong></span>
                </div>
              </div>
              <div style={approvalBar}>
                <span style={{ fontWeight: 600, fontSize: 14 }}>Submit for Admin Approval</span>
                <div style={{ display: 'flex', gap: 8 }}>
                  <button style={{ ...btn, background: '#1a237e', padding: '8px 20px' }} onClick={handleSubmit}>
                    Submit Ticket →
                  </button>
                  <button style={{ ...btn, background: '#78909c', padding: '8px 20px' }} onClick={handleReset}>
                    Cancel
                  </button>
                </div>
              </div>
            </div>
          )}

          {submitted && (
            <div style={{ ...resultBox, borderColor: '#1a237e', background: '#e8eaf6' }}>
              <div style={{ fontWeight: 700, color: '#1a237e', marginBottom: 8 }}>Ticket submitted for admin review</div>
              <p style={{ margin: 0, fontSize: 13, color: '#333' }}>
                Role <code style={{ ...pill, background: '#c5cae9' }}>{plan?.custom_role_id}</code> is pending
                approval for <strong>{plan?.requester_email}</strong> with{' '}
                <strong>{plan?.permissions.length} permission(s)</strong>. No live GCP call has been made.
              </p>
              <p style={{ margin: '8px 0 0', fontSize: 12, color: '#555' }}>
                Visit the <strong>Tickets</strong> tab in the sidebar to approve or reject this request.
              </p>
              <button style={{ ...btn, marginTop: 14, background: '#455a64', cursor: 'pointer' }} onClick={handleReset}>
                New request
              </button>
            </div>
          )}
        </>
      )}

      {/* ── Identity Records Tab ───────────────────────────────────────────── */}
      {activeTab === 'records' && (
        <>
          <h2 style={{ marginTop: 0, fontSize: 18, color: '#1a237e' }}>Identity Records</h2>
          <p style={{ color: '#555', fontSize: 13, marginBottom: 16 }}>
            Current IAM bindings for the dev project. Stale and departed identities are flagged for review.
          </p>

          {/* Summary chips */}
          <div style={{ display: 'flex', gap: 10, marginBottom: 16, flexWrap: 'wrap' }}>
            {(
              [
                { label: 'Total', count: MOCK_IDENTITY_DATA.length, bg: '#e3f2fd', color: '#1565c0' },
                { label: 'Active', count: MOCK_IDENTITY_DATA.filter(i => i.status === 'active').length, bg: '#e8f5e9', color: '#2e7d32' },
                { label: 'Stale', count: MOCK_IDENTITY_DATA.filter(i => i.status === 'stale').length, bg: '#fff3e0', color: '#e65100' },
                { label: 'Departed', count: MOCK_IDENTITY_DATA.filter(i => i.status === 'departed').length, bg: '#ffebee', color: '#c62828' },
              ] as const
            ).map(s => (
              <div key={s.label} style={{ padding: '4px 14px', borderRadius: 14, background: s.bg, color: s.color, fontSize: 13, fontWeight: 600 }}>
                {s.label}: {s.count}
              </div>
            ))}
          </div>

          {/* Filters */}
          <div style={{ display: 'flex', gap: 10, marginBottom: 14 }}>
            <input
              style={{ ...inp, flex: 1, marginBottom: 0 }}
              placeholder="Search by email…"
              value={searchEmail}
              onChange={e => setSearchEmail(e.target.value)}
            />
            <select
              style={{ ...inp, width: 140, marginBottom: 0 }}
              value={filterStatus}
              onChange={e => setFilterStatus(e.target.value as typeof filterStatus)}
            >
              <option value="all">All statuses</option>
              <option value="active">Active</option>
              <option value="stale">Stale</option>
              <option value="departed">Departed</option>
            </select>
          </div>

          {/* Table */}
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
              <thead>
                <tr style={{ background: '#f8f9fa', borderBottom: '2px solid #dee2e6' }}>
                  {['Email / Principal', 'Role', 'Project', 'Status', 'Last Activity', 'Days Inactive'].map(h => (
                    <th key={h} style={{ padding: '8px 12px', textAlign: 'left', fontSize: 11, fontWeight: 700, color: '#666', textTransform: 'uppercase', letterSpacing: '0.05em', whiteSpace: 'nowrap' }}>
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {filteredIdentities.length === 0 && (
                  <tr>
                    <td colSpan={6} style={{ padding: '20px', textAlign: 'center', color: '#888' }}>No identities match the current filter.</td>
                  </tr>
                )}
                {filteredIdentities.map(id => {
                  const s = STATUS_STYLE[id.status]
                  const isSvc = id.email.includes('gserviceaccount')
                  return (
                    <tr key={id.email} style={{ borderBottom: '1px solid #f0f0f0' }}>
                      <td style={{ padding: '10px 12px' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                          <span style={{ fontSize: 14 }}>{isSvc ? '⚙️' : '👤'}</span>
                          <span style={{ fontFamily: 'monospace', fontSize: 12, color: '#333', wordBreak: 'break-all' }}>{id.email}</span>
                        </div>
                      </td>
                      <td style={{ padding: '10px 12px' }}>
                        <code style={{ background: '#f5f5f5', padding: '2px 6px', borderRadius: 3, fontSize: 11, color: '#555' }}>{id.role}</code>
                      </td>
                      <td style={{ padding: '10px 12px', color: '#555', fontSize: 12 }}>{id.project_id}</td>
                      <td style={{ padding: '10px 12px' }}>
                        <span style={{ background: s.bg, color: s.color, padding: '2px 8px', borderRadius: 10, fontSize: 11, fontWeight: 700 }}>
                          {s.label}
                        </span>
                      </td>
                      <td style={{ padding: '10px 12px', color: '#555', fontSize: 12 }}>{id.last_activity ?? '—'}</td>
                      <td style={{ padding: '10px 12px', textAlign: 'center' }}>
                        {id.days_inactive != null ? (
                          <span style={{ color: id.days_inactive > 90 ? '#c62828' : id.days_inactive > 30 ? '#e65100' : '#2e7d32', fontWeight: 600 }}>
                            {id.days_inactive}d
                          </span>
                        ) : '—'}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>

          {filteredIdentities.length > 0 && (
            <div style={{ fontSize: 12, color: '#888', marginTop: 10 }}>
              Showing {filteredIdentities.length} of {MOCK_IDENTITY_DATA.length} identities
              {issueCount > 0 && (
                <span style={{ marginLeft: 8, color: '#e65100' }}>· {issueCount} require attention</span>
              )}
            </div>
          )}
        </>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Styles
// ---------------------------------------------------------------------------

function tabBtn(active: boolean): React.CSSProperties {
  return {
    padding: '10px 18px',
    border: 'none',
    background: 'none',
    cursor: 'pointer',
    fontWeight: active ? 700 : 400,
    fontSize: 14,
    color: active ? '#1a237e' : '#888',
    borderBottom: active ? '2px solid #1a237e' : '2px solid transparent',
    marginBottom: -2,
    display: 'flex',
    alignItems: 'center',
    gap: 4,
  }
}

const card: React.CSSProperties = {
  background: '#fff',
  border: '1px solid #e0e0e0',
  borderRadius: 8,
  padding: 24,
}

const row: React.CSSProperties = { display: 'flex', flexDirection: 'column', gap: 4 }

const lbl: React.CSSProperties = {
  fontSize: 12, fontWeight: 600, color: '#555',
  textTransform: 'uppercase', letterSpacing: '0.05em',
}

const inp: React.CSSProperties = {
  border: '1px solid #ccc', borderRadius: 4, padding: '8px 10px',
  fontSize: 14, fontFamily: 'inherit', width: '100%', boxSizing: 'border-box',
}

const btn: React.CSSProperties = {
  border: 'none', borderRadius: 4, padding: '10px 18px', color: '#fff', fontWeight: 600, fontSize: 14,
}

const pill: React.CSSProperties = {
  background: '#e3f2fd', color: '#1565c0', borderRadius: 4,
  padding: '2px 8px', fontSize: 12, fontFamily: 'monospace',
}

const section: React.CSSProperties = { marginTop: 16 }

const sectionTitle: React.CSSProperties = {
  fontSize: 11, fontWeight: 700, color: '#888',
  textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 4,
}

const planHeader: React.CSSProperties = {
  background: '#e8eaf6', borderRadius: 6, padding: '10px 14px',
  marginBottom: 16, border: '1px solid #c5cae9',
}

const approvalBar: React.CSSProperties = {
  marginTop: 20, padding: '14px 16px', background: '#fff3e0',
  border: '1px solid #ffcc02', borderRadius: 6,
  display: 'flex', alignItems: 'center', justifyContent: 'space-between',
}

const errBox: React.CSSProperties = {
  background: '#ffebee', border: '1px solid #ef9a9a', borderRadius: 4,
  padding: '10px 12px', fontSize: 13, color: '#c62828', whiteSpace: 'pre-wrap',
}

const resultBox: React.CSSProperties = { border: '1px solid', borderRadius: 6, padding: 16 }
