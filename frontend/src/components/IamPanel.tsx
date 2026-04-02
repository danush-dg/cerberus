import { useState } from 'react'
import type { IamPlan } from '../types'
import { submitTicket, getIamInventory, getTickets, type IAMBindingResponse, type IamTicketResponse } from '../api'

interface IamPanelProps {
  onTicketCreated?: (plan: IamPlan) => void
}

type ActiveTab = 'request' | 'records'

// ---------------------------------------------------------------------------
// Status display config — covers all statuses the backend can return
// ---------------------------------------------------------------------------

function getStatusStyle(status: string): { bg: string; color: string; label: string } {
  const s = status.toLowerCase()
  if (s === 'active' || s.startsWith('active'))
    return { bg: '#e8f5e9', color: '#2e7d32', label: status }
  if (s === 'stale')
    return { bg: '#fff3e0', color: '#e65100', label: 'Stale' }
  if (s === 'revoked')
    return { bg: '#f3e5f5', color: '#7b1fa2', label: 'Revoked' }
  if (s.includes('departed') || s.includes('inactive'))
    return { bg: '#ffebee', color: '#c62828', label: 'Departed' }
  return { bg: '#e9ecef', color: '#495057', label: status }
}

function isIssue(status: string): boolean {
  const s = status.toLowerCase()
  return s === 'stale' || s === 'revoked' || s.includes('departed') || s.includes('inactive')
}

function isCerberusManaged(b: IAMBindingResponse, tickets: IamTicketResponse[]): boolean {
  return tickets.some(t => {
    const plan = t.plan as Record<string, unknown>
    return (
      (plan.requester_email as string | undefined) === b.identity &&
      (plan.role as string | undefined) === b.role
    )
  })
}

