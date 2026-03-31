import { useState, useEffect, useRef, useCallback } from 'react'
import { ApprovalTable } from './components/ApprovalTable'
import { ExecutePanel } from './components/ExecutePanel'
import { IamPanel } from './components/IamPanel'
import type { ResourceRow, RevalidationStatus, NavSection, IamTicket, SecurityAlert, IamPlan } from './types'
import { MOCK_IDENTITY_DATA } from './types'
import {
  startRun,
  pollPlan,
  approvePlan,
  getStatus,
  getTickets,
  reviewTicket,
  type ResourceRecord,
  type IamTicketResponse,
} from './api'

// ---------------------------------------------------------------------------
// Phase state machine (Cost Center)
// ---------------------------------------------------------------------------

type Phase =
  | 'start'
  | 'scanning'
  | 'awaiting_approval'
  | 'executing'
  | 'complete'
  | 'error'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function toResourceRow(r: ResourceRecord): ResourceRow {
  return {
    resource_id: r.resource_id,
    resource_type: r.resource_type,
    region: r.region,
    owner_email: r.owner_email,
    ownership_status: r.ownership_status,
    decision: r.decision,
    reasoning: r.reasoning,
    estimated_monthly_savings: r.estimated_monthly_savings,
    outcome: r.outcome ?? null,
  }
}

function fmt(n: number) {
  return `$${n.toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`
}

function toIamTicket(r: IamTicketResponse): IamTicket {
  return { id: r.id, ts: r.ts, plan: r.plan as unknown as IamPlan, status: r.status }
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const PIPELINE_STEPS = [
  { id: 'scan',    label: 'Scan',    icon: '🔍', phases: ['scanning', 'awaiting_approval', 'executing', 'complete'] },
  { id: 'enrich',  label: 'Enrich',  icon: '🏷️',  phases: ['awaiting_approval', 'executing', 'complete'] },
  { id: 'reason',  label: 'Reason',  icon: '🧠', phases: ['awaiting_approval', 'executing', 'complete'] },
  { id: 'approve', label: 'Approve', icon: '✅', phases: ['executing', 'complete'] },
  { id: 'execute', label: 'Execute', icon: '⚡', phases: ['complete'] },
  { id: 'audit',   label: 'Audit',   icon: '📋', phases: ['complete'] },
]

const QUICK_PRESETS = [
  { label: '🔍 Sandbox',  value: 'nexus-tech-dev-sandbox' },
  { label: '🧪 Dev 1',    value: 'nexus-tech-dev-1' },
  { label: '🧪 Dev 2',    value: 'nexus-tech-dev-2' },
  { label: '🧪 Dev 3',    value: 'nexus-tech-dev-3' },
]

const PHASE_LABELS: Record<Phase, string> = {
  start:             'Ready',
  scanning:          'Scanning…',
  awaiting_approval: 'Awaiting Approval',
  executing:         'Executing…',
  complete:          'Complete',
  error:             'Error',
}

const PHASE_COLORS: Record<Phase, [string, string]> = {
  start:             ['#495057', '#e9ecef'],
  scanning:          ['#004085', '#cce5ff'],
  awaiting_approval: ['#856404', '#fff3cd'],
  executing:         ['#0c4a6e', '#bae6fd'],
  complete:          ['#155724', '#d4edda'],
  error:             ['#721c24', '#f8d7da'],
}

const DECISION_CARD: Record<string, { border: string; bg: string; color: string; label: string }> = {
  safe_to_stop:   { border: '#ff9800', bg: '#fff3e0', color: '#e65100', label: 'Safe to Stop' },
  safe_to_delete: { border: '#f44336', bg: '#ffebee', color: '#b71c1c', label: 'Safe to Delete' },
  needs_review:   { border: '#9e9e9e', bg: '#f5f5f5', color: '#424242', label: 'Needs Review' },
  skip:           { border: '#1f77b4', bg: '#e3f2fd', color: '#0d47a1', label: 'Skip' },
}

const NAV_ITEMS: { section: NavSection; icon: string; label: string }[] = [
  { section: 'dashboard', icon: '📊', label: 'Dashboard' },
  { section: 'iam',       icon: '🛡️',  label: 'IAM Center' },
  { section: 'cost',      icon: '💰', label: 'Cost Center' },
  { section: 'security',  icon: '🔒', label: 'Security Hub' },
  { section: 'tickets',   icon: '🎫', label: 'Tickets' },
]

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function Stat({ label, value }: { label: string; value: string | number | undefined }) {
  return (
    <div style={{ minWidth: 90 }}>
      <div style={{ fontSize: 11, color: '#6c757d', textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 2 }}>
        {label}
      </div>
      <div style={{ fontSize: 22, fontWeight: 700, color: '#212529' }}>{value ?? '—'}</div>
    </div>
  )
}

function MetricCard({
  label, value, sub, borderColor,
}: { label: string; value: string | number; sub?: string; borderColor: string }) {
  return (
    <div style={{
      background: '#fff', border: '1px solid #dee2e6', borderLeft: `4px solid ${borderColor}`,
      borderRadius: 6, padding: '12px 16px', marginBottom: 10,
    }}>
      <div style={{ fontSize: 12, color: '#6c757d', marginBottom: 4 }}>{label}</div>
      <div style={{ fontSize: 20, fontWeight: 700 }}>{value}</div>
      {sub && <div style={{ fontSize: 12, color: '#6c757d', marginTop: 2 }}>{sub}</div>}
    </div>
  )
}

function PipelineStep({ icon, label, done, active }: { icon: string; label: string; done: boolean; active: boolean }) {
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 10, padding: '7px 12px', borderRadius: 6,
      background: active ? '#e3f2fd' : done ? '#f1f8f1' : 'transparent', marginBottom: 2,
    }}>
      <span style={{ fontSize: 15 }}>{icon}</span>
      <span style={{ fontSize: 13, fontWeight: active ? 700 : 500, color: active ? '#1f77b4' : done ? '#2e7d32' : '#9e9e9e', flex: 1 }}>
        {label}
      </span>
      {done && !active && <span style={{ fontSize: 12, color: '#2e7d32' }}>✓</span>}
      {active && <span style={{ width: 8, height: 8, borderRadius: '50%', background: '#1f77b4', animation: 'blink 1s step-end infinite' }} />}
    </div>
  )
}

function NavItem({
  icon, label, active, onClick, badge,
}: { icon: string; label: string; active: boolean; onClick: () => void; badge?: number }) {
  return (
    <button
      onClick={onClick}
      style={{
        width: '100%', textAlign: 'left', display: 'flex', alignItems: 'center', gap: 10,
        padding: '10px 16px', border: 'none', background: active ? '#e3f2fd' : 'transparent',
        borderLeft: `3px solid ${active ? '#1f77b4' : 'transparent'}`,
        color: active ? '#1f77b4' : '#495057', cursor: 'pointer', fontSize: 14,
        fontWeight: active ? 700 : 400, marginBottom: 2, borderRadius: '0 6px 6px 0',
        transition: 'background 0.15s',
      }}
    >
      <span style={{ fontSize: 16 }}>{icon}</span>
      <span style={{ flex: 1 }}>{label}</span>
      {badge != null && badge > 0 && (
        <span style={{ background: '#f44336', color: '#fff', borderRadius: 10, padding: '1px 7px', fontSize: 11, fontWeight: 700 }}>
          {badge}
        </span>
      )}
    </button>
  )
}

