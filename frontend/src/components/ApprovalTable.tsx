import React from 'react'
import { ResourceRow } from '../types'

// ---------------------------------------------------------------------------
// Decision badge styling — INV-UI-01
// ---------------------------------------------------------------------------

const DECISION_STYLES: Record<string, { background: string; color: string }> = {
  safe_to_stop:   { background: '#FFF3CD', color: '#856404' },
  safe_to_delete: { background: '#F8D7DA', color: '#721C24' },
  needs_review:   { background: '#E2E3E5', color: '#383D41' },
  skip:           { background: '#CCE5FF', color: '#004085' },
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const EM_DASH = '—'

function display(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === '') return EM_DASH
  return String(value)
}

function truncate(text: string, max = 80): string {
  return text.length <= max ? text : text.slice(0, max) + '...'
}

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface ApprovalTableProps {
  resources: ResourceRow[]
  approvedIds: Set<string>
  onApprove: (id: string) => void
  onReject: (id: string) => void
}

// ---------------------------------------------------------------------------
// Component — INV-UI-01, INV-ENR-03 (4th enforcement point)
// ---------------------------------------------------------------------------

export function ApprovalTable({
  resources,
  approvedIds,
  onApprove,
  onReject,
}: ApprovalTableProps) {
  // Total recoverable: sum savings for approvedIds only
  const total = resources.reduce((sum, r) => {
    if (approvedIds.has(r.resource_id) && r.estimated_monthly_savings != null) {
      return sum + r.estimated_monthly_savings
    }
    return sum
  }, 0)

  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '14px' }}>
        <thead>
          <tr style={{ borderBottom: '2px solid #dee2e6', textAlign: 'left' }}>
            <th style={thStyle}>Resource Name</th>
            <th style={thStyle}>Type</th>
            <th style={thStyle}>Region</th>
            <th style={thStyle}>Owner</th>
            <th style={thStyle}>Ownership Status</th>
            <th style={thStyle}>Decision</th>
            <th style={thStyle}>Reasoning</th>
            <th style={thStyle}>Est. Savings ($/mo)</th>
            <th style={thStyle}>Action</th>
          </tr>
        </thead>
        <tbody>
          {resources.map((r) => {
            const isApproved = approvedIds.has(r.resource_id)
            const isNoOwner = r.ownership_status === 'no_owner'
            const decisionStyle = r.decision ? DECISION_STYLES[r.decision] : undefined
            const reasoningText = r.reasoning ?? ''

            return (
              <tr
                key={r.resource_id}
                style={{ borderBottom: '1px solid #dee2e6', background: isApproved ? '#f0fff0' : 'white' }}
              >
                {/* Resource Name */}
                <td style={tdStyle}>{display(r.resource_id)}</td>

                {/* Type */}
                <td style={tdStyle}>{display(r.resource_type)}</td>

                {/* Region */}
                <td style={tdStyle}>{display(r.region)}</td>

                {/* Owner */}
                <td style={tdStyle}>{display(r.owner_email)}</td>

                {/* Ownership Status */}
                <td style={tdStyle}>{display(r.ownership_status)}</td>

                {/* Decision badge */}
                <td style={tdStyle}>
                  {r.decision ? (
                    <span
                      style={{
                        padding: '2px 8px',
                        borderRadius: '4px',
                        fontSize: '12px',
                        fontWeight: 600,
                        background: decisionStyle?.background,
                        color: decisionStyle?.color,
                      }}
                    >
                      {r.decision}
                    </span>
                  ) : (
                    EM_DASH
                  )}
                </td>

                {/* Reasoning — truncated with full text in tooltip */}
                <td style={{ ...tdStyle, maxWidth: '260px' }}>
                  {reasoningText ? (
                    <span title={reasoningText}>{truncate(reasoningText)}</span>
                  ) : (
                    EM_DASH
                  )}
                </td>

                {/* Est. Savings */}
                <td style={tdStyle}>
                  {r.estimated_monthly_savings != null
                    ? `$${r.estimated_monthly_savings.toFixed(2)}`
                    : EM_DASH}
                </td>

                {/* Action — INV-ENR-03: Approve disabled for no_owner */}
                <td style={{ ...tdStyle, whiteSpace: 'nowrap' }}>
                  <button
                    onClick={() => onApprove(r.resource_id)}
                    disabled={isNoOwner}
                    style={{
                      marginRight: '6px',
                      padding: '4px 10px',
                      background: isApproved ? '#6c757d' : '#28a745',
                      color: 'white',
                      border: 'none',
                      borderRadius: '4px',
                      cursor: isNoOwner ? 'not-allowed' : 'pointer',
                      opacity: isNoOwner ? 0.5 : 1,
                    }}
                  >
                    {isApproved ? 'Approved' : 'Approve'}
                  </button>
                  {isApproved && (
                    <button
                      onClick={() => onReject(r.resource_id)}
                      style={{
                        padding: '4px 10px',
                        background: '#dc3545',
                        color: 'white',
                        border: 'none',
                        borderRadius: '4px',
                        cursor: 'pointer',
                      }}
                    >
                      Reject
                    </button>
                  )}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>

      {/* Total recoverable */}
      <p style={{ marginTop: '12px', fontWeight: 600 }}>
        Total recoverable: ${total.toFixed(2)}/month
      </p>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Shared cell styles
// ---------------------------------------------------------------------------

const thStyle: React.CSSProperties = {
  padding: '10px 12px',
  fontWeight: 700,
  whiteSpace: 'nowrap',
}

const tdStyle: React.CSSProperties = {
  padding: '8px 12px',
  verticalAlign: 'top',
}

export default ApprovalTable
