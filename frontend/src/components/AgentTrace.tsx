// ---------------------------------------------------------------------------
// AgentTrace — live reasoning / execution trace drawer
// Polls GET /run/{run_id}/events and renders a scrollable timeline of what
// the agent is doing at every stage.
// ---------------------------------------------------------------------------

import { useState, useEffect, useRef, useCallback } from 'react'
import { getRunEvents, type TraceEvent } from '../api'

interface Props {
  runId: string | null
  active: boolean   // true while scanning or executing
}

const NODE_LABEL: Record<string, string> = {
  scan_node:       'Scan Node',
  enrich_node:     'Enrich Node',
  reason_node:     'Reason Node',
  revalidate_node: 'Revalidate Node',
  approve_node:    'Approve Node',
  execute_node:    'Execute Node',
  audit_node:      'Audit Node',
}

const DECISION_CHIP: Record<string, { bg: string; color: string }> = {
  safe_to_stop:   { bg: '#fff3e0', color: '#e65100' },
  safe_to_delete: { bg: '#ffebee', color: '#b71c1c' },
  needs_review:   { bg: '#f5f5f5', color: '#424242' },
  skip:           { bg: '#e3f2fd', color: '#0d47a1' },
}

const OUTCOME_CHIP: Record<string, { bg: string; color: string }> = {
  SUCCESS:           { bg: '#e8f5e9', color: '#2e7d32' },
  DRY_RUN:           { bg: '#e3f2fd', color: '#1565c0' },
  FAILED:            { bg: '#ffebee', color: '#c62828' },
  SKIPPED_GUARDRAIL: { bg: '#fff8e1', color: '#f57f17' },
  REJECTED:          { bg: '#f5f5f5', color: '#616161' },
}

function fmt(ts: string): string {
  try {
    return new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
  } catch {
    return ts
  }
}

function Chip({ label, style }: { label: string; style: { bg: string; color: string } }) {
  return (
    <span style={{
      display: 'inline-block', padding: '1px 7px', borderRadius: 8, fontSize: 11,
      fontWeight: 600, background: style.bg, color: style.color, whiteSpace: 'nowrap',
    }}>
      {label}
    </span>
  )
}