function StatusBadge({ status }: { status: 'pending' | 'approved' | 'rejected' }) {
  const map = {
    pending:  { bg: '#fff3cd', color: '#856404', label: 'Pending' },
    approved: { bg: '#d4edda', color: '#155724', label: 'Approved' },
    rejected: { bg: '#f8d7da', color: '#721c24', label: 'Rejected' },
  }
  const s = map[status]
  return (
    <span style={{ padding: '3px 10px', borderRadius: 10, fontSize: 12, fontWeight: 600, background: s.bg, color: s.color }}>
      {s.label}
    </span>
  )
}

// ---------------------------------------------------------------------------
// Dashboard view
// ---------------------------------------------------------------------------

function DashboardView({
  resources, tickets, totalWaste, onNav,
}: {
  resources: ResourceRow[]
  tickets: IamTicket[]
  totalWaste: number
  onNav: (s: NavSection) => void
}) {
  const activeIds   = MOCK_IDENTITY_DATA.filter(i => i.status === 'active').length
  const staleIds    = MOCK_IDENTITY_DATA.filter(i => i.status === 'stale').length
  const departedIds = MOCK_IDENTITY_DATA.filter(i => i.status === 'departed').length
  const pendingTix  = tickets.filter(t => t.status === 'pending').length
  const overPerm    = MOCK_IDENTITY_DATA.filter(i =>
    i.status !== 'active' && (i.role.includes('owner') || i.role.includes('editor'))
  ).length

  // Health score: start 100, penalise issues
  const score = Math.max(0, 100 - staleIds * 5 - departedIds * 15 - overPerm * 10 - (resources.length > 0 ? 5 : 0))
  const scoreColor = score >= 80 ? '#2e7d32' : score >= 60 ? '#e65100' : '#c62828'

  return (
    <div>
      <h1 style={{ margin: '0 0 4px', fontSize: 24, fontWeight: 700 }}>Command Center</h1>
      <p style={{ margin: '0 0 24px', color: '#6c757d', fontSize: 14 }}>
        GCP dev environment health — nexus-tech-dev-sandbox
      </p>

      {/* Health + quick stats */}
      <div style={{ display: 'grid', gridTemplateColumns: '180px 1fr', gap: 16, marginBottom: 20 }}>
        {/* Health score */}
        <div style={{ ...mainCard, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: '24px 16px' }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: '#9e9e9e', letterSpacing: 1, marginBottom: 8 }}>HEALTH SCORE</div>
          <div style={{ fontSize: 52, fontWeight: 800, color: scoreColor, lineHeight: 1 }}>{score}</div>
          <div style={{ fontSize: 12, color: scoreColor, marginTop: 4, fontWeight: 600 }}>
            {score >= 80 ? 'Good' : score >= 60 ? 'Fair' : 'Critical'}
          </div>
        </div>

        {/* KPI grid */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12 }}>
          {[
            { label: 'Active Identities', value: activeIds, sub: `${staleIds} stale · ${departedIds} departed`, border: '#4caf50' },
            { label: 'Over-Permissioned', value: overPerm, sub: 'owner/editor + stale', border: '#ff9800' },
            { label: 'Monthly Waste', value: resources.length > 0 ? `${fmt(totalWaste)}/mo` : '—', sub: resources.length > 0 ? `${resources.length} resources` : 'Run a scan to populate', border: '#f44336' },
            { label: 'Pending Tickets', value: pendingTix, sub: 'IAM access requests', border: '#9c27b0' },
            { label: 'Total Identities', value: MOCK_IDENTITY_DATA.length, sub: 'users + service accounts', border: '#1f77b4' },
            { label: 'Last Scan', value: resources.length > 0 ? 'Today' : 'Never', sub: resources.length > 0 ? `${resources.length} resources found` : 'Go to Cost Center', border: '#607d8b' },
          ].map(c => (
            <div key={c.label} style={{ ...mainCard, marginBottom: 0, borderLeft: `4px solid ${c.border}`, padding: '14px 16px' }}>
              <div style={{ fontSize: 11, color: '#6c757d', marginBottom: 4 }}>{c.label}</div>
              <div style={{ fontSize: 22, fontWeight: 700 }}>{c.value}</div>
              <div style={{ fontSize: 11, color: '#9e9e9e', marginTop: 2 }}>{c.sub}</div>
            </div>
          ))}
        </div>
      </div>

      {/* Quick actions */}
      <div style={{ ...mainCard, display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'center' }}>
        <span style={{ fontWeight: 700, fontSize: 14, marginRight: 4 }}>Quick Actions</span>
        {[
          { label: '🔍 Start Scan', section: 'cost' as NavSection, color: '#1f77b4' },
          { label: '🛡️ Request IAM Access', section: 'iam' as NavSection, color: '#7b1fa2' },
          { label: '🔒 View Security Alerts', section: 'security' as NavSection, color: '#e65100' },
          { label: '🎫 Review Tickets', section: 'tickets' as NavSection, color: '#2e7d32' },
        ].map(a => (
          <button key={a.label} onClick={() => onNav(a.section)} style={{
            padding: '8px 16px', borderRadius: 6, border: `1px solid ${a.color}`,
            background: '#fff', color: a.color, fontWeight: 600, fontSize: 13, cursor: 'pointer',
          }}>
            {a.label}
          </button>
        ))}
      </div>

      {/* Recent activity */}
      <div style={mainCard}>
        <div style={{ fontWeight: 700, fontSize: 14, marginBottom: 14 }}>Recent Activity</div>
        {[
          { ts: '2026-03-31 09:14', icon: '🔍', text: 'Cerberus scan completed — nexus-tech-dev-sandbox', tag: 'Scan', tagColor: '#1f77b4' },
          { ts: '2026-03-30 16:45', icon: '🛡️', text: 'IAM plan synthesized for alice.chen@nexus-tech.com', tag: 'IAM', tagColor: '#7b1fa2' },
          { ts: '2026-03-29 11:02', icon: '⚠️', text: 'bob.wilson@nexus-tech.com flagged — owner role, 136 days inactive', tag: 'Security', tagColor: '#e65100' },
          { ts: '2026-03-28 08:30', icon: '✅', text: '3 idle VMs stopped (dry-run)', tag: 'Execute', tagColor: '#4caf50' },
        ].map((a, i) => (
          <div key={i} style={{
            display: 'flex', gap: 12, alignItems: 'flex-start', padding: '10px 0',
            borderBottom: i < 3 ? '1px solid #f0f0f0' : 'none',
          }}>
            <span style={{ fontSize: 18, marginTop: 1 }}>{a.icon}</span>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 13 }}>{a.text}</div>
              <div style={{ fontSize: 11, color: '#9e9e9e', marginTop: 2 }}>{a.ts}</div>
            </div>
            <span style={{ padding: '2px 8px', borderRadius: 8, fontSize: 11, fontWeight: 600, background: '#f0f4ff', color: a.tagColor }}>
              {a.tag}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Security Hub view
// ---------------------------------------------------------------------------

function SecurityHubView({ resources }: { resources: ResourceRow[] }) {
  const overPerm: SecurityAlert[] = MOCK_IDENTITY_DATA
    .filter(i => i.status !== 'active' && (i.role.includes('owner') || i.role.includes('editor')))
    .map(i => ({
      id: `overperm-${i.email}`,
      type: 'over_permission' as const,
      severity: i.status === 'departed' ? 'high' as const : 'medium' as const,
      message: `${i.role} role held by ${i.status} user (${i.days_inactive}d inactive)`,
      resource: i.email,
      ts: i.last_activity ?? '—',
    }))

  const ghosts: SecurityAlert[] = resources
    .filter(r => r.decision === 'safe_to_stop' || r.resource_type === 'orphaned_disk')
    .map(r => ({
      id: `ghost-${r.resource_id}`,
      type: 'idle_resource' as const,
      severity: 'low' as const,
      message: `${r.resource_type} idle — estimated waste ${r.estimated_monthly_savings != null ? fmt(r.estimated_monthly_savings) + '/mo' : 'unknown'}`,
      resource: r.resource_id,
      ts: '—',
    }))

  const allAlerts = [...overPerm, ...ghosts]
  const high   = allAlerts.filter(a => a.severity === 'high').length
  const medium = allAlerts.filter(a => a.severity === 'medium').length
  const low    = allAlerts.filter(a => a.severity === 'low').length

  const SEVER: Record<string, { bg: string; color: string; border: string }> = {
    high:   { bg: '#ffebee', color: '#c62828', border: '#f44336' },
    medium: { bg: '#fff3e0', color: '#e65100', border: '#ff9800' },
    low:    { bg: '#f3e5f5', color: '#7b1fa2', border: '#ce93d8' },
  }

  const TYPE_ICON: Record<string, string> = {
    over_permission:  '🔑',
    idle_resource:    '💤',
    budget_breach:    '💸',
    departed_owner:   '👻',
  }

  return (
    <div>
      <h1 style={{ margin: '0 0 4px', fontSize: 24, fontWeight: 700 }}>Security Hub</h1>
      <p style={{ margin: '0 0 20px', color: '#6c757d', fontSize: 14 }}>
        Monitors over-permissioning, ghost resources, and budget breaches.
      </p>

      {/* Alert summary */}
      <div style={{ display: 'flex', gap: 12, marginBottom: 20 }}>
        {[
          { label: 'High', count: high,   bg: '#ffebee', color: '#c62828' },
          { label: 'Medium', count: medium, bg: '#fff3e0', color: '#e65100' },
          { label: 'Low',  count: low,    bg: '#f3e5f5', color: '#7b1fa2' },
          { label: 'Total', count: allAlerts.length, bg: '#e3f2fd', color: '#1f77b4' },
        ].map(s => (
          <div key={s.label} style={{ ...mainCard, marginBottom: 0, flex: 1, padding: '14px 16px', background: s.bg, border: `1px solid ${s.color}22` }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: s.color, letterSpacing: 0.5 }}>{s.label.toUpperCase()}</div>
            <div style={{ fontSize: 28, fontWeight: 800, color: s.color, lineHeight: 1.2 }}>{s.count}</div>
          </div>
        ))}
      </div>

      {/* Over-permissioning */}
      <div style={mainCard}>
        <div style={{ fontWeight: 700, fontSize: 14, marginBottom: 14, display: 'flex', alignItems: 'center', gap: 8 }}>
          🔑 Over-Permissioning Violations
          <span style={{ background: '#ffebee', color: '#c62828', borderRadius: 10, padding: '1px 8px', fontSize: 12, fontWeight: 700 }}>
            {overPerm.length}
          </span>
        </div>
        {overPerm.length === 0 ? (
          <div style={{ color: '#6c757d', fontSize: 13 }}>No over-permissioning detected.</div>
        ) : (
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead>
              <tr style={{ background: '#f8f9fa' }}>
                {['Severity', 'Identity', 'Role', 'Status', 'Inactive', 'Last Activity'].map(h => (
                  <th key={h} style={{ textAlign: 'left', padding: '8px 10px', fontSize: 11, fontWeight: 700, color: '#6c757d', borderBottom: '1px solid #dee2e6' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {MOCK_IDENTITY_DATA.filter(i => i.status !== 'active' && (i.role.includes('owner') || i.role.includes('editor'))).map(i => {
                const sev = i.status === 'departed' ? 'high' : 'medium'
                const s = SEVER[sev]
                return (
                  <tr key={i.email} style={{ borderBottom: '1px solid #f0f0f0' }}>
                    <td style={{ padding: '9px 10px' }}>
                      <span style={{ ...s, padding: '2px 8px', borderRadius: 8, fontSize: 11, fontWeight: 700 }}>{sev}</span>
                    </td>
                    <td style={{ padding: '9px 10px', fontFamily: 'monospace', fontSize: 12 }}>{i.email}</td>
                    <td style={{ padding: '9px 10px', fontFamily: 'monospace', fontSize: 12, color: '#e65100' }}>{i.role}</td>
                    <td style={{ padding: '9px 10px' }}>
                      <span style={{ background: i.status === 'departed' ? '#ffebee' : '#fff3e0', color: i.status === 'departed' ? '#c62828' : '#e65100', borderRadius: 8, padding: '2px 8px', fontSize: 11, fontWeight: 600 }}>
                        {i.status}
                      </span>
                    </td>
                    <td style={{ padding: '9px 10px', fontWeight: 700, color: (i.days_inactive ?? 0) > 90 ? '#c62828' : '#e65100' }}>{i.days_inactive}d</td>
                    <td style={{ padding: '9px 10px', color: '#6c757d' }}>{i.last_activity ?? '—'}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </div>

      {/* Ghost resources */}
      <div style={mainCard}>
        <div style={{ fontWeight: 700, fontSize: 14, marginBottom: 14, display: 'flex', alignItems: 'center', gap: 8 }}>
          💤 Ghost Resources (Idle / Orphaned)
          <span style={{ background: '#f3e5f5', color: '#7b1fa2', borderRadius: 10, padding: '1px 8px', fontSize: 12, fontWeight: 700 }}>
            {ghosts.length}
          </span>
        </div>
        {ghosts.length === 0 ? (
          <div style={{ color: '#6c757d', fontSize: 13 }}>
            {resources.length === 0 ? 'Run a Cost Center scan first to detect ghost resources.' : 'No ghost resources detected.'}
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {ghosts.map(g => (
              <div key={g.id} style={{ display: 'flex', gap: 12, alignItems: 'center', padding: '10px 14px', background: '#f9f0ff', borderRadius: 6, border: '1px solid #e1bee7' }}>
                <span style={{ fontSize: 18 }}>{TYPE_ICON[g.type]}</span>
                <div style={{ flex: 1 }}>
                  <code style={{ fontSize: 12, color: '#424242' }}>{g.resource}</code>
                  <div style={{ fontSize: 12, color: '#6c757d', marginTop: 2 }}>{g.message}</div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Budget alerts (static thresholds) */}
      <div style={mainCard}>
        <div style={{ fontWeight: 700, fontSize: 14, marginBottom: 14 }}>💸 Budget Thresholds</div>
        {[
          { project: 'nexus-tech-dev-sandbox', budget: 500, current: resources.length > 0 ? resources.reduce((s, r) => s + (r.estimated_monthly_savings ?? 0), 0) : 0 },
          { project: 'nexus-tech-dev-1', budget: 200, current: 142 },
          { project: 'nexus-tech-dev-2', budget: 200, current: 67 },
        ].map(b => {
          const pct = Math.min(100, Math.round((b.current / b.budget) * 100))
          const color = pct >= 90 ? '#c62828' : pct >= 70 ? '#e65100' : '#2e7d32'
          return (
            <div key={b.project} style={{ marginBottom: 14 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, marginBottom: 4 }}>
                <span style={{ fontFamily: 'monospace' }}>{b.project}</span>
                <span style={{ fontWeight: 600, color }}>{fmt(b.current)} / {fmt(b.budget)} ({pct}%)</span>
              </div>
              <div style={{ height: 8, background: '#e9ecef', borderRadius: 4, overflow: 'hidden' }}>
                <div style={{ height: '100%', width: `${pct}%`, background: color, borderRadius: 4, transition: 'width 0.5s' }} />
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Tickets view
// ---------------------------------------------------------------------------

function TicketsView({ tickets, onRefresh }: { tickets: IamTicket[]; onRefresh: () => void }) {
  const [reviewing, setReviewing] = useState<string | null>(null)
  const [error, setError]         = useState<string | null>(null)

  async function handleReview(id: string, action: 'approved' | 'rejected') {
    setReviewing(id); setError(null)
    try {
      await reviewTicket(id, action)
      await onRefresh()
    } catch (e) {
      setError(String(e))
    } finally {
      setReviewing(null)
    }
  }

  const pending  = tickets.filter(t => t.status === 'pending').length
  const approved = tickets.filter(t => t.status === 'approved').length
  const rejected = tickets.filter(t => t.status === 'rejected').length

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 4 }}>
        <h1 style={{ margin: 0, fontSize: 24, fontWeight: 700 }}>IAM Ticket Queue</h1>
        <button onClick={onRefresh} style={{ ...secondaryBtn, fontSize: 13, padding: '6px 14px' }}>↻ Refresh</button>
      </div>
      <p style={{ margin: '0 0 20px', color: '#6c757d', fontSize: 14 }}>
        Admin review of synthesized least-privilege IAM provisioning plans.
      </p>

      {/* Summary chips */}
      <div style={{ display: 'flex', gap: 10, marginBottom: 20 }}>
        {[
          { label: 'Pending',  count: pending,  bg: '#fff3cd', color: '#856404' },
          { label: 'Approved', count: approved, bg: '#d4edda', color: '#155724' },
          { label: 'Rejected', count: rejected, bg: '#f8d7da', color: '#721c24' },
        ].map(s => (
          <div key={s.label} style={{ padding: '8px 18px', borderRadius: 8, background: s.bg, color: s.color, fontWeight: 700, fontSize: 14 }}>
            {s.label}: {s.count}
          </div>
        ))}
      </div>

      {error && (
        <div style={{ ...errBox, marginBottom: 16 }}>{error}</div>
      )}

      {tickets.length === 0 ? (
        <div style={{ ...mainCard, textAlign: 'center', padding: 40, color: '#6c757d' }}>
          <div style={{ fontSize: 32, marginBottom: 12 }}>🎫</div>
          <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 8 }}>No tickets yet</div>
          <div style={{ fontSize: 13 }}>IAM access requests submitted from the IAM Center will appear here.</div>
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          {[...tickets].sort((a, b) => (b.ts > a.ts ? 1 : -1)).map(t => (
            <div key={t.id} style={{ ...mainCard, marginBottom: 0, borderLeft: `4px solid ${t.status === 'pending' ? '#ff9800' : t.status === 'approved' ? '#4caf50' : '#f44336'}` }}>
              <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 12 }}>
                <div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 4 }}>
                    <code style={{ fontSize: 12, background: '#f8f9fa', padding: '2px 6px', borderRadius: 4 }}>{t.id.slice(0, 12)}…</code>
                    <StatusBadge status={t.status} />
                  </div>
                  <div style={{ fontSize: 13, color: '#6c757d' }}>{new Date(t.ts).toLocaleString()}</div>
                </div>
                {t.status === 'pending' && (
                  <div style={{ display: 'flex', gap: 8 }}>
                    <button
                      onClick={() => handleReview(t.id, 'approved')}
                      disabled={reviewing === t.id}
                      style={{ ...primaryBtn, padding: '7px 16px', fontSize: 13, opacity: reviewing === t.id ? 0.6 : 1 }}
                    >
                      Approve
                    </button>
                    <button
                      onClick={() => handleReview(t.id, 'rejected')}
                      disabled={reviewing === t.id}
                      style={{ background: '#dc3545', color: '#fff', border: 'none', borderRadius: 6, padding: '7px 16px', fontSize: 13, fontWeight: 600, cursor: 'pointer', opacity: reviewing === t.id ? 0.6 : 1 }}
                    >
                      Reject
                    </button>
                  </div>
                )}
              </div>

              {/* Plan summary */}
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12, fontSize: 13 }}>
                <div>
                  <div style={{ fontSize: 11, fontWeight: 700, color: '#9e9e9e', marginBottom: 3 }}>REQUESTER</div>
                  <div style={{ fontFamily: 'monospace', fontSize: 12 }}>{t.plan.requester_email}</div>
                </div>
                <div>
                  <div style={{ fontSize: 11, fontWeight: 700, color: '#9e9e9e', marginBottom: 3 }}>CUSTOM ROLE</div>
                  <div style={{ fontFamily: 'monospace', fontSize: 12, color: '#7b1fa2' }}>{t.plan.custom_role_id}</div>
                </div>
                <div>
                  <div style={{ fontSize: 11, fontWeight: 700, color: '#9e9e9e', marginBottom: 3 }}>REVIEW AFTER</div>
                  <div>{t.plan.review_after_days} days</div>
                </div>
              </div>

              <div style={{ marginTop: 12 }}>
                <div style={{ fontSize: 11, fontWeight: 700, color: '#9e9e9e', marginBottom: 6 }}>PERMISSIONS ({t.plan.permissions.length})</div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                  {t.plan.permissions.slice(0, 8).map(p => (
                    <span key={p} style={{ background: '#e3f2fd', color: '#1565c0', borderRadius: 4, padding: '2px 8px', fontSize: 11, fontFamily: 'monospace' }}>{p}</span>
                  ))}
                  {t.plan.permissions.length > 8 && (
                    <span style={{ background: '#f5f5f5', color: '#616161', borderRadius: 4, padding: '2px 8px', fontSize: 11 }}>+{t.plan.permissions.length - 8} more</span>
                  )}
                </div>
              </div>

              {t.plan.reasoning && (
                <div style={{ marginTop: 12, padding: '8px 12px', background: '#f8f9fa', borderRadius: 6, fontSize: 12, color: '#495057', fontStyle: 'italic' }}>
                  {t.plan.reasoning}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function App() {
  // ── Navigation ──────────────────────────────────────────────────────────────
  const [navSection, setNavSection] = useState<NavSection>('dashboard')

  // ── Cost Center: scan phase state ───────────────────────────────────────────
  const [phase, setPhase]                           = useState<Phase>('start')
  const [projectId, setProjectId]                   = useState('')
  const [dryRun, setDryRun]                         = useState(true)
  const [runId, setRunId]                           = useState<string | null>(null)
  const [resources, setResources]                   = useState<ResourceRow[]>([])
  const [approvedIds, setApprovedIds]               = useState<Set<string>>(new Set())
  const [revalidationStatus, setRevalidationStatus] = useState<RevalidationStatus>('idle')
  const [langsmithTraceUrl, setLangsmithTraceUrl]   = useState<string | null>(null)
  const [errorMessage, setErrorMessage]             = useState<string | null>(null)
  const [mutationCount, setMutationCount]           = useState(0)
  const [statusMessage, setStatusMessage]           = useState('')

  // ── Tickets ─────────────────────────────────────────────────────────────────
  const [tickets, setTickets] = useState<IamTicket[]>([])

  const pollTimer = useRef<ReturnType<typeof setInterval> | null>(null)

  // ── Load tickets on mount ───────────────────────────────────────────────────
  const loadTickets = useCallback(async () => {
    try {
      const data = await getTickets()
      setTickets(data.map(toIamTicket))
    } catch {
      // silently ignore — tickets section will show empty state
    }
  }, [])

  useEffect(() => { loadTickets() }, [loadTickets])

  // ── Polling ─────────────────────────────────────────────────────────────────

  const stopPolling = useCallback(() => {
    if (pollTimer.current) { clearInterval(pollTimer.current); pollTimer.current = null }
  }, [])

  const pollForPlan = useCallback((id: string) => {
    pollTimer.current = setInterval(async () => {
      try {
        const data = await pollPlan(id)
        if (data.status === 'awaiting_approval' && data.plan) {
          stopPolling()
          setResources(data.plan.map(toResourceRow))
          setPhase('awaiting_approval')
          setStatusMessage(`${data.plan.length} resource(s) ready for review`)
        } else if (data.status === 'complete') {
          stopPolling()
          const status = await getStatus(id)
          setResources(status.resources.map(toResourceRow))
          setLangsmithTraceUrl(status.langsmith_trace_url)
          setMutationCount(status.mutation_count)
          setPhase('complete')
        } else if (data.status === 'error') {
          stopPolling()
          setErrorMessage('Scan failed. Check backend logs.')
          setPhase('error')
        }
      } catch (err) { stopPolling(); setErrorMessage(String(err)); setPhase('error') }
    }, 2000)
  }, [stopPolling])

  const pollForCompletion = useCallback((id: string) => {
    pollTimer.current = setInterval(async () => {
      try {
        const status = await getStatus(id)
        if (status.run_complete || status.status === 'complete') {
          stopPolling()
          setResources(status.resources.map(toResourceRow))
          setLangsmithTraceUrl(status.langsmith_trace_url)
          setMutationCount(status.mutation_count)
          setPhase('complete')
        } else if (status.status === 'error') {
          stopPolling()
          setErrorMessage(status.error_message ?? 'Execution failed.')
          setPhase('error')
        }
      } catch (err) { stopPolling(); setErrorMessage(String(err)); setPhase('error') }
    }, 2000)
  }, [stopPolling])

  useEffect(() => () => stopPolling(), [stopPolling])

  // ── Cost Center handlers ────────────────────────────────────────────────────

  async function handleStartScan() {
    if (!projectId.trim()) return
    setErrorMessage(null); setResources([]); setApprovedIds(new Set())
    setMutationCount(0); setStatusMessage('Starting scan…'); setPhase('scanning')
    try {
      const { run_id } = await startRun(projectId.trim(), dryRun)
      setRunId(run_id)
      setStatusMessage(`Run ${run_id.slice(0, 8)}… — scanning GCP project`)
      pollForPlan(run_id)
    } catch (err) { setErrorMessage(String(err)); setPhase('error') }
  }

  function handleApprove(id: string)  { setApprovedIds(prev => new Set([...prev, id])) }
  function handleReject(id: string)   { setApprovedIds(prev => { const n = new Set(prev); n.delete(id); return n }) }

  async function handleExecute() {
    if (!runId) return
    setRevalidationStatus('running'); setPhase('executing')
    try {
      await approvePlan(runId, [...approvedIds])
      setRevalidationStatus('complete')
      pollForCompletion(runId)
    } catch (err) { setErrorMessage(String(err)); setPhase('error') }
  }

  function handleReset() {
    stopPolling(); setPhase('start'); setRunId(null); setResources([])
    setApprovedIds(new Set()); setRevalidationStatus('idle'); setLangsmithTraceUrl(null)
    setErrorMessage(null); setMutationCount(0); setStatusMessage('')
  }

  // ── IAM ticket handler ──────────────────────────────────────────────────────

  function handleTicketCreated() {
    loadTickets()
    // Brief delay then navigate to tickets so admin can see it
    setTimeout(() => setNavSection('tickets'), 600)
  }

  // ── Derived stats ───────────────────────────────────────────────────────────

  const totalSavings = resources.reduce((s, r) =>
    r.estimated_monthly_savings != null ? s + r.estimated_monthly_savings : s, 0)

  const approvedSavings = resources.reduce((s, r) =>
    approvedIds.has(r.resource_id) && r.estimated_monthly_savings != null
      ? s + r.estimated_monthly_savings : s, 0)

  const decisionCounts = resources.reduce<Record<string, number>>((acc, r) => {
    if (r.decision) acc[r.decision] = (acc[r.decision] ?? 0) + 1
    return acc
  }, {})

  const [phaseColor, phaseBg] = PHASE_COLORS[phase]
  const pendingTicketCount = tickets.filter(t => t.status === 'pending').length

  // ── Render ──────────────────────────────────────────────────────────────────

  return (
    <div style={{ display: 'flex', minHeight: '100vh', fontFamily: "'Inter','Segoe UI',system-ui,sans-serif", background: '#f0f2f5' }}>
      <style>{`
        * { box-sizing: border-box; }
        body { margin: 0; }
        @keyframes blink { 0%,100%{opacity:1} 50%{opacity:0.2} }
        @keyframes spin  { to{transform:rotate(360deg)} }
        @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.4} }
        button:hover:not(:disabled) { filter: brightness(0.93); }
        input[type="text"]:focus, textarea:focus { outline: 2px solid #1f77b4; outline-offset: 1px; }
      `}</style>

      {/* ── Sidebar nav ────────────────────────────────────────────────────── */}
      <aside style={{
        width: 240, minWidth: 240, background: '#fff', borderRight: '1px solid #dee2e6',
        display: 'flex', flexDirection: 'column', position: 'sticky', top: 0, height: '100vh', overflowY: 'auto',
      }}>
        {/* Branding */}
        <div style={{
          padding: '18px 20px 14px', borderBottom: '1px solid #dee2e6',
          background: 'linear-gradient(135deg, #1f3c6e 0%, #1f77b4 100%)', color: '#fff',
        }}>
          <div style={{ fontSize: 22, fontWeight: 800, letterSpacing: -0.5 }}>🐕 Cerberus</div>
          <div style={{ fontSize: 11, opacity: 0.8, marginTop: 3 }}>GCP Dev Environment Guardian</div>
        </div>

        {/* Navigation */}
        <nav style={{ padding: '12px 0 8px' }}>
          <div style={{ fontSize: 10, fontWeight: 700, color: '#b0bec5', letterSpacing: 1.2, padding: '0 16px 8px' }}>NAVIGATION</div>
          {NAV_ITEMS.map(item => (
            <NavItem
              key={item.section}
              icon={item.icon}
              label={item.label}
              active={navSection === item.section}
              onClick={() => setNavSection(item.section)}
              badge={item.section === 'tickets' ? pendingTicketCount : undefined}
            />
          ))}
        </nav>

        {/* Cost Center extras (pipeline + presets) */}
        {navSection === 'cost' && (
          <>
            <div style={{ padding: '8px 12px', borderTop: '1px solid #f0f0f0' }}>
              <div style={{ fontSize: 10, fontWeight: 700, color: '#b0bec5', letterSpacing: 1.2, marginBottom: 8, paddingLeft: 4 }}>PIPELINE</div>
              {phase !== 'start' && (
                <div style={{ marginBottom: 6, padding: '3px 10px', display: 'inline-block', borderRadius: 12, fontSize: 11, fontWeight: 600, background: phaseBg, color: phaseColor }}>
                  {PHASE_LABELS[phase]}
                </div>
              )}
              {PIPELINE_STEPS.map(step => {
                const done   = step.phases.includes(phase)
                const active = (
                  (step.id === 'scan'    && phase === 'scanning') ||
                  (step.id === 'enrich' && phase === 'scanning') ||
                  (step.id === 'reason' && phase === 'scanning') ||
                  (step.id === 'approve'&& phase === 'awaiting_approval') ||
                  (step.id === 'execute'&& phase === 'executing')
                )
                return <PipelineStep key={step.id} icon={step.icon} label={step.label} done={done} active={active} />
              })}
            </div>

            <div style={{ padding: '10px 12px', borderTop: '1px solid #f0f0f0' }}>
              <div style={{ fontSize: 10, fontWeight: 700, color: '#b0bec5', letterSpacing: 1.2, marginBottom: 8, paddingLeft: 4 }}>QUICK SCAN</div>
              {QUICK_PRESETS.map(p => (
                <button
                  key={p.value}
                  onClick={() => { setProjectId(p.value); if (phase !== 'start') handleReset() }}
                  style={{
                    width: '100%', textAlign: 'left', padding: '7px 10px', marginBottom: 4, borderRadius: 6,
                    border: '1px solid #dee2e6', background: projectId === p.value ? '#e3f2fd' : '#fff',
                    color: projectId === p.value ? '#1f77b4' : '#495057',
                    fontWeight: projectId === p.value ? 600 : 400, cursor: 'pointer', fontSize: 12,
                  }}
                >
                  {p.label}
                </button>
              ))}
            </div>

            {/* Run stats */}
            {resources.length > 0 && (
              <div style={{ padding: '10px 16px', borderTop: '1px solid #f0f0f0' }}>
                <div style={{ fontSize: 10, fontWeight: 700, color: '#b0bec5', letterSpacing: 1.2, marginBottom: 8 }}>SCAN STATS</div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginBottom: 8 }}>
                  <div style={sideStatBox}><div style={sideStatLabel}>Resources</div><div style={sideStatValue}>{resources.length}</div></div>
                  <div style={sideStatBox}><div style={sideStatLabel}>Approved</div><div style={sideStatValue}>{approvedIds.size}</div></div>
                </div>
                <div style={{ ...sideStatBox, marginBottom: 8 }}>
                  <div style={sideStatLabel}>Total waste</div>
                  <div style={{ ...sideStatValue, color: '#e65100', fontSize: 16 }}>{fmt(totalSavings)}<span style={{ fontSize: 10 }}>/mo</span></div>
                </div>
                {approvedIds.size > 0 && (
                  <div style={sideStatBox}>
                    <div style={sideStatLabel}>Approved savings</div>
                    <div style={{ ...sideStatValue, color: '#2e7d32', fontSize: 16 }}>{fmt(approvedSavings)}<span style={{ fontSize: 10 }}>/mo</span></div>
                  </div>
                )}
              </div>
            )}

            {runId && (
              <div style={{ padding: '8px 16px', borderTop: '1px solid #f0f0f0' }}>
                <div style={{ fontSize: 10, color: '#b0bec5', marginBottom: 4 }}>RUN ID</div>
                <code style={{ fontSize: 11, color: '#495057' }}>{runId.slice(0, 14)}…</code>
                {dryRun && (
                  <div style={{ marginTop: 5, display: 'inline-block', padding: '2px 8px', background: '#e3f2fd', color: '#1f77b4', borderRadius: 10, fontSize: 11, fontWeight: 600 }}>
                    DRY-RUN
                  </div>
                )}
              </div>
            )}

            {phase !== 'start' && (
              <div style={{ padding: '8px 16px 0', borderTop: '1px solid #f0f0f0', marginTop: 'auto' }}>
                <button onClick={handleReset} style={{ width: '100%', padding: '7px', borderRadius: 6, border: '1px solid #dee2e6', background: '#f8f9fa', color: '#495057', cursor: 'pointer', fontSize: 13 }}>
                  + New Scan
                </button>
              </div>
            )}
          </>
        )}

        {/* Footer */}
        <div style={{ marginTop: 'auto', padding: '12px 16px', borderTop: '1px solid #f0f0f0', fontSize: 11, color: '#b0bec5' }}>
          v1.0 · session/s09 · dry-run by default
        </div>
      </aside>

      {/* ── Main content ─────────────────────────────────────────────────── */}
      <main style={{ flex: 1, padding: '28px 32px', overflowY: 'auto', maxWidth: 1200 }}>

        {/* Dashboard */}
        {navSection === 'dashboard' && (
          <DashboardView resources={resources} tickets={tickets} totalWaste={totalSavings} onNav={setNavSection} />
        )}

        {/* IAM Center */}
        {navSection === 'iam' && (
          <div>
            <h1 style={{ margin: '0 0 4px', fontSize: 24, fontWeight: 700 }}>IAM Center</h1>
            <p style={{ margin: '0 0 20px', color: '#6c757d', fontSize: 14 }}>
              Request least-privilege access and manage identity records.
            </p>
            <IamPanel onTicketCreated={handleTicketCreated} />
          </div>
        )}

        {/* Cost Center */}
        {navSection === 'cost' && (
          <div>
            {/* ── Start form ─────────────────────────────────────────────── */}
            {phase === 'start' && (
              <div>
                <h1 style={{ margin: '0 0 4px', fontSize: 24, fontWeight: 700 }}>Cost Center</h1>
                <p style={{ margin: '0 0 28px', color: '#6c757d', fontSize: 14 }}>
                  Discover idle resources, enrich with ownership data, and classify with Gemini.
                </p>
                <div style={mainCard}>
                  <label style={fieldLabel}>GCP Project ID</label>
                  <input
                    style={inputStyle} type="text" value={projectId}
                    onChange={e => setProjectId(e.target.value)}
                    placeholder="nexus-tech-dev-sandbox"
                    onKeyDown={e => e.key === 'Enter' && handleStartScan()}
                  />
                  <label style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 24, cursor: 'pointer' }}>
                    <input type="checkbox" checked={dryRun} onChange={() => setDryRun(v => !v)} />
                    <span style={{ fontWeight: 600, fontSize: 14 }}>Dry-run mode</span>
                    <span style={{ color: '#6c757d', fontSize: 13 }}>— no GCP mutations, safe for demos</span>
                  </label>
                  <button style={primaryBtn} onClick={handleStartScan} disabled={!projectId.trim()}>
                    Start Scan →
                  </button>
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 16, marginTop: 24 }}>
                  {[
                    { icon: '🔍', title: 'Scan', desc: 'Discovers VMs, orphaned disks, and unused IPs in the target GCP project.', color: '#1f77b4' },
                    { icon: '🧠', title: 'Reason', desc: 'Calls Gemini 1.5 Pro to classify each resource and estimate monthly savings.', color: '#ff9800' },
                    { icon: '✅', title: 'Execute', desc: 'Human-approved actions are executed with full audit trail and dry-run guard.', color: '#4caf50' },
                  ].map(c => (
                    <div key={c.title} style={{ ...mainCard, borderTop: `4px solid ${c.color}`, padding: '18px 20px' }}>
                      <div style={{ fontSize: 22, marginBottom: 8 }}>{c.icon}</div>
                      <div style={{ fontWeight: 700, marginBottom: 6 }}>{c.title}</div>
                      <div style={{ fontSize: 13, color: '#6c757d', lineHeight: 1.5 }}>{c.desc}</div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* ── Scanning ──────────────────────────────────────────────── */}
            {phase === 'scanning' && (
              <div>
                <h1 style={{ margin: '0 0 20px', fontSize: 22, fontWeight: 700 }}>
                  Scanning <span style={{ color: '#1f77b4' }}>{projectId}</span>
                </h1>
                <div style={mainCard}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16 }}>
                    <div style={{ width: 20, height: 20, border: '3px solid #1f77b4', borderTopColor: 'transparent', borderRadius: '50%', animation: 'spin 0.9s linear infinite', flexShrink: 0 }} />
                    <div style={{ fontWeight: 600 }}>{statusMessage}</div>
                  </div>
                  <p style={{ color: '#6c757d', fontSize: 13, margin: '0 0 16px' }}>
                    Discovering resources → enriching ownership data → classifying with Gemini
                  </p>
                  <div style={{ height: 6, background: '#e9ecef', borderRadius: 3, overflow: 'hidden' }}>
                    <div style={{ height: '100%', width: '70%', background: '#1f77b4', borderRadius: 3, animation: 'pulse 2s ease-in-out infinite' }} />
                  </div>
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 12, marginTop: 16 }}>
                  {[
                    { step: '1', label: 'Scan Node',   desc: 'Listing VMs, disks, IPs' },
                    { step: '2', label: 'Enrich Node', desc: 'Resolving ownership' },
                    { step: '3', label: 'Reason Node', desc: 'Gemini classification' },
                  ].map(s => (
                    <div key={s.step} style={{ ...mainCard, padding: '14px 16px', borderLeft: '4px solid #1f77b4' }}>
                      <div style={{ fontSize: 11, color: '#6c757d', marginBottom: 4 }}>STEP {s.step}</div>
                      <div style={{ fontWeight: 600, marginBottom: 4 }}>{s.label}</div>
                      <div style={{ fontSize: 12, color: '#1f77b4' }}>{s.desc}…</div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* ── Awaiting approval ────────────────────────────────────── */}
            {phase === 'awaiting_approval' && (
              <div>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 20 }}>
                  <div>
                    <h1 style={{ margin: 0, fontSize: 22, fontWeight: 700 }}>Review & Approve</h1>
                    <p style={{ margin: '4px 0 0', color: '#6c757d', fontSize: 14 }}>{statusMessage}</p>
                  </div>
                  <span style={{ padding: '5px 14px', borderRadius: 14, fontSize: 13, fontWeight: 600, background: '#fff3cd', color: '#856404' }}>
                    Awaiting Approval
                  </span>
                </div>
                <div style={{ display: 'flex', gap: 20, alignItems: 'flex-start' }}>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ ...mainCard, display: 'flex', gap: 28, flexWrap: 'wrap', padding: '14px 24px', borderLeft: '4px solid #1f77b4' }}>
                      <Stat label="Resources"       value={resources.length} />
                      <Stat label="Total waste"      value={`${fmt(totalSavings)}/mo`} />
                      <Stat label="Approved"         value={approvedIds.size} />
                      <Stat label="Approved savings" value={`${fmt(approvedSavings)}/mo`} />
                    </div>
                    <div style={mainCard}>
                      <h2 style={{ margin: '0 0 16px', fontSize: 16 }}>Resources</h2>
                      <ApprovalTable resources={resources} approvedIds={approvedIds} onApprove={handleApprove} onReject={handleReject} />
                    </div>
                    <div style={mainCard}>
                      <ExecutePanel approvedCount={approvedIds.size} dryRun={dryRun} onToggleDryRun={() => setDryRun(v => !v)} onExecute={handleExecute} revalidationStatus={revalidationStatus} langsmithTraceUrl={langsmithTraceUrl} />
                    </div>
                  </div>
                  <div style={{ width: 220, flexShrink: 0 }}>
                    <div style={{ ...mainCard, padding: '16px 18px' }}>
                      <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 12 }}>Decision Breakdown</div>
                      {Object.entries(DECISION_CARD).map(([key, style]) => {
                        const count = decisionCounts[key] ?? 0
                        if (count === 0) return null
                        return (
                          <div key={key} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '7px 10px', borderRadius: 6, marginBottom: 6, background: style.bg, borderLeft: `3px solid ${style.border}` }}>
                            <span style={{ fontSize: 12, color: style.color, fontWeight: 600 }}>{style.label}</span>
                            <span style={{ fontSize: 14, fontWeight: 700, color: style.color }}>{count}</span>
                          </div>
                        )
                      })}
                    </div>
                    <div style={{ ...mainCard, padding: '16px 18px' }}>
                      <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 12 }}>Savings Potential</div>
                      <MetricCard label="Monthly waste" value={`${fmt(totalSavings)}/mo`} borderColor="#f44336" />
                      <MetricCard label="Annual waste" value={`${fmt(totalSavings * 12)}/yr`} sub="if all actioned" borderColor="#ff9800" />
                      {approvedIds.size > 0 && <MetricCard label="Approved savings" value={`${fmt(approvedSavings)}/mo`} borderColor="#4caf50" />}
                    </div>
                    <div style={{ ...mainCard, padding: '16px 18px' }}>
                      <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 10 }}>Mode</div>
                      <div style={{ padding: '8px 12px', borderRadius: 6, background: dryRun ? '#e3f2fd' : '#fff3e0', border: `1px solid ${dryRun ? '#90caf9' : '#ffb74d'}` }}>
                        <div style={{ fontWeight: 600, fontSize: 13, color: dryRun ? '#1f77b4' : '#e65100' }}>{dryRun ? '🔒 Dry-run' : '⚡ Live'}</div>
                        <div style={{ fontSize: 11, color: '#6c757d', marginTop: 3 }}>{dryRun ? 'No GCP mutations' : 'Real infrastructure changes'}</div>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            )}

            {/* ── Executing ───────────────────────────────────────────── */}
            {phase === 'executing' && (
              <div>
                <h1 style={{ margin: '0 0 20px', fontSize: 22, fontWeight: 700 }}>
                  Executing {approvedIds.size} approved action{approvedIds.size !== 1 ? 's' : ''}
                </h1>
                <div style={{ ...mainCard, borderLeft: '4px solid #1f77b4' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12 }}>
                    <div style={{ width: 20, height: 20, border: '3px solid #1f77b4', borderTopColor: 'transparent', borderRadius: '50%', animation: 'spin 0.9s linear infinite', flexShrink: 0 }} />
                    <span style={{ fontWeight: 600 }}>{dryRun ? 'Dry-run — recording actions without GCP mutations' : 'Executing live GCP mutations…'}</span>
                  </div>
                  <ExecutePanel approvedCount={approvedIds.size} dryRun={dryRun} onToggleDryRun={() => {}} onExecute={() => {}} revalidationStatus={revalidationStatus} langsmithTraceUrl={langsmithTraceUrl} />
                </div>
              </div>
            )}

            {/* ── Complete ────────────────────────────────────────────── */}
            {phase === 'complete' && (
              <div>
                <div style={{ ...mainCard, borderLeft: '4px solid #4caf50', display: 'flex', gap: 32, flexWrap: 'wrap', alignItems: 'center', padding: '18px 24px' }}>
                  <span style={{ fontSize: 22 }}>✅</span>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontWeight: 700, fontSize: 16, color: '#155724' }}>Run complete</div>
                    <div style={{ fontSize: 13, color: '#6c757d', marginTop: 2 }}>
                      {dryRun ? 'Dry-run — no mutations applied.' : `${mutationCount} mutation(s) applied.`}
                    </div>
                  </div>
                  <Stat label="Run ID"    value={`${runId?.slice(0, 8)}…`} />
                  <Stat label="Mutations" value={mutationCount} />
                  <Stat label="Mode"      value={dryRun ? 'Dry-run' : 'Live'} />
                  {langsmithTraceUrl && (
                    <div>
                      <div style={{ fontSize: 11, color: '#6c757d', marginBottom: 3 }}>Reasoning trace</div>
                      <a href={langsmithTraceUrl} target="_blank" rel="noreferrer" style={{ fontSize: 13 }}>View in LangSmith ↗</a>
                    </div>
                  )}
                </div>
                {resources.length > 0 && (
                  <div style={mainCard}>
                    <h2 style={{ margin: '0 0 16px', fontSize: 16 }}>
                      Processed resources <span style={{ fontSize: 13, fontWeight: 400, color: '#6c757d' }}>({resources.length})</span>
                    </h2>
                    <div style={{ display: 'flex', gap: 12, marginBottom: 20, flexWrap: 'wrap' }}>
                      {[
                        { key: 'DRY_RUN',          label: 'Dry-run',  bg: '#e3f2fd', color: '#1f77b4' },
                        { key: 'SUCCESS',           label: 'Success',  bg: '#e8f5e9', color: '#2e7d32' },
                        { key: 'FAILED',            label: 'Failed',   bg: '#ffebee', color: '#c62828' },
                        { key: 'SKIPPED_GUARDRAIL', label: 'Guardrail',bg: '#fff8e1', color: '#f57f17' },
                        { key: 'REJECTED',          label: 'Rejected', bg: '#f5f5f5', color: '#616161' },
                      ].map(o => {
                        const count = resources.filter(r => r.outcome === o.key).length
                        if (!count) return null
                        return (
                          <div key={o.key} style={{ padding: '6px 14px', borderRadius: 8, background: o.bg, color: o.color, fontWeight: 600, fontSize: 13 }}>
                            {o.label}: {count}
                          </div>
                        )
                      })}
                    </div>
                    <ApprovalTable resources={resources} approvedIds={approvedIds} onApprove={() => {}} onReject={() => {}} />
                  </div>
                )}
                <div style={{ textAlign: 'center', marginTop: 8 }}>
                  <button style={primaryBtn} onClick={handleReset}>+ Start new scan</button>
                </div>
              </div>
            )}

            {/* ── Error ──────────────────────────────────────────────── */}
            {phase === 'error' && (
              <div style={{ ...mainCard, borderLeft: '4px solid #f44336' }}>
                <h2 style={{ marginTop: 0, fontSize: 18, color: '#b71c1c' }}>Error</h2>
                <pre style={{ background: '#fff3f3', padding: 12, borderRadius: 4, fontSize: 13, overflowX: 'auto', color: '#c62828', margin: 0 }}>
                  {errorMessage ?? 'Unknown error'}
                </pre>
                <button style={{ ...secondaryBtn, marginTop: 14 }} onClick={handleReset}>Try again</button>
              </div>
            )}
          </div>
        )}

        {/* Security Hub */}
        {navSection === 'security' && (
          <SecurityHubView resources={resources} />
        )}

        {/* Tickets */}
        {navSection === 'tickets' && (
          <TicketsView tickets={tickets} onRefresh={loadTickets} />
        )}
      </main>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Shared styles
// ---------------------------------------------------------------------------

const mainCard: React.CSSProperties = {
  background: '#fff', border: '1px solid #dee2e6', borderRadius: 8,
  padding: '20px 24px', marginBottom: 16, boxShadow: '0 1px 3px rgba(0,0,0,0.06)',
}

const primaryBtn: React.CSSProperties = {
  background: '#1f77b4', color: '#fff', border: 'none', borderRadius: 6,
  padding: '10px 24px', fontSize: 15, fontWeight: 600, cursor: 'pointer',
}

const secondaryBtn: React.CSSProperties = {
  background: '#6c757d', color: '#fff', border: 'none', borderRadius: 6,
  padding: '8px 18px', fontSize: 14, cursor: 'pointer',
}

const inputStyle: React.CSSProperties = {
  width: '100%', padding: '10px 14px', fontSize: 15, border: '1px solid #ced4da',
  borderRadius: 6, marginBottom: 16,
}

const fieldLabel: React.CSSProperties = {
  display: 'block', marginBottom: 6, fontWeight: 600, fontSize: 14,
}

const sideStatBox: React.CSSProperties = {
  background: '#f8f9fa', borderRadius: 6, padding: '8px 10px',
}

const sideStatLabel: React.CSSProperties = {
  fontSize: 10, color: '#9e9e9e', textTransform: 'uppercase' as const, letterSpacing: 0.5, marginBottom: 2,
}

const sideStatValue: React.CSSProperties = {
  fontSize: 18, fontWeight: 700, color: '#212529',
}

const errBox: React.CSSProperties = {
  background: '#ffebee', border: '1px solid #ef9a9a', borderRadius: 4,
  padding: '10px 12px', fontSize: 13, color: '#c62828',
}
