import { useState } from 'react'

interface IamPlan {
  requester_email: string
  custom_role_id: string
  permissions: string[]
  binding_condition: string
  budget_alert_threshold_usd: number
  review_after_days: number
  checklist: string[]
  reasoning: string
}

type ApprovalState = 'idle' | 'pending' | 'approved' | 'rejected'

export function IamPanel() {
  const [requesterEmail, setRequesterEmail] = useState('')
  const [projectId, setProjectId]           = useState('')
  const [requestText, setRequestText]       = useState('')
  const [loading, setLoading]               = useState(false)
  const [error, setError]                   = useState<string | null>(null)
  const [plan, setPlan]                     = useState<IamPlan | null>(null)
  const [approval, setApproval]             = useState<ApprovalState>('idle')

  async function handleSynthesize() {
    if (!requesterEmail.trim() || !projectId.trim() || !requestText.trim()) return
    setLoading(true); setError(null); setPlan(null); setApproval('idle')
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
      setApproval('pending')
    } catch (e) {
      setError(String(e))
    } finally {
      setLoading(false)
    }
  }

  function handleReset() {
    setPlan(null); setApproval('idle'); setError(null)
    setRequesterEmail(''); setProjectId(''); setRequestText('')
  }

  return (
    <div style={card}>
      <h2 style={{ marginTop: 0, fontSize: 18, color: '#1a237e' }}>
        IAM Access Request
      </h2>
      <p style={{ color: '#555', fontSize: 13, marginBottom: 16 }}>
        Describe access in plain English. Cerberus synthesizes the minimum GCP
        permissions via Gemini and generates a 7-step provisioning checklist.
      </p>

      {/* Input form */}
      {approval === 'idle' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          <div style={row}>
            <label style={lbl}>Requester email</label>
            <input
              style={inp}
              placeholder="anurag@company.com"
              value={requesterEmail}
              onChange={e => setRequesterEmail(e.target.value)}
            />
          </div>
          <div style={row}>
            <label style={lbl}>Project ID</label>
            <input
              style={inp}
              placeholder="nexus-tech-dev-sandbox"
              value={projectId}
              onChange={e => setProjectId(e.target.value)}
            />
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
            style={{
              ...btn,
              background: loading ? '#90a4ae' : '#1a237e',
              cursor: loading ? 'not-allowed' : 'pointer',
            }}
            disabled={loading || !requesterEmail.trim() || !projectId.trim() || !requestText.trim()}
            onClick={handleSynthesize}
          >
            {loading ? 'Synthesizing...' : 'Synthesize IAM Plan →'}
          </button>
          {error && <div style={errBox}>{error}</div>}
        </div>
      )}

      {/* Plan — awaiting human approval */}
      {plan && approval === 'pending' && (
        <div>
          <div style={planHeader}>
            <span style={{ fontWeight: 700, color: '#1a237e' }}>Plan ready — awaiting your approval</span>
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
            <p style={{ margin: 0, fontSize: 13, color: '#333', fontStyle: 'italic' }}>
              {plan.reasoning}
            </p>
          </div>

          <div style={section}>
            <div style={sectionTitle}>Provisioning Checklist</div>
            <ol style={{ margin: '6px 0 0 18px', padding: 0, fontSize: 13, lineHeight: 1.7 }}>
              {plan.checklist.map((step, i) => (
                <li key={i} style={{ color: '#333' }}>{step}</li>
              ))}
            </ol>
          </div>

          <div style={section}>
            <div style={{ display: 'flex', gap: 6, fontSize: 12, color: '#666' }}>
              <span>Budget alert: <strong>${plan.budget_alert_threshold_usd}/mo</strong></span>
              <span>·</span>
              <span>Review in: <strong>{plan.review_after_days} days</strong></span>
            </div>
          </div>

          {/* Human approval gate */}
          <div style={approvalBar}>
            <span style={{ fontWeight: 600, fontSize: 14 }}>
              Human Approval Required
            </span>
            <div style={{ display: 'flex', gap: 8 }}>
              <button
                style={{ ...btn, background: '#2e7d32', padding: '8px 20px' }}
                onClick={() => setApproval('approved')}
              >
                Approve &amp; Provision
              </button>
              <button
                style={{ ...btn, background: '#c62828', padding: '8px 20px' }}
                onClick={() => setApproval('rejected')}
              >
                Reject
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Approved */}
      {plan && approval === 'approved' && (
        <div style={{ ...resultBox, borderColor: '#2e7d32', background: '#f1f8e9' }}>
          <div style={{ fontWeight: 700, color: '#2e7d32', marginBottom: 8 }}>
            Provisioning approved (dry-run)
          </div>
          <p style={{ margin: 0, fontSize: 13, color: '#333' }}>
            Role <code style={{ ...pill, background: '#c8e6c9' }}>{plan.custom_role_id}</code> would
            be created and bound to <strong>{plan.requester_email}</strong> with{' '}
            <strong>{plan.permissions.length} permission(s)</strong>.
            A 90-day review is scheduled. No live GCP call was made.
          </p>
          <button style={{ ...btn, marginTop: 14, background: '#455a64' }} onClick={handleReset}>
            New request
          </button>
        </div>
      )}

      {/* Rejected */}
      {plan && approval === 'rejected' && (
        <div style={{ ...resultBox, borderColor: '#c62828', background: '#ffebee' }}>
          <div style={{ fontWeight: 700, color: '#c62828', marginBottom: 8 }}>
            Request rejected
          </div>
          <p style={{ margin: 0, fontSize: 13, color: '#333' }}>
            The IAM provisioning plan for <strong>{plan.requester_email}</strong> was rejected.
            No changes were made.
          </p>
          <button style={{ ...btn, marginTop: 14, background: '#455a64' }} onClick={handleReset}>
            New request
          </button>
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Styles
// ---------------------------------------------------------------------------

const card: React.CSSProperties = {
  background: '#fff',
  border: '1px solid #e0e0e0',
  borderRadius: 8,
  padding: 24,
  marginTop: 24,
}

const row: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  gap: 4,
}

const lbl: React.CSSProperties = {
  fontSize: 12,
  fontWeight: 600,
  color: '#555',
  textTransform: 'uppercase',
  letterSpacing: '0.05em',
}

const inp: React.CSSProperties = {
  border: '1px solid #ccc',
  borderRadius: 4,
  padding: '8px 10px',
  fontSize: 14,
  fontFamily: 'inherit',
  width: '100%',
  boxSizing: 'border-box',
}

const btn: React.CSSProperties = {
  border: 'none',
  borderRadius: 4,
  padding: '10px 18px',
  color: '#fff',
  fontWeight: 600,
  fontSize: 14,
  cursor: 'pointer',
}

const pill: React.CSSProperties = {
  background: '#e3f2fd',
  color: '#1565c0',
  borderRadius: 4,
  padding: '2px 8px',
  fontSize: 12,
  fontFamily: 'monospace',
}

const section: React.CSSProperties = {
  marginTop: 16,
}

const sectionTitle: React.CSSProperties = {
  fontSize: 11,
  fontWeight: 700,
  color: '#888',
  textTransform: 'uppercase',
  letterSpacing: '0.06em',
  marginBottom: 4,
}

const planHeader: React.CSSProperties = {
  background: '#e8eaf6',
  borderRadius: 6,
  padding: '10px 14px',
  marginBottom: 16,
  border: '1px solid #c5cae9',
}

const approvalBar: React.CSSProperties = {
  marginTop: 20,
  padding: '14px 16px',
  background: '#fff3e0',
  border: '1px solid #ffcc02',
  borderRadius: 6,
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'space-between',
}

const errBox: React.CSSProperties = {
  background: '#ffebee',
  border: '1px solid #ef9a9a',
  borderRadius: 4,
  padding: '10px 12px',
  fontSize: 13,
  color: '#c62828',
  whiteSpace: 'pre-wrap',
}

const resultBox: React.CSSProperties = {
  border: '1px solid',
  borderRadius: 6,
  padding: 16,
}