function EventRow({ ev, isLast }: { ev: TraceEvent; isLast: boolean }) {
  const [expanded, setExpanded] = useState(false)
  const hasDetail = (ev.detail?.length ?? 0) > 0
  const isStart = ev.type === 'node_start'
  const opacity = isStart ? 0.65 : 1

  return (
    <div style={{ display: 'flex', gap: 10, opacity }}>
      {/* Timeline dot + line */}
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', width: 18, flexShrink: 0 }}>
        <div style={{
          width: 14, height: 14, borderRadius: '50%', flexShrink: 0, marginTop: 2,
          background: isStart ? 'transparent' : ev.color,
          border: `2px solid ${ev.color}`,
        }} />
        {!isLast && <div style={{ flex: 1, width: 2, background: '#e9ecef', minHeight: 8 }} />}
      </div>

      {/* Content */}
      <div style={{ flex: 1, paddingBottom: isLast ? 0 : 10 }}>
        <div
          style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: hasDetail ? 'pointer' : 'default' }}
          onClick={() => hasDetail && setExpanded(v => !v)}
        >
          <span style={{ fontSize: 13 }}>{ev.icon}</span>
          <span style={{ fontSize: 11, fontWeight: 700, color: ev.color, textTransform: 'uppercase' as const, letterSpacing: 0.5 }}>
            {NODE_LABEL[ev.node] ?? ev.node}
          </span>
          <span style={{ fontSize: 10, color: '#b0bec5', marginLeft: 'auto', flexShrink: 0 }}>
            {fmt(ev.ts)}
          </span>
          {hasDetail && <span style={{ fontSize: 11, color: '#9e9e9e' }}>{expanded ? '▲' : '▼'}</span>}
        </div>

        <div style={{ fontSize: 12, color: '#495057', marginTop: 2, lineHeight: 1.45 }}>
          {ev.message}
        </div>

        {/* Per-resource detail rows */}
        {expanded && hasDetail && (
          <div style={{ marginTop: 8, borderLeft: `2px solid ${ev.color}33`, paddingLeft: 10 }}>
            {ev.detail!.map((d, i) => (
              <div key={i} style={{ marginBottom: 8, padding: '6px 10px', background: '#f8f9fa', borderRadius: 6, fontSize: 12 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap', marginBottom: 3 }}>
                  <code style={{ fontSize: 11, color: '#1f77b4' }}>{d.resource_id}</code>
                  <span style={{ fontSize: 10, color: '#9e9e9e' }}>{d.resource_type}</span>
                  {d.decision && d.decision !== '—' && (
                    <Chip label={d.decision} style={DECISION_CHIP[d.decision] ?? { bg: '#e9ecef', color: '#495057' }} />
                  )}
                  {d.outcome && d.outcome !== '—' && (
                    <Chip label={d.outcome} style={OUTCOME_CHIP[d.outcome] ?? { bg: '#e9ecef', color: '#495057' }} />
                  )}
                  {d.savings != null && (
                    <span style={{ marginLeft: 'auto', fontWeight: 600, color: '#2e7d32', fontSize: 11 }}>
                      ${d.savings.toFixed(0)}/mo
                    </span>
                  )}
                </div>
                {d.reasoning && d.reasoning !== '—' && (
                  <div style={{ color: '#6c757d', fontSize: 11, lineHeight: 1.45, fontStyle: 'italic' }}>
                    {d.reasoning}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

export function AgentTrace({ runId, active }: Props) {
  const [open, setOpen]           = useState(true)
  const [events, setEvents]       = useState<TraceEvent[]>([])
  const [status, setStatus]       = useState<string>('')
  const timerRef                  = useRef<ReturnType<typeof setInterval> | null>(null)
  const bottomRef                 = useRef<HTMLDivElement>(null)
  const scrollRef                 = useRef<HTMLDivElement>(null)
  const [pinBottom, setPinBottom] = useState(true)
  const offsetRef                 = useRef(0)

  const fetchEvents = useCallback(async (id: string) => {
    try {
      const data = await getRunEvents(id, offsetRef.current)
      if (data.events.length > 0) {
        setEvents(prev => [...prev, ...data.events])
        offsetRef.current = data.total
      }
      setStatus(data.status)
    } catch {
      // silently ignore — polling will retry
    }
  }, [])

  // Reset + start/stop polling when runId changes
  useEffect(() => {
    if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null }
    setEvents([])
    setStatus('')
    setPinBottom(true)
    offsetRef.current = 0

    if (!runId) return

    fetchEvents(runId)
    if (active) {
      timerRef.current = setInterval(() => fetchEvents(runId), 1500)
    }
    return () => {
      if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null }
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId])

  // When active flips false, stop interval + final fetch
  useEffect(() => {
    if (!active) {
      if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null }
      if (runId) setTimeout(() => fetchEvents(runId), 800)
    } else if (runId && !timerRef.current) {
      timerRef.current = setInterval(() => fetchEvents(runId), 1500)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active])

  // Auto-scroll to latest
  useEffect(() => {
    if (pinBottom && bottomRef.current) {
      bottomRef.current.scrollIntoView({ behavior: 'smooth' })
    }
  }, [events, pinBottom])

  function handleScroll() {
    const el = scrollRef.current
    if (!el) return
    setPinBottom(el.scrollHeight - el.scrollTop - el.clientHeight < 24)
  }

  if (!runId) return null

  const isDone = status === 'complete' || status === 'error'
  const isRunning = status === 'scanning' || status === 'executing'

  return (
    <div style={{
      position: 'fixed', bottom: 24, right: 24, zIndex: 900,
      width: open ? 420 : 180,
      background: '#fff', borderRadius: 10,
      border: '1px solid #dee2e6',
      boxShadow: '0 4px 24px rgba(0,0,0,0.13)',
      transition: 'width 0.2s',
      display: 'flex', flexDirection: 'column',
      maxHeight: open ? 480 : 'auto',
    }}>
      {/* Header */}
      <div
        onClick={() => setOpen(v => !v)}
        style={{
          display: 'flex', alignItems: 'center', gap: 8,
          padding: '10px 14px', cursor: 'pointer',
          borderBottom: open ? '1px solid #f0f0f0' : 'none',
          borderRadius: open ? '10px 10px 0 0' : 10,
          background: 'linear-gradient(90deg, #1f3c6e 0%, #1f77b4 100%)',
          color: '#fff', userSelect: 'none',
        }}
      >
        {isRunning
          ? <div style={{ width: 10, height: 10, borderRadius: '50%', border: '2px solid #fff', borderTopColor: 'transparent', animation: 'spin 0.9s linear infinite', flexShrink: 0 }} />
          : <span style={{ fontSize: 13 }}>{isDone ? '✅' : '🐕'}</span>
        }
        <span style={{ fontWeight: 700, fontSize: 13, flex: 1 }}>Agent Trace</span>
        <span style={{ fontSize: 11, opacity: 0.8 }}>{events.length} event{events.length !== 1 ? 's' : ''}</span>
        <span style={{ fontSize: 13, opacity: 0.8, marginLeft: 6 }}>{open ? '▼' : '▲'}</span>
      </div>

      {open && (
        <>
          <div ref={scrollRef} onScroll={handleScroll} style={{ flex: 1, overflowY: 'auto', padding: '12px 14px', maxHeight: 400 }}>
            {events.length === 0
              ? <div style={{ color: '#9e9e9e', fontSize: 12, textAlign: 'center', padding: '20px 0' }}>
                  {isRunning ? 'Waiting for agent events…' : 'No events yet.'}
                </div>
              : events.map((ev, i) => <EventRow key={i} ev={ev} isLast={i === events.length - 1} />)
            }
            <div ref={bottomRef} />
          </div>

          <div style={{ padding: '6px 14px', borderTop: '1px solid #f0f0f0', display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: 11, color: '#9e9e9e' }}>
            <span>{isRunning ? 'Live · polling every 1.5s' : isDone ? `Done · ${events.length} events` : ''}</span>
            {!pinBottom && (
              <button onClick={() => { setPinBottom(true); bottomRef.current?.scrollIntoView({ behavior: 'smooth' }) }}
                style={{ fontSize: 11, border: 'none', background: 'none', cursor: 'pointer', color: '#1f77b4', padding: 0 }}>
                ↓ Jump to latest
              </button>
            )}
          </div>
        </>
      )}
    </div>
  )
}
