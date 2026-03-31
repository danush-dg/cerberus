import { useState, useEffect, useRef, useCallback } from 'react'
import { ApprovalTable } from './components/ApprovalTable'
import { ExecutePanel } from './components/ExecutePanel'
import { IamPanel } from './components/IamPanel'
import type { ResourceRow, RevalidationStatus } from './types'
import {
  startRun,
  pollPlan,
  approvePlan,
  getStatus,
  type ResourceRecord,
} from './api'

// ---------------------------------------------------------------------------
// Phase state machine
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

// ---------------------------------------------------------------------------
// Pipeline steps config
// ---------------------------------------------------------------------------

const PIPELINE_STEPS = [
  { id: 'scan',       label: 'Scan',      icon: '🔍', phases: ['scanning', 'awaiting_approval', 'executing', 'complete'] },
  { id: 'enrich',     label: 'Enrich',    icon: '🏷️',  phases: ['awaiting_approval', 'executing', 'complete'] },
  { id: 'reason',     label: 'Reason',    icon: '🧠', phases: ['awaiting_approval', 'executing', 'complete'] },
  { id: 'approve',    label: 'Approve',   icon: '✅', phases: ['executing', 'complete'] },
  { id: 'execute',    label: 'Execute',   icon: '⚡', phases: ['complete'] },
  { id: 'audit',      label: 'Audit',     icon: '📋', phases: ['complete'] },
]

const QUICK_PRESETS = [
  { label: '🔍 Sandbox scan',  value: 'nexus-tech-dev-sandbox' },
  { label: '🧪 Dev 1',         value: 'nexus-tech-dev-1' },
  { label: '🧪 Dev 2',         value: 'nexus-tech-dev-2' },
  { label: '🧪 Dev 3',         value: 'nexus-tech-dev-3' },
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
      background: '#fff',
      border: '1px solid #dee2e6',
      borderLeft: `4px solid ${borderColor}`,
      borderRadius: 6,
      padding: '12px 16px',
      marginBottom: 10,
    }}>
      <div style={{ fontSize: 12, color: '#6c757d', marginBottom: 4 }}>{label}</div>
      <div style={{ fontSize: 20, fontWeight: 700 }}>{value}</div>
      {sub && <div style={{ fontSize: 12, color: '#6c757d', marginTop: 2 }}>{sub}</div>}
    </div>
  )
}

