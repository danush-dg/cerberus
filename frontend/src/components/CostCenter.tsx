import { useState, useEffect } from 'react'
import {
  getProjectCostSummary,
  getRecentProjects,
  getUserCostSummary,
  executeResourceAction,
  type ProjectCostSummaryResponse,
  type ProjectResourceRecord,
  type UserCostSummaryResponse,
  type ExecuteResourceResponse,
} from '../api'

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

const primaryBtn: React.CSSProperties = {
  background: '#1f77b4',
  color: '#fff',
  border: 'none',
  borderRadius: 6,
  padding: '9px 20px',
  fontSize: 14,
  fontWeight: 600,
  cursor: 'pointer',
}

const inputStyle: React.CSSProperties = {
  padding: '9px 12px',
  fontSize: 14,
  border: '1px solid #ced4da',
  borderRadius: 6,
  marginRight: 8,
  width: 280,
}

const tableStyle: React.CSSProperties = {
  width: '100%',
  borderCollapse: 'collapse',
  fontSize: 13,
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
}

// ---------------------------------------------------------------------------
// Decision badge styles
// ---------------------------------------------------------------------------

const DECISION_BADGE: Record<string, React.CSSProperties> = {
  safe_to_stop:   { background: '#fff8e1', color: '#e65100', border: '1px solid #ffcc80', borderRadius: 4, padding: '2px 8px', fontSize: 11, fontWeight: 700 },
  safe_to_delete: { background: '#ffebee', color: '#c62828', border: '1px solid #ef9a9a', borderRadius: 4, padding: '2px 8px', fontSize: 11, fontWeight: 700 },
  needs_review:   { background: '#e3f2fd', color: '#1565c0', border: '1px solid #90caf9', borderRadius: 4, padding: '2px 8px', fontSize: 11, fontWeight: 700 },
  skip:           { background: '#f1f3f5', color: '#868e96', border: '1px solid #dee2e6', borderRadius: 4, padding: '2px 8px', fontSize: 11, fontWeight: 700 },
  unknown:        { background: '#f1f3f5', color: '#868e96', border: '1px solid #dee2e6', borderRadius: 4, padding: '2px 8px', fontSize: 11, fontWeight: 700 },
}

function DecisionBadge({ decision }: { decision: string }) {
  const style = DECISION_BADGE[decision] ?? DECISION_BADGE.unknown
  return <span style={style}>{decision.replace(/_/g, ' ')}</span>
}

// ---------------------------------------------------------------------------
// Action confirm modal
// ---------------------------------------------------------------------------

interface ModalProps {
  resource: ProjectResourceRecord
  projectId: string
  onClose: () => void
  onDone: (result: ExecuteResourceResponse) => void
}