function getCerberusTicket(b: IAMBindingResponse, tickets: IamTicketResponse[]): IamTicketResponse | undefined {
  return tickets.find(t => {
    const plan = t.plan as Record<string, unknown>
    return (
      (plan.requester_email as string | undefined) === b.identity &&
      (plan.role as string | undefined) === b.role
    )
  })
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function IamPanel({ onTicketCreated }: IamPanelProps) {
  const [activeTab, setActiveTab] = useState<ActiveTab>('request')

  // ── Request form state ──────────────────────────────────────────────────
  const [requesterEmail, setRequesterEmail] = useState('')
  const [projectId, setProjectId]           = useState('')
  const [requestText, setRequestText]       = useState('')
  const [roleName, setRoleName]             = useState('')
  const [loading, setLoading]               = useState(false)
  const [error, setError]                   = useState<string | null>(null)
  const [plan, setPlan]                     = useState<IamPlan | null>(null)
  const [submitted, setSubmitted]           = useState(false)

  // ── Identity records state ───────────────────────────────────────────────
  const [inventoryProjectId, setInventoryProjectId] = useState('')
  const [inventoryLoading, setInventoryLoading]     = useState(false)
  const [inventoryError, setInventoryError]         = useState<string | null>(null)
  const [bindings, setBindings]                     = useState<IAMBindingResponse[] | null>(null)
  const [cerberusTickets, setCerberusTickets]       = useState<IamTicketResponse[]>([])
  const [searchEmail, setSearchEmail]               = useState('')
  const [filterStatus, setFilterStatus]             = useState<string>('all')

  // ---------------------------------------------------------------------------
  // Request form logic
  // ---------------------------------------------------------------------------

  async function handleSynthesize() {
    if (!requesterEmail.trim() || !projectId.trim() || !requestText.trim() || !roleName.trim()) return
    setLoading(true); setError(null); setPlan(null); setSubmitted(false)
    try {
      const res = await fetch('/api/iam/request', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          natural_language_request: requestText.trim(),
          requester_email: requesterEmail.trim(),
          project_id: projectId.trim(),
          role: roleName.trim(),
        }),
      })
      const data = await res.json()
      if (!res.ok) { setError(data.error ?? `HTTP ${res.status}`); return }
      setPlan(data.plan ?? data)
      setSubmitted(true)
      onTicketCreated?.(data.plan ?? data)
      // Pre-fill inventory project_id so the records tab is ready
      setInventoryProjectId(projectId.trim())
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
    setRequesterEmail(''); setProjectId(''); setRequestText(''); setRoleName('')
  }

  // ---------------------------------------------------------------------------
  // Identity records logic
  // ---------------------------------------------------------------------------

  async function handleLoadInventory(pid?: string) {
    const target = (pid ?? inventoryProjectId).trim()
    if (!target) return
    setInventoryLoading(true)
    setInventoryError(null)
    setBindings(null)
    try {
      const [data, tickets] = await Promise.all([
        getIamInventory(target),
        getTickets().catch(() => [] as IamTicketResponse[]),
      ])
      setBindings(data)
      setCerberusTickets(tickets)
      if (!inventoryProjectId) setInventoryProjectId(target)
    } catch (e) {
      setInventoryError(e instanceof Error ? e.message : String(e))
    } finally {
      setInventoryLoading(false)
    }
  }

  function handleTabSwitch(tab: ActiveTab) {
    setActiveTab(tab)
    // Auto-load inventory when switching to records if project_id is known and not yet loaded
    if (tab === 'records' && !bindings && !inventoryLoading) {
      const pid = inventoryProjectId || projectId
      if (pid) {
        setInventoryProjectId(pid)
        handleLoadInventory(pid)
      }
    }
  }

  const filteredBindings = (bindings ?? []).filter(b => {
    const matchEmail  = !searchEmail || b.identity.toLowerCase().includes(searchEmail.toLowerCase())
    const matchStatus =
      filterStatus === 'all'
        ? true
        : filterStatus === 'cerberus'
          ? isCerberusManaged(b, cerberusTickets)
          : b.status.toLowerCase() === filterStatus.toLowerCase()
    return matchEmail && matchStatus
  })

  const issueCount = (bindings ?? []).filter(b => isIssue(b.status)).length

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div style={card}>
      {/* Tab bar */}
      <div style={{ display: 'flex', gap: 0, borderBottom: '2px solid #e0e0e0', marginBottom: 20 }}>
        <button style={tabBtn(activeTab === 'request')} onClick={() => handleTabSwitch('request')}>
          New Request
        </button>
        <button style={tabBtn(activeTab === 'records')} onClick={() => handleTabSwitch('records')}>
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
                <label style={lbl}>Custom Role Name</label>
                <input
                  style={inp}
                  placeholder="e.g. bigquery-read-access, ml-pipeline-writer"
                  value={roleName}
                  onChange={e => setRoleName(e.target.value)}
                />
                <span style={{ fontSize: 11, color: '#888', marginTop: 2 }}>
                  A descriptive name for this access. Cerberus will create a custom GCP role with minimum permissions.
                </span>
              </div>
              <div style={row}>
                <label style={lbl}>Justification</label>
                <textarea
                  style={{ ...inp, height: 72, resize: 'vertical' }}
                  placeholder="e.g. I need read access to the ml-pipeline Cloud Storage bucket for model training"
                  value={requestText}
                  onChange={e => setRequestText(e.target.value)}
                />
              </div>
              <button
                style={{ ...btn, background: loading ? '#90a4ae' : '#1a237e', cursor: loading ? 'not-allowed' : 'pointer' }}
                disabled={loading || !requesterEmail.trim() || !projectId.trim() || !requestText.trim() || !roleName.trim()}
                onClick={handleSynthesize}
              >
                {loading ? 'Submitting…' : 'Request IAM Access →'}
              </button>
              {error && <div style={errBox}>{error}</div>}
            </div>
          )}

          {plan && submitted && (
            <div>
              <div style={{ ...planHeader, background: '#e8f5e9', borderColor: '#a5d6a7' }}>
                <span style={{ fontWeight: 700, color: '#2e7d32' }}>✓ Access request submitted — pending admin approval</span>
              </div>
              <div style={section}>
                <div style={sectionTitle}>Requester</div>
                <div>{plan.requester_email}</div>
              </div>
              <div style={section}>
                <div style={sectionTitle}>Requested Role</div>
                <code style={{ ...pill, background: '#e3f2fd', color: '#1565c0' }}>{plan.role ?? plan.custom_role_id}</code>
              </div>
              {plan.permissions && plan.permissions.length > 0 && (
                <div style={section}>
                  <div style={sectionTitle}>Representative Permissions ({plan.permissions.length})</div>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 4 }}>
                    {plan.permissions.map(p => (
                      <code key={p} style={{ ...pill, background: '#e8f5e9', color: '#2e7d32' }}>{p}</code>
                    ))}
                  </div>
                </div>
              )}
              <div style={section}>
                <div style={sectionTitle}>Justification</div>
                <p style={{ margin: 0, fontSize: 13, color: '#333', fontStyle: 'italic' }}>{plan.justification ?? plan.reasoning}</p>
              </div>
              <div style={approvalBar}>
                <span style={{ fontSize: 13, color: '#555' }}>
                  Ticket created — pending admin approval in the <strong>Tickets</strong> tab.
                </span>
                <button style={{ ...btn, background: '#455a64', padding: '8px 20px' }} onClick={handleReset}>
                  New request
                </button>
              </div>
            </div>
          )}
        </>
      )}

      {/* ── Identity Records Tab ───────────────────────────────────────────── */}
      {activeTab === 'records' && (
        <>
          <h2 style={{ marginTop: 0, fontSize: 18, color: '#1a237e' }}>IAM Identity Records</h2>
          <p style={{ color: '#555', fontSize: 13, marginBottom: 16 }}>
            Live GCP IAM bindings for the project, enriched with Cerberus ticket history.
            Includes all provisioned, stale, and revoked identities.
          </p>

          {/* Project ID input */}
          <div style={{ display: 'flex', gap: 8, marginBottom: 16, alignItems: 'center' }}>
            <input
              style={{ ...inp, flex: 1, marginBottom: 0 }}
              placeholder="nexus-tech-dev-sandbox"
              value={inventoryProjectId}
              onChange={e => setInventoryProjectId(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleLoadInventory()}
            />
            <button
              style={{
                ...btn,
                background: inventoryLoading ? '#90a4ae' : '#1a237e',
                cursor: inventoryLoading ? 'not-allowed' : 'pointer',
                padding: '9px 20px',
                whiteSpace: 'nowrap',
              }}
              disabled={inventoryLoading || !inventoryProjectId.trim()}
              onClick={() => handleLoadInventory()}
            >
              {inventoryLoading ? 'Loading…' : '↻ Load Records'}
            </button>
          </div>

          {inventoryError && (
            <div style={{ ...errBox, marginBottom: 14 }}>
              {inventoryError.includes('403') || inventoryError.includes('credentials')
                ? '⚠ GCP credentials not configured — only ChromaDB ticket history will be available once configured.'
                : inventoryError}
            </div>
          )}

          {/* Loading spinner */}
          {inventoryLoading && (
            <div style={{ textAlign: 'center', padding: 32, color: '#6c757d', fontSize: 14 }}>
              <div style={{ width: 20, height: 20, border: '2px solid #1a237e', borderTopColor: 'transparent', borderRadius: '50%', animation: 'spin 0.9s linear infinite', margin: '0 auto 12px' }} />
              Fetching live GCP bindings…
            </div>
          )}

          {/* Empty state before load */}
          {!bindings && !inventoryLoading && !inventoryError && (
            <div style={{ textAlign: 'center', padding: 32, color: '#9e9e9e', fontSize: 14 }}>
              Enter a project ID and click Load Records to see live IAM bindings.
            </div>
          )}

          {/* Results */}
          {bindings && !inventoryLoading && (
            <>
              {/* Summary chips */}
              <div style={{ display: 'flex', gap: 10, marginBottom: 14, flexWrap: 'wrap' }}>
                {[
                  { label: 'Total',    count: bindings.length,                                                       bg: '#e3f2fd', color: '#1565c0' },
                  { label: 'Active',   count: bindings.filter(b => !isIssue(b.status)).length,                       bg: '#e8f5e9', color: '#2e7d32' },
                  { label: 'Issues',   count: issueCount,                                                            bg: '#ffebee', color: '#c62828' },
                  { label: 'Cerberus', count: bindings.filter(b => isCerberusManaged(b, cerberusTickets)).length,    bg: '#e8eaf6', color: '#3949ab' },
                ].map(s => (
                  <div key={s.label} style={{ padding: '4px 14px', borderRadius: 14, background: s.bg, color: s.color, fontSize: 13, fontWeight: 600 }}>
                    {s.label}: {s.count}
                  </div>
                ))}
              </div>

              {/* Filters */}
              <div style={{ display: 'flex', gap: 10, marginBottom: 14 }}>
                <input
                  style={{ ...inp, flex: 1, marginBottom: 0 }}
                  placeholder="Search by identity / email…"
                  value={searchEmail}
                  onChange={e => setSearchEmail(e.target.value)}
                />
                <select
                  style={{ ...inp, width: 160, marginBottom: 0 }}
                  value={filterStatus}
                  onChange={e => setFilterStatus(e.target.value)}
                >
                  <option value="all">All statuses</option>
                  <option value="active">Active</option>
                  <option value="stale">Stale</option>
                  <option value="revoked">Revoked</option>
                  <option value="inactive/departed">Departed</option>
                  <option value="cerberus">Cerberus-managed</option>
                </select>
              </div>

              {/* Table */}
              <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
                  <thead>
                    <tr style={{ background: '#f8f9fa', borderBottom: '2px solid #dee2e6' }}>
                      {['Identity', 'Role', 'Type', 'Status', 'Last Activity', 'Days Inactive'].map(h => (
                        <th key={h} style={{ padding: '8px 12px', textAlign: 'left', fontSize: 11, fontWeight: 700, color: '#666', textTransform: 'uppercase', letterSpacing: '0.05em', whiteSpace: 'nowrap' }}>
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {filteredBindings.length === 0 && (
                      <tr>
                        <td colSpan={6} style={{ padding: '20px', textAlign: 'center', color: '#888' }}>
                          No identities match the current filter.
                        </td>
                      </tr>
                    )}
                    {filteredBindings.map((b, i) => {
                      const st = getStatusStyle(b.status)
                      const isSvc = b.binding_type === 'serviceAccount' || b.identity.includes('gserviceaccount')
                      const daysNum = parseInt(b.days_inactive ?? '0', 10)
                      const cerberusTicket = getCerberusTicket(b, cerberusTickets)
                      return (
                        <tr key={`${b.identity}-${b.role}-${i}`} style={{ borderBottom: '1px solid #f0f0f0' }}>
                          <td style={{ padding: '10px 12px' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
                              <span style={{ fontSize: 14 }}>{isSvc ? '⚙️' : '👤'}</span>
                              <span style={{ fontFamily: 'monospace', fontSize: 12, color: '#333', wordBreak: 'break-all' }}>{b.identity || '—'}</span>
                              {cerberusTicket && (
                                <span title={`Cerberus ticket · ${cerberusTicket.status}`} style={{ background: '#e8eaf6', color: '#3949ab', fontSize: 10, fontWeight: 700, borderRadius: 4, padding: '1px 5px', letterSpacing: '0.03em', whiteSpace: 'nowrap' }}>
                                  CERBERUS · {cerberusTicket.status.toUpperCase()}
                                </span>
                              )}
                            </div>
                          </td>
                          <td style={{ padding: '10px 12px' }}>
                            <code style={{ background: '#f5f5f5', padding: '2px 6px', borderRadius: 3, fontSize: 11, color: '#555', wordBreak: 'break-all' }}>{b.role || '—'}</code>
                          </td>
                          <td style={{ padding: '10px 12px', color: '#6c757d', fontSize: 12 }}>
                            {b.binding_type || '—'}
                          </td>
                          <td style={{ padding: '10px 12px' }}>
                            <span style={{ background: st.bg, color: st.color, padding: '2px 8px', borderRadius: 10, fontSize: 11, fontWeight: 700, whiteSpace: 'nowrap' }}>
                              {st.label}
                            </span>
                          </td>
                          <td style={{ padding: '10px 12px', color: '#555', fontSize: 12, whiteSpace: 'nowrap' }}>
                            {b.last_activity ?? '—'}
                          </td>
                          <td style={{ padding: '10px 12px', textAlign: 'center' }}>
                            <span style={{ color: daysNum > 90 ? '#c62828' : daysNum > 30 ? '#e65100' : '#2e7d32', fontWeight: 600 }}>
                              {b.days_inactive ?? '—'}
                            </span>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>

              {filteredBindings.length > 0 && (
                <div style={{ fontSize: 12, color: '#888', marginTop: 10 }}>
                  Showing {filteredBindings.length} of {bindings.length} bindings
                  {issueCount > 0 && (
                    <span style={{ marginLeft: 8, color: '#e65100' }}>· {issueCount} require attention</span>
                  )}
                </div>
              )}
            </>
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