function PipelineStep({
  icon, label, done, active,
}: { icon: string; label: string; done: boolean; active: boolean }) {
  return (
    <div style={{
      display: 'flex',
      alignItems: 'center',
      gap: 10,
      padding: '7px 12px',
      borderRadius: 6,
      background: active ? '#e3f2fd' : done ? '#f1f8f1' : 'transparent',
      marginBottom: 2,
    }}>
      <span style={{ fontSize: 15 }}>{icon}</span>
      <span style={{
        fontSize: 13,
        fontWeight: active ? 700 : 500,
        color: active ? '#1f77b4' : done ? '#2e7d32' : '#9e9e9e',
        flex: 1,
      }}>
        {label}
      </span>
      {done && !active && <span style={{ fontSize: 12, color: '#2e7d32' }}>✓</span>}
      {active && <span style={{
        width: 8, height: 8, borderRadius: '50%', background: '#1f77b4',
        animation: 'blink 1s step-end infinite',
      }} />}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function App() {
  const [phase, setPhase] = useState<Phase>('start')
  const [projectId, setProjectId] = useState('')
  const [dryRun, setDryRun] = useState(true)
  const [runId, setRunId] = useState<string | null>(null)
  const [resources, setResources] = useState<ResourceRow[]>([])
  const [approvedIds, setApprovedIds] = useState<Set<string>>(new Set())
  const [revalidationStatus, setRevalidationStatus] = useState<RevalidationStatus>('idle')
  const [langsmithTraceUrl, setLangsmithTraceUrl] = useState<string | null>(null)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [mutationCount, setMutationCount] = useState(0)
  const [statusMessage, setStatusMessage] = useState('')

  const pollTimer = useRef<ReturnType<typeof setInterval> | null>(null)

  // ── Polling ────────────────────────────────────────────────────────────────

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

  // ── Actions ────────────────────────────────────────────────────────────────

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

  // ── Derived stats ──────────────────────────────────────────────────────────

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

  // ── Render ─────────────────────────────────────────────────────────────────

  return (
    <div style={{ display: 'flex', minHeight: '100vh', fontFamily: "'Inter','Segoe UI',system-ui,sans-serif", background: '#f0f2f5' }}>
      <style>{`
        * { box-sizing: border-box; }
        body { margin: 0; }
        @keyframes blink { 0%,100%{opacity:1} 50%{opacity:0.2} }
        @keyframes spin  { to{transform:rotate(360deg)} }
        @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.4} }
        button:hover:not(:disabled) { filter: brightness(0.93); }
        input[type="text"]:focus { outline: 2px solid #1f77b4; outline-offset: 1px; }
      `}</style>

      {/* ── Sidebar ──────────────────────────────────────────────────────── */}
      <aside style={{
        width: 260,
        minWidth: 260,
        background: '#fff',
        borderRight: '1px solid #dee2e6',
        display: 'flex',
        flexDirection: 'column',
        padding: '0 0 24px',
        position: 'sticky',
        top: 0,
        height: '100vh',
        overflowY: 'auto',
      }}>
        {/* Branding */}
        <div style={{
          padding: '20px 20px 16px',
          borderBottom: '1px solid #dee2e6',
          background: 'linear-gradient(135deg, #1f3c6e 0%, #1f77b4 100%)',
          color: '#fff',
        }}>
          <div style={{ fontSize: 24, fontWeight: 800, letterSpacing: -0.5 }}>
            🐕 Cerberus
          </div>
          <div style={{ fontSize: 12, opacity: 0.85, marginTop: 4 }}>
            GCP Dev Environment Guardian
          </div>
          {phase !== 'start' && (
            <div style={{
              marginTop: 10,
              display: 'inline-block',
              padding: '3px 10px',
              borderRadius: 12,
              fontSize: 12,
              fontWeight: 600,
              background: phaseBg,
              color: phaseColor,
            }}>
              {PHASE_LABELS[phase]}
            </div>
          )}
        </div>

        {/* Pipeline steps */}
        <div style={{ padding: '16px 12px 8px' }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: '#9e9e9e', letterSpacing: 1, marginBottom: 8, paddingLeft: 12 }}>
            PIPELINE
          </div>
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

        {/* Quick presets */}
        <div style={{ padding: '12px 12px 8px', borderTop: '1px solid #f0f0f0' }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: '#9e9e9e', letterSpacing: 1, marginBottom: 8, paddingLeft: 4 }}>
            QUICK SCAN
          </div>
          {QUICK_PRESETS.map(p => (
            <button
              key={p.value}
              onClick={() => { setProjectId(p.value); if (phase !== 'start') handleReset() }}
              style={{
                width: '100%', textAlign: 'left', padding: '8px 12px',
                marginBottom: 4, borderRadius: 6, border: '1px solid #dee2e6',
                background: projectId === p.value ? '#e3f2fd' : '#fff',
                color: projectId === p.value ? '#1f77b4' : '#495057',
                fontWeight: projectId === p.value ? 600 : 400,
                cursor: 'pointer', fontSize: 13,
              }}
            >
              {p.label}
            </button>
          ))}
        </div>

        {/* Run stats (when scan is in progress or done) */}
        {resources.length > 0 && (
          <div style={{ padding: '12px 16px 8px', borderTop: '1px solid #f0f0f0' }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: '#9e9e9e', letterSpacing: 1, marginBottom: 10 }}>
              SCAN STATS
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginBottom: 8 }}>
              <div style={sideStatBox}>
                <div style={sideStatLabel}>Resources</div>
                <div style={sideStatValue}>{resources.length}</div>
              </div>
              <div style={sideStatBox}>
                <div style={sideStatLabel}>Approved</div>
                <div style={sideStatValue}>{approvedIds.size}</div>
              </div>
            </div>
            <div style={{ ...sideStatBox, marginBottom: 8 }}>
              <div style={sideStatLabel}>Total waste</div>
              <div style={{ ...sideStatValue, color: '#e65100' }}>{fmt(totalSavings)}<span style={{ fontSize: 10 }}>/mo</span></div>
            </div>
            {approvedIds.size > 0 && (
              <div style={{ ...sideStatBox }}>
                <div style={sideStatLabel}>Approved savings</div>
                <div style={{ ...sideStatValue, color: '#2e7d32' }}>{fmt(approvedSavings)}<span style={{ fontSize: 10 }}>/mo</span></div>
              </div>
            )}
          </div>
        )}

        {/* Run info */}
        {runId && (
          <div style={{ padding: '10px 16px', borderTop: '1px solid #f0f0f0', marginTop: 'auto' }}>
            <div style={{ fontSize: 11, color: '#9e9e9e', marginBottom: 4 }}>RUN ID</div>
            <code style={{ fontSize: 11, color: '#495057' }}>{runId.slice(0, 16)}…</code>
            {dryRun && (
              <div style={{ marginTop: 6, display: 'inline-block', padding: '2px 8px', background: '#e3f2fd', color: '#1f77b4', borderRadius: 10, fontSize: 11, fontWeight: 600 }}>
                DRY-RUN
              </div>
            )}
          </div>
        )}

        {/* New Scan button */}
        {phase !== 'start' && (
          <div style={{ padding: '10px 16px 0', borderTop: '1px solid #f0f0f0' }}>
            <button
              onClick={handleReset}
              style={{
                width: '100%', padding: '8px', borderRadius: 6,
                border: '1px solid #dee2e6', background: '#f8f9fa',
                color: '#495057', cursor: 'pointer', fontSize: 13, fontWeight: 500,
              }}
            >
              + New Scan
            </button>
          </div>
        )}
      </aside>

      {/* ── Main content ─────────────────────────────────────────────────── */}
      <main style={{ flex: 1, padding: '28px 32px', overflowY: 'auto' }}>

        {/* ── Start form ─────────────────────────────────────────────────── */}
        {phase === 'start' && (
          <div>
            <h1 style={{ margin: '0 0 4px', fontSize: 24, fontWeight: 700 }}>
              Start a new scan
            </h1>
            <p style={{ margin: '0 0 28px', color: '#6c757d', fontSize: 14 }}>
              Discover idle resources, enrich with ownership data, and classify with Gemini.
            </p>

            <div style={mainCard}>
              <label style={fieldLabel}>GCP Project ID</label>
              <input
                style={inputStyle}
                type="text"
                value={projectId}
                onChange={e => setProjectId(e.target.value)}
                placeholder="nexus-tech-dev-sandbox"
                onKeyDown={e => e.key === 'Enter' && handleStartScan()}
              />

              <label style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 24, cursor: 'pointer' }}>
                <input type="checkbox" checked={dryRun} onChange={() => setDryRun(v => !v)} />
                <span style={{ fontWeight: 600, fontSize: 14 }}>Dry-run mode</span>
                <span style={{ color: '#6c757d', fontSize: 13 }}>— no GCP mutations, safe for demos</span>
              </label>

              <button
                style={primaryBtn}
                onClick={handleStartScan}
                disabled={!projectId.trim()}
              >
                Start Scan →
              </button>
            </div>

            {/* Info cards */}
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

        {/* ── Scanning ───────────────────────────────────────────────────── */}
        {phase === 'scanning' && (
          <div>
            <h1 style={{ margin: '0 0 20px', fontSize: 22, fontWeight: 700 }}>
              Scanning <span style={{ color: '#1f77b4' }}>{projectId}</span>
            </h1>
            <div style={mainCard}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16 }}>
                <div style={{
                  width: 20, height: 20, border: '3px solid #1f77b4',
                  borderTopColor: 'transparent', borderRadius: '50%',
                  animation: 'spin 0.9s linear infinite', flexShrink: 0,
                }} />
                <div style={{ fontWeight: 600 }}>{statusMessage}</div>
              </div>
              <p style={{ color: '#6c757d', fontSize: 13, margin: '0 0 16px' }}>
                Discovering resources → enriching ownership data → classifying with Gemini
              </p>
              <div style={{ height: 6, background: '#e9ecef', borderRadius: 3, overflow: 'hidden' }}>
                <div style={{
                  height: '100%', width: '70%', background: '#1f77b4',
                  borderRadius: 3, animation: 'pulse 2s ease-in-out infinite',
                }} />
              </div>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 12, marginTop: 16 }}>
              {[
                { step: '1', label: 'Scan Node', desc: 'Listing VMs, disks, IPs', active: true },
                { step: '2', label: 'Enrich Node', desc: 'Resolving ownership', active: true },
                { step: '3', label: 'Reason Node', desc: 'Gemini classification', active: true },
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

        {/* ── Awaiting approval ──────────────────────────────────────────── */}
        {phase === 'awaiting_approval' && (
          <div>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 20 }}>
              <div>
                <h1 style={{ margin: 0, fontSize: 22, fontWeight: 700 }}>Review & Approve</h1>
                <p style={{ margin: '4px 0 0', color: '#6c757d', fontSize: 14 }}>
                  {statusMessage}
                </p>
              </div>
              <span style={{
                padding: '5px 14px', borderRadius: 14, fontSize: 13, fontWeight: 600,
                background: '#fff3cd', color: '#856404',
              }}>
                Awaiting Approval
              </span>
            </div>

            {/* Two-column: table left, stats right */}
            <div style={{ display: 'flex', gap: 20, alignItems: 'flex-start' }}>

              {/* Left: table + execute panel */}
              <div style={{ flex: 1, minWidth: 0 }}>
                {/* Summary bar */}
                <div style={{
                  ...mainCard,
                  display: 'flex', gap: 28, flexWrap: 'wrap', padding: '14px 24px',
                  borderLeft: '4px solid #1f77b4',
                }}>
                  <Stat label="Resources"       value={resources.length} />
                  <Stat label="Total waste"      value={`${fmt(totalSavings)}/mo`} />
                  <Stat label="Approved"         value={approvedIds.size} />
                  <Stat label="Approved savings" value={`${fmt(approvedSavings)}/mo`} />
                </div>

                {/* Approval table */}
                <div style={mainCard}>
                  <h2 style={{ margin: '0 0 16px', fontSize: 16 }}>Resources</h2>
                  <ApprovalTable
                    resources={resources}
                    approvedIds={approvedIds}
                    onApprove={handleApprove}
                    onReject={handleReject}
                  />
                </div>

                {/* Execute panel */}
                <div style={mainCard}>
                  <ExecutePanel
                    approvedCount={approvedIds.size}
                    dryRun={dryRun}
                    onToggleDryRun={() => setDryRun(v => !v)}
                    onExecute={handleExecute}
                    revalidationStatus={revalidationStatus}
                    langsmithTraceUrl={langsmithTraceUrl}
                  />
                </div>
              </div>

              {/* Right: decision breakdown + savings */}
              <div style={{ width: 220, flexShrink: 0 }}>
                <div style={{ ...mainCard, padding: '16px 18px' }}>
                  <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 12 }}>Decision Breakdown</div>
                  {Object.entries(DECISION_CARD).map(([key, style]) => {
                    const count = decisionCounts[key] ?? 0
                    if (count === 0) return null
                    return (
                      <div key={key} style={{
                        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                        padding: '7px 10px', borderRadius: 6, marginBottom: 6,
                        background: style.bg, borderLeft: `3px solid ${style.border}`,
                      }}>
                        <span style={{ fontSize: 12, color: style.color, fontWeight: 600 }}>{style.label}</span>
                        <span style={{ fontSize: 14, fontWeight: 700, color: style.color }}>{count}</span>
                      </div>
                    )
                  })}
                </div>

                <div style={{ ...mainCard, padding: '16px 18px' }}>
                  <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 12 }}>Savings Potential</div>
                  <MetricCard label="Monthly waste" value={`${fmt(totalSavings)}/mo`} borderColor="#f44336" />
                  <MetricCard label="Annual waste"  value={`${fmt(totalSavings * 12)}/yr`} sub="if all actioned" borderColor="#ff9800" />
                  {approvedIds.size > 0 && (
                    <MetricCard label="Approved savings" value={`${fmt(approvedSavings)}/mo`} borderColor="#4caf50" />
                  )}
                </div>

                <div style={{ ...mainCard, padding: '16px 18px' }}>
                  <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 10 }}>Mode</div>
                  <div style={{
                    padding: '8px 12px', borderRadius: 6,
                    background: dryRun ? '#e3f2fd' : '#fff3e0',
                    border: `1px solid ${dryRun ? '#90caf9' : '#ffb74d'}`,
                  }}>
                    <div style={{ fontWeight: 600, fontSize: 13, color: dryRun ? '#1f77b4' : '#e65100' }}>
                      {dryRun ? '🔒 Dry-run' : '⚡ Live'}
                    </div>
                    <div style={{ fontSize: 11, color: '#6c757d', marginTop: 3 }}>
                      {dryRun ? 'No GCP mutations' : 'Real infrastructure changes'}
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* ── Executing ──────────────────────────────────────────────────── */}
        {phase === 'executing' && (
          <div>
            <h1 style={{ margin: '0 0 20px', fontSize: 22, fontWeight: 700 }}>
              Executing {approvedIds.size} approved action{approvedIds.size !== 1 ? 's' : ''}
            </h1>
            <div style={{ ...mainCard, borderLeft: '4px solid #1f77b4' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12 }}>
                <div style={{
                  width: 20, height: 20, border: '3px solid #1f77b4',
                  borderTopColor: 'transparent', borderRadius: '50%',
                  animation: 'spin 0.9s linear infinite', flexShrink: 0,
                }} />
                <span style={{ fontWeight: 600 }}>
                  {dryRun ? 'Dry-run — recording actions without GCP mutations' : 'Executing live GCP mutations…'}
                </span>
              </div>
              <ExecutePanel
                approvedCount={approvedIds.size}
                dryRun={dryRun}
                onToggleDryRun={() => {}}
                onExecute={() => {}}
                revalidationStatus={revalidationStatus}
                langsmithTraceUrl={langsmithTraceUrl}
              />
            </div>
          </div>
        )}

        {/* ── Complete ───────────────────────────────────────────────────── */}
        {phase === 'complete' && (
          <div>
            <div style={{
              ...mainCard,
              borderLeft: '4px solid #4caf50',
              display: 'flex', gap: 32, flexWrap: 'wrap', alignItems: 'center',
              padding: '18px 24px',
            }}>
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
                  <a href={langsmithTraceUrl} target="_blank" rel="noreferrer" style={{ fontSize: 13 }}>
                    View in LangSmith ↗
                  </a>
                </div>
              )}
            </div>

            {resources.length > 0 && (
              <div style={mainCard}>
                <h2 style={{ margin: '0 0 16px', fontSize: 16 }}>
                  Processed resources
                  <span style={{ marginLeft: 8, fontSize: 13, fontWeight: 400, color: '#6c757d' }}>
                    ({resources.length})
                  </span>
                </h2>

                {/* Outcome summary */}
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
                      <div key={o.key} style={{
                        padding: '6px 14px', borderRadius: 8,
                        background: o.bg, color: o.color, fontWeight: 600, fontSize: 13,
                      }}>
                        {o.label}: {count}
                      </div>
                    )
                  })}
                </div>

                <ApprovalTable
                  resources={resources}
                  approvedIds={approvedIds}
                  onApprove={() => {}}
                  onReject={() => {}}
                />
              </div>
            )}

            <div style={{ textAlign: 'center', marginTop: 8 }}>
              <button style={primaryBtn} onClick={handleReset}>+ Start new scan</button>
            </div>
          </div>
        )}

        {/* ── Error ──────────────────────────────────────────────────────── */}
        {phase === 'error' && (
          <div style={{ ...mainCard, borderLeft: '4px solid #f44336' }}>
            <h2 style={{ marginTop: 0, fontSize: 18, color: '#b71c1c' }}>Error</h2>
            <pre style={{
              background: '#fff3f3', padding: 12, borderRadius: 4,
              fontSize: 13, overflowX: 'auto', color: '#c62828', margin: 0,
            }}>
              {errorMessage ?? 'Unknown error'}
            </pre>
            <button style={{ ...secondaryBtn, marginTop: 14 }} onClick={handleReset}>
              Try again
            </button>
          </div>
        )}
        {/* ── IAM Access Request ─────────────────────────────────────────── */}
        <IamPanel />

      </main>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Shared styles