function ActionModal({ resource, projectId, onClose, onDone }: ModalProps) {
  const [dryRun, setDryRun] = useState(true)
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<ExecuteResourceResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  const actionLabel = resource.decision === 'safe_to_stop' ? 'Stop' : 'Delete'

  async function handleExecute() {
    setLoading(true)
    setError(null)
    try {
      const res = await executeResourceAction(
        resource.resource_id,
        resource.resource_type,
        resource.decision,
        projectId,
        dryRun,
      )
      setResult(res)
      onDone(res)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Execution failed')
    } finally {
      setLoading(false)
    }
  }

  const outcomeColor: Record<string, string> = {
    SUCCESS: '#2e7d32',
    DRY_RUN: '#1565c0',
    FAILED:  '#c62828',
    SKIPPED: '#e65100',
  }

  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.45)',
      display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000,
    }}>
      <div style={{ background: '#fff', borderRadius: 10, padding: 28, width: 480, boxShadow: '0 8px 32px rgba(0,0,0,0.18)' }}>
        <h3 style={{ margin: '0 0 16px', fontSize: 17 }}>
          Approve Action: <span style={{ color: resource.decision === 'safe_to_delete' ? '#c62828' : '#e65100' }}>{actionLabel}</span>
        </h3>

        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13, marginBottom: 18 }}>
          <tbody>
            {[
              ['Resource ID', resource.resource_id],
              ['Type',        resource.resource_type],
              ['Region',      resource.region || '—'],
              ['Owner',       resource.owner_email || '—'],
              ['Decision',    resource.decision],
              ['Est. Cost',   `$${resource.estimated_monthly_cost.toFixed(2)}/mo`],
            ].map(([k, v]) => (
              <tr key={k}>
                <td style={{ padding: '5px 8px', color: '#6c757d', fontWeight: 600, width: 120 }}>{k}</td>
                <td style={{ padding: '5px 8px', fontFamily: k === 'Resource ID' ? 'monospace' : undefined }}>{v}</td>
              </tr>
            ))}
          </tbody>
        </table>

        {resource.reasoning && (
          <div style={{ background: '#f8f9fa', borderRadius: 6, padding: '10px 12px', fontSize: 12, color: '#495057', marginBottom: 16, lineHeight: 1.5 }}>
            <strong>Reasoning:</strong> {resource.reasoning}
          </div>
        )}

        {/* Dry-run toggle */}
        {!result && (
          <label style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 18, cursor: 'pointer', fontSize: 13 }}>
            <input
              type="checkbox"
              checked={dryRun}
              onChange={e => setDryRun(e.target.checked)}
              style={{ width: 16, height: 16 }}
            />
            <span>
              <strong>Dry Run</strong> — preview only, no GCP mutation
            </span>
          </label>
        )}

        {/* Result */}
        {result && (
          <div style={{
            background: '#f8f9fa', borderRadius: 6, padding: '10px 14px',
            marginBottom: 16, borderLeft: `4px solid ${outcomeColor[result.outcome] ?? '#868e96'}`,
          }}>
            <div style={{ fontWeight: 700, color: outcomeColor[result.outcome], marginBottom: 4 }}>
              {result.outcome}
            </div>
            <div style={{ fontSize: 13, color: '#495057' }}>{result.detail}</div>
          </div>
        )}

        {error && (
          <div style={{ background: '#ffebee', borderRadius: 6, padding: '8px 12px', color: '#c62828', fontSize: 13, marginBottom: 14 }}>
            {error}
          </div>
        )}

        <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
          <button
            onClick={onClose}
            style={{ background: 'none', border: '1px solid #ced4da', borderRadius: 6, padding: '8px 18px', cursor: 'pointer', fontSize: 14 }}
          >
            {result ? 'Close' : 'Cancel'}
          </button>
          {!result && (
            <button
              onClick={handleExecute}
              disabled={loading}
              style={{
                ...primaryBtn,
                background: resource.decision === 'safe_to_delete' ? '#c62828' : '#e65100',
                opacity: loading ? 0.6 : 1,
                cursor: loading ? 'not-allowed' : 'pointer',
              }}
            >
              {loading ? 'Executing…' : `${dryRun ? '[Dry Run] ' : ''}${actionLabel}`}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Resource table (all project resources with decisions)
// ---------------------------------------------------------------------------

interface ResourcesTableProps {
  summary: ProjectCostSummaryResponse
  onAction: (resource: ProjectResourceRecord) => void
  actionResults: Record<string, ExecuteResourceResponse>
}

function ResourcesTable({ summary, onAction, actionResults }: ResourcesTableProps) {
  const [filter, setFilter] = useState<'all' | 'actionable'>('all')

  const displayed = filter === 'actionable'
    ? summary.resources.filter(r => r.decision === 'safe_to_stop' || r.decision === 'safe_to_delete')
    : summary.resources

  return (
    <div style={card}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
        <h2 style={{ margin: 0, fontSize: 16 }}>
          All Resources — <span style={{ color: '#1f77b4' }}>{summary.project_id}</span>
          <span style={{ marginLeft: 10, fontSize: 13, fontWeight: 400, color: '#6c757d' }}>
            {summary.resources.length} resource{summary.resources.length !== 1 ? 's' : ''}
          </span>
        </h2>
        <div style={{ display: 'flex', gap: 6 }}>
          {(['all', 'actionable'] as const).map(f => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              style={{
                padding: '4px 12px', fontSize: 12, borderRadius: 4, cursor: 'pointer',
                border: `1px solid ${filter === f ? '#1f77b4' : '#ced4da'}`,
                background: filter === f ? '#e3f2fd' : '#fff',
                color: filter === f ? '#1f77b4' : '#495057',
                fontWeight: filter === f ? 700 : 400,
              }}
            >
              {f === 'all' ? 'All' : 'Actionable only'}
            </button>
          ))}
        </div>
      </div>

      <table style={tableStyle}>
        <thead>
          <tr>
            <th style={thStyle}>Resource ID</th>
            <th style={thStyle}>Type</th>
            <th style={thStyle}>Region</th>
            <th style={thStyle}>Owner</th>
            <th style={thStyle}>Decision</th>
            <th style={thStyle}>Reasoning</th>
            <th style={{ ...thStyle, textAlign: 'right' }}>Est. Cost/mo</th>
            <th style={thStyle}>Action</th>
          </tr>
        </thead>
        <tbody>
          {displayed.map((r) => {
            const isActionable = r.decision === 'safe_to_stop' || r.decision === 'safe_to_delete'
            const actionLabel = r.decision === 'safe_to_stop' ? 'Stop' : r.decision === 'safe_to_delete' ? 'Delete' : null
            const result = actionResults[r.resource_id]

            const outcomeStyle: Record<string, React.CSSProperties> = {
              SUCCESS: { color: '#2e7d32', fontWeight: 700 },
              DRY_RUN: { color: '#1565c0', fontWeight: 700 },
              FAILED:  { color: '#c62828', fontWeight: 700 },
            }

            return (
              <tr key={r.resource_id} style={result?.outcome === 'SUCCESS' ? { background: '#f1f8e9' } : {}}>
                <td style={{ ...tdStyle, fontFamily: 'monospace', fontSize: 12, maxWidth: 180, wordBreak: 'break-all' }}>
                  {r.resource_id || '—'}
                </td>
                <td style={tdStyle}>{r.resource_type || '—'}</td>
                <td style={{ ...tdStyle, fontSize: 12, color: '#6c757d' }}>{r.region || '—'}</td>
                <td style={{ ...tdStyle, fontSize: 12, maxWidth: 140, wordBreak: 'break-all' }}>
                  {r.owner_email || '—'}
                </td>
                <td style={tdStyle}>
                  <DecisionBadge decision={r.decision} />
                </td>
                <td style={{ ...tdStyle, fontSize: 12, color: '#495057', maxWidth: 200 }}>
                  {r.reasoning || '—'}
                </td>
                <td style={{ ...tdStyle, textAlign: 'right', fontWeight: 600 }}>
                  {r.estimated_monthly_cost > 0 ? `$${r.estimated_monthly_cost.toFixed(2)}` : '—'}
                </td>
                <td style={tdStyle}>
                  {result ? (
                    <span style={outcomeStyle[result.outcome] ?? {}}>
                      {result.outcome}
                    </span>
                  ) : isActionable ? (
                    <button
                      onClick={() => onAction(r)}
                      style={{
                        padding: '4px 12px',
                        fontSize: 12,
                        fontWeight: 600,
                        borderRadius: 4,
                        border: 'none',
                        cursor: 'pointer',
                        background: r.decision === 'safe_to_delete' ? '#ffebee' : '#fff8e1',
                        color: r.decision === 'safe_to_delete' ? '#c62828' : '#e65100',
                      }}
                    >
                      {actionLabel}
                    </button>
                  ) : (
                    <span style={{ color: '#ced4da', fontSize: 12 }}>—</span>
                  )}
                </td>
              </tr>
            )
          })}
          {displayed.length === 0 && (
            <tr>
              <td colSpan={8} style={{ ...tdStyle, color: '#6c757d', textAlign: 'center', padding: 24 }}>
                {filter === 'actionable'
                  ? 'No actionable resources found. Run a scan to classify resources.'
                  : 'No resources found. Run a scan first to populate ChromaDB.'}
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function SummaryKpi({ label, value, borderColor }: { label: string; value: string; borderColor: string }) {
  return (
    <div style={{ ...card, borderLeft: `4px solid ${borderColor}`, marginBottom: 0, padding: '14px 18px' }}>
      <div style={{ fontSize: 11, color: '#6c757d', marginBottom: 4 }}>{label}</div>
      <div style={{ fontSize: 20, fontWeight: 700 }}>{value}</div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Project breakdown table (owner breakdown)
// ---------------------------------------------------------------------------

function ProjectBreakdownTable({
  summary,
  onDrillDown,
}: {
  summary: ProjectCostSummaryResponse
  onDrillDown: (email: string) => void
}) {
  return (
    <div style={card}>
      <h2 style={{ margin: '0 0 6px', fontSize: 16 }}>
        Owner Breakdown — <span style={{ color: '#1f77b4' }}>{summary.project_id}</span>
      </h2>
      <p style={{ margin: '0 0 16px', fontSize: 13, color: '#6c757d' }}>
        Period: {summary.period} · {summary.breakdown.length} owner(s)
      </p>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 12, marginBottom: 20 }}>
        <SummaryKpi label="Total" value={`$${summary.total_usd.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`} borderColor="#1f77b4" />
        <SummaryKpi label="Attributed" value={`$${summary.attributed_usd.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`} borderColor="#4caf50" />
        <SummaryKpi label="Unattributed" value={`$${summary.unattributed_usd.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`} borderColor="#ff9800" />
      </div>

      <table style={tableStyle}>
        <thead>
          <tr>
            <th style={thStyle}>Owner</th>
            <th style={{ ...thStyle, textAlign: 'right' }}>Monthly Cost</th>
            <th style={{ ...thStyle, textAlign: 'right' }}>% of Total</th>
            <th style={thStyle}>Actions</th>
          </tr>
        </thead>
        <tbody>
          {summary.breakdown.map((row) => {
            const isUnattributed = row.owner_email === 'unattributed'
            const pct = summary.total_usd > 0
              ? ((row.cost_usd / summary.total_usd) * 100).toFixed(1)
              : '0.0'
            return (
              <tr key={row.owner_email} style={isUnattributed ? { background: '#fff8e1' } : {}}>
                <td style={tdStyle}>
                  <span style={{
                    fontFamily: 'monospace',
                    color: isUnattributed ? '#e65100' : '#212529',
                    fontWeight: isUnattributed ? 700 : 400,
                  }}>
                    {row.owner_email === 'unattributed' ? '⚠ unattributed' : row.owner_email}
                  </span>
                </td>
                <td style={{ ...tdStyle, textAlign: 'right', fontWeight: 600 }}>
                  {row.cost_usd === 0 ? '—' : `$${row.cost_usd.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`}
                </td>
                <td style={{ ...tdStyle, textAlign: 'right', color: '#6c757d' }}>{pct}%</td>
                <td style={tdStyle}>
                  {!isUnattributed && (
                    <button
                      style={{ ...primaryBtn, padding: '4px 12px', fontSize: 12 }}
                      onClick={() => onDrillDown(row.owner_email)}
                    >
                      Drill down
                    </button>
                  )}
                </td>
              </tr>
            )
          })}
          {summary.breakdown.length === 0 && (
            <tr>
              <td colSpan={4} style={{ ...tdStyle, color: '#6c757d', textAlign: 'center', padding: 24 }}>
                No cost data found. Run a scan first to populate ChromaDB.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  )
}

// ---------------------------------------------------------------------------
// User detail table
// ---------------------------------------------------------------------------

function UserDetailTable({
  summary,
  onBack,
}: {
  summary: UserCostSummaryResponse
  onBack: () => void
}) {
  return (
    <div style={card}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16 }}>
        <button
          style={{ background: 'none', border: '1px solid #ced4da', borderRadius: 5, padding: '5px 12px', cursor: 'pointer', fontSize: 13 }}
          onClick={onBack}
        >
          ← Back
        </button>
        <h2 style={{ margin: 0, fontSize: 16 }}>
          Resources owned by <span style={{ color: '#1f77b4' }}>{summary.owner_email}</span>
        </h2>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 12, marginBottom: 20 }}>
        <SummaryKpi label="Total Cost" value={`$${summary.total_usd.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`} borderColor="#1f77b4" />
        <SummaryKpi label="Resources" value={String(summary.resource_count)} borderColor="#4caf50" />
        <SummaryKpi label="Project" value={summary.project_id} borderColor="#9c27b0" />
      </div>

      <table style={tableStyle}>
        <thead>
          <tr>
            <th style={thStyle}>Resource ID</th>
            <th style={thStyle}>Type</th>
            <th style={{ ...thStyle, textAlign: 'right' }}>Monthly Cost</th>
          </tr>
        </thead>
        <tbody>
          {summary.resources.map((r) => (
            <tr key={r.resource_id}>
              <td style={{ ...tdStyle, fontFamily: 'monospace', fontSize: 12 }}>{r.resource_id ?? '—'}</td>
              <td style={tdStyle}>{r.resource_type ?? '—'}</td>
              <td style={{ ...tdStyle, textAlign: 'right', fontWeight: 600 }}>
                {r.cost_usd === 0 ? '—' : `$${r.cost_usd.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`}
              </td>
            </tr>
          ))}
          {summary.resources.length === 0 && (
            <tr>
              <td colSpan={3} style={{ ...tdStyle, color: '#6c757d', textAlign: 'center', padding: 24 }}>
                No resources found for this owner.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Tabs
// ---------------------------------------------------------------------------

type CostTab = 'owners' | 'resources'

// ---------------------------------------------------------------------------
// Main CostCenter component
// ---------------------------------------------------------------------------

export function CostCenter({ initialProjectId }: { initialProjectId?: string }) {
  const [projectId, setProjectId] = useState(initialProjectId ?? '')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [projectSummary, setProjectSummary] = useState<ProjectCostSummaryResponse | null>(null)
  const [userSummary, setUserSummary] = useState<UserCostSummaryResponse | null>(null)
  const [userLoading, setUserLoading] = useState(false)
  const [activeTab, setActiveTab] = useState<CostTab>('resources')
  const [pendingAction, setPendingAction] = useState<ProjectResourceRecord | null>(null)
  const [actionResults, setActionResults] = useState<Record<string, ExecuteResourceResponse>>({})
  const [recentProjects, setRecentProjects] = useState<string[]>([])

  // Auto-load recent project list from ChromaDB on mount
  useEffect(() => {
    getRecentProjects()
      .then(ids => {
        setRecentProjects(ids)
        // If no project is pre-selected and ChromaDB has history, auto-load the first one
        if (!initialProjectId && ids.length > 0) {
          setProjectId(ids[0])
          handleLoadProject(ids[0])
        }
      })
      .catch(() => { /* silently ignore */ })
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  async function handleLoadProject(pid: string) {
    if (!pid.trim()) return
    setLoading(true)
    setError(null)
    setProjectSummary(null)
    setUserSummary(null)
    try {
      const data = await getProjectCostSummary(pid.trim())
      setProjectSummary(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load cost data')
    } finally {
      setLoading(false)
    }
  }

  async function handleLoad() {
    if (!projectId.trim()) return
    setLoading(true)
    setError(null)
    setProjectSummary(null)
    setUserSummary(null)
    setActionResults({})
    try {
      const data = await getProjectCostSummary(projectId.trim())
      setProjectSummary(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load cost data')
    } finally {
      setLoading(false)
    }
  }

  async function handleDrillDown(ownerEmail: string) {
    if (!projectSummary) return
    setUserLoading(true)
    setError(null)
    try {
      const data = await getUserCostSummary(ownerEmail, projectSummary.project_id)
      setUserSummary(data)
      setActiveTab('owners')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load user cost data')
    } finally {
      setUserLoading(false)
    }
  }

  function handleActionDone(result: ExecuteResourceResponse) {
    setActionResults(prev => ({ ...prev, [result.resource_id]: result }))
  }

  const tabStyle = (t: CostTab): React.CSSProperties => ({
    padding: '8px 20px',
    fontSize: 14,
    fontWeight: activeTab === t ? 700 : 400,
    cursor: 'pointer',
    border: 'none',
    borderBottom: activeTab === t ? '2px solid #1f77b4' : '2px solid transparent',
    background: 'none',
    color: activeTab === t ? '#1f77b4' : '#495057',
  })

  return (
    <div>
      <h1 style={{ margin: '0 0 4px', fontSize: 24, fontWeight: 700 }}>Cost Attribution</h1>
      <p style={{ margin: '0 0 20px', color: '#6c757d', fontSize: 14 }}>
        Per-resource and per-owner cost breakdown from ChromaDB. Approve actions directly from the resource table.
      </p>

      {/* Query form */}
      <div style={card}>
        {recentProjects.length > 0 && (
          <div style={{ marginBottom: 10, display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ fontSize: 12, color: '#6c757d', fontWeight: 600 }}>HISTORY:</span>
            {recentProjects.map(pid => (
              <button
                key={pid}
                style={{
                  background: projectId === pid ? '#1f77b4' : '#e9ecef',
                  color: projectId === pid ? '#fff' : '#495057',
                  border: 'none', borderRadius: 12, padding: '3px 10px',
                  fontSize: 12, cursor: 'pointer', fontWeight: 500,
                }}
                onClick={() => { setProjectId(pid); handleLoadProject(pid) }}
              >
                {pid}
              </button>
            ))}
          </div>
        )}
        <div style={{ display: 'flex', alignItems: 'center', gap: 0 }}>
          <input
            style={inputStyle}
            type="text"
            value={projectId}
            onChange={e => setProjectId(e.target.value)}
            placeholder="nexus-tech-dev-sandbox"
            onKeyDown={e => e.key === 'Enter' && handleLoad()}
          />
          <button
            style={{ ...primaryBtn, opacity: !projectId.trim() || loading ? 0.6 : 1, cursor: !projectId.trim() || loading ? 'not-allowed' : 'pointer' }}
            onClick={handleLoad}
            disabled={!projectId.trim() || loading}
          >
            {loading ? 'Loading…' : 'Load Cost Data'}
          </button>
        </div>
      </div>

      {/* Error */}
      {error && (
        <div style={{ background: '#ffebee', border: '1px solid #ef9a9a', borderRadius: 4, padding: '10px 14px', marginBottom: 16, fontSize: 13, color: '#c62828' }}>
          {error}
        </div>
      )}

      {/* Tabs */}
      {projectSummary && (
        <div style={{ display: 'flex', borderBottom: '1px solid #dee2e6', marginBottom: 16 }}>
          <button style={tabStyle('resources')} onClick={() => { setActiveTab('resources'); setUserSummary(null) }}>
            Resources ({projectSummary.resources.length})
          </button>
          <button style={tabStyle('owners')} onClick={() => setActiveTab('owners')}>
            Owner Breakdown
          </button>
        </div>
      )}

      {/* Resources tab */}
      {projectSummary && activeTab === 'resources' && !userSummary && (
        <ResourcesTable
          summary={projectSummary}
          onAction={r => setPendingAction(r)}
          actionResults={actionResults}
        />
      )}

      {/* Owner tab */}
      {projectSummary && activeTab === 'owners' && !userSummary && !userLoading && (
        <ProjectBreakdownTable summary={projectSummary} onDrillDown={handleDrillDown} />
      )}

      {/* User drill-down */}
      {userSummary && !userLoading && (
        <UserDetailTable summary={userSummary} onBack={() => setUserSummary(null)} />
      )}

      {/* User loading */}
      {userLoading && (
        <div style={{ ...card, display: 'flex', alignItems: 'center', gap: 10, color: '#1f77b4' }}>
          <div style={{ width: 16, height: 16, border: '2px solid #1f77b4', borderTopColor: 'transparent', borderRadius: '50%', animation: 'spin 0.9s linear infinite' }} />
          Loading user data…
        </div>
      )}

      {/* Empty state */}
      {!projectSummary && !loading && !error && (
        <div style={{ ...card, color: '#6c757d', fontSize: 14, textAlign: 'center', padding: 32 }}>
          Enter a project ID and click Load Cost Data to see all resources and owner-attributed cost breakdown.
        </div>
      )}

      {/* Action confirm modal */}
      {pendingAction && projectSummary && (
        <ActionModal
          resource={pendingAction}
          projectId={projectSummary.project_id}
          onClose={() => setPendingAction(null)}
          onDone={(result) => {
            handleActionDone(result)
            setPendingAction(null)
          }}
        />
      )}
    </div>
  )
}