// ---------------------------------------------------------------------------

const mainCard: React.CSSProperties = {
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
  padding: '10px 24px',
  fontSize: 15,
  fontWeight: 600,
  cursor: 'pointer',
}

const secondaryBtn: React.CSSProperties = {
  background: '#6c757d',
  color: '#fff',
  border: 'none',
  borderRadius: 6,
  padding: '8px 18px',
  fontSize: 14,
  cursor: 'pointer',
}

const inputStyle: React.CSSProperties = {
  width: '100%',
  padding: '10px 14px',
  fontSize: 15,
  border: '1px solid #ced4da',
  borderRadius: 6,
  marginBottom: 16,
}

const fieldLabel: React.CSSProperties = {
  display: 'block',
  marginBottom: 6,
  fontWeight: 600,
  fontSize: 14,
}

const sideStatBox: React.CSSProperties = {
  background: '#f8f9fa',
  borderRadius: 6,
  padding: '8px 10px',
}

const sideStatLabel: React.CSSProperties = {
  fontSize: 10,
  color: '#9e9e9e',
  textTransform: 'uppercase' as const,
  letterSpacing: 0.5,
  marginBottom: 2,
}

const sideStatValue: React.CSSProperties = {
  fontSize: 18,
  fontWeight: 700,
  color: '#212529',
}
