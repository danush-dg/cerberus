import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi } from 'vitest'
import { ApprovalTable } from './ApprovalTable'
import { ResourceRow } from '../types'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function mockResource(overrides: Partial<ResourceRow> = {}): ResourceRow {
  return {
    resource_id: 'vm-test-1',
    resource_type: 'vm',
    region: 'us-central1',
    owner_email: 'owner@nexus.tech',
    ownership_status: 'active_owner',
    decision: 'safe_to_stop',
    reasoning: 'CPU utilisation averaged 2% over 72 hours, costing $45/mo with no active owner.',
    estimated_monthly_savings: 45.0,
    ...overrides,
  }
}

const noop = () => {}

// ---------------------------------------------------------------------------
// INV-UI-01: All 9 columns must be rendered
// ---------------------------------------------------------------------------

describe('ApprovalTable — column headers', () => {
  it('renders all 9 required columns', () => {
    render(
      <ApprovalTable
        resources={[mockResource()]}
        approvedIds={new Set()}
        onApprove={noop}
        onReject={noop}
      />
    )
    const cols = [
      'Resource Name',
      'Type',
      'Region',
      'Owner',
      'Ownership Status',
      'Decision',
      'Reasoning',
      'Est. Savings ($/mo)',
      'Action',
    ]
    for (const col of cols) {
      expect(screen.getByText(col)).toBeInTheDocument()
    }
  })
})

// ---------------------------------------------------------------------------
// INV-UI-01: null / undefined fields render em-dash
// ---------------------------------------------------------------------------

describe('ApprovalTable — null field rendering', () => {
  it('renders em-dash for null owner_email', () => {
    render(
      <ApprovalTable
        resources={[mockResource({ owner_email: null })]}
        approvedIds={new Set()}
        onApprove={noop}
        onReject={noop}
      />
    )
    expect(screen.getAllByText('—').length).toBeGreaterThan(0)
  })

  it('renders em-dash for null decision', () => {
    render(
      <ApprovalTable
        resources={[mockResource({ decision: null })]}
        approvedIds={new Set()}
        onApprove={noop}
        onReject={noop}
      />
    )
    expect(screen.getAllByText('—').length).toBeGreaterThan(0)
  })

  it('renders em-dash for null estimated_monthly_savings', () => {
    render(
      <ApprovalTable
        resources={[mockResource({ estimated_monthly_savings: null })]}
        approvedIds={new Set()}
        onApprove={noop}
        onReject={noop}
      />
    )
    expect(screen.getAllByText('—').length).toBeGreaterThan(0)
  })

  it('renders em-dash for null reasoning', () => {
    render(
      <ApprovalTable
        resources={[mockResource({ reasoning: null })]}
        approvedIds={new Set()}
        onApprove={noop}
        onReject={noop}
      />
    )
    expect(screen.getAllByText('—').length).toBeGreaterThan(0)
  })
})

// ---------------------------------------------------------------------------
// INV-ENR-03: Approve button disabled for no_owner (4th enforcement point)
// ---------------------------------------------------------------------------

describe('ApprovalTable — no_owner guardrail', () => {
  it('disables Approve button when ownership_status is no_owner', () => {
    render(
      <ApprovalTable
        resources={[mockResource({ ownership_status: 'no_owner' })]}
        approvedIds={new Set()}
        onApprove={noop}
        onReject={noop}
      />
    )
    expect(screen.getByRole('button', { name: /approve/i })).toBeDisabled()
  })

  it('enables Approve button when ownership_status is active_owner', () => {
    render(
      <ApprovalTable
        resources={[mockResource({ ownership_status: 'active_owner' })]}
        approvedIds={new Set()}
        onApprove={noop}
        onReject={noop}
      />
    )
    expect(screen.getByRole('button', { name: /approve/i })).not.toBeDisabled()
  })
})

// ---------------------------------------------------------------------------
// Total recoverable — approvedIds only
// ---------------------------------------------------------------------------

describe('ApprovalTable — total recoverable', () => {
  it('shows $0.00 when nothing is approved', () => {
    const r = mockResource({ resource_id: 'vm-1', estimated_monthly_savings: 45.0 })
    render(
      <ApprovalTable
        resources={[r]}
        approvedIds={new Set()}
        onApprove={noop}
        onReject={noop}
      />
    )
    expect(screen.getByText(/Total recoverable: \$0\.00\/month/)).toBeInTheDocument()
  })

  it('updates total when resource is in approvedIds', () => {
    const r = mockResource({ resource_id: 'vm-1', estimated_monthly_savings: 45.0 })
    const { rerender } = render(
      <ApprovalTable
        resources={[r]}
        approvedIds={new Set()}
        onApprove={noop}
        onReject={noop}
      />
    )
    expect(screen.getByText(/Total recoverable: \$0\.00\/month/)).toBeInTheDocument()

    rerender(
      <ApprovalTable
        resources={[r]}
        approvedIds={new Set(['vm-1'])}
        onApprove={noop}
        onReject={noop}
      />
    )
    expect(screen.getByText(/Total recoverable: \$45\.00\/month/)).toBeInTheDocument()
  })

  it('sums savings from multiple approved resources', () => {
    const resources = [
      mockResource({ resource_id: 'vm-1', estimated_monthly_savings: 45.0, reasoning: null }),
      mockResource({ resource_id: 'vm-2', estimated_monthly_savings: 30.0, reasoning: null }),
      mockResource({ resource_id: 'vm-3', estimated_monthly_savings: 20.0, reasoning: null }),
    ]
    render(
      <ApprovalTable
        resources={resources}
        approvedIds={new Set(['vm-1', 'vm-2'])}
        onApprove={noop}
        onReject={noop}
      />
    )
    // vm-1 + vm-2 = 75, not vm-3
    expect(screen.getByText(/Total recoverable: \$75\.00\/month/)).toBeInTheDocument()
  })

  it('excludes null savings from total', () => {
    const resources = [
      mockResource({ resource_id: 'vm-1', estimated_monthly_savings: 45.0, reasoning: null }),
      mockResource({ resource_id: 'vm-2', estimated_monthly_savings: null, reasoning: null }),
    ]
    render(
      <ApprovalTable
        resources={resources}
        approvedIds={new Set(['vm-1', 'vm-2'])}
        onApprove={noop}
        onReject={noop}
      />
    )
    expect(screen.getByText(/Total recoverable: \$45\.00\/month/)).toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------
// Decision badge colours
// ---------------------------------------------------------------------------

describe('ApprovalTable — decision badge', () => {
  it('renders safe_to_stop with amber badge', () => {
    render(
      <ApprovalTable
        resources={[mockResource({ decision: 'safe_to_stop' })]}
        approvedIds={new Set()}
        onApprove={noop}
        onReject={noop}
      />
    )
    const badge = screen.getByText('safe_to_stop')
    expect(badge).toHaveStyle({ background: '#FFF3CD', color: '#856404' })
  })

  it('renders safe_to_delete with red badge', () => {
    render(
      <ApprovalTable
        resources={[mockResource({ decision: 'safe_to_delete' })]}
        approvedIds={new Set()}
        onApprove={noop}
        onReject={noop}
      />
    )
    const badge = screen.getByText('safe_to_delete')
    expect(badge).toHaveStyle({ background: '#F8D7DA', color: '#721C24' })
  })
})

// ---------------------------------------------------------------------------
// Reasoning truncation
// ---------------------------------------------------------------------------

describe('ApprovalTable — reasoning truncation', () => {
  it('truncates long reasoning to 80 chars with ellipsis', () => {
    const longReasoning = 'A'.repeat(100)
    render(
      <ApprovalTable
        resources={[mockResource({ reasoning: longReasoning })]}
        approvedIds={new Set()}
        onApprove={noop}
        onReject={noop}
      />
    )
    const span = screen.getByTitle(longReasoning)
    expect(span.textContent).toHaveLength(83) // 80 + '...'
  })

  it('shows full reasoning in title tooltip', () => {
    const fullReasoning = 'CPU at 2% for 72h. Cost $45/mo. Owner departed 100 days ago.'
    render(
      <ApprovalTable
        resources={[mockResource({ reasoning: fullReasoning })]}
        approvedIds={new Set()}
        onApprove={noop}
        onReject={noop}
      />
    )
    expect(screen.getByTitle(fullReasoning)).toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------
// onApprove / onReject callbacks
// ---------------------------------------------------------------------------

describe('ApprovalTable — callbacks', () => {
  it('calls onApprove with resource_id when Approve clicked', async () => {
    const onApprove = vi.fn()
    render(
      <ApprovalTable
        resources={[mockResource({ resource_id: 'vm-42' })]}
        approvedIds={new Set()}
        onApprove={onApprove}
        onReject={noop}
      />
    )
    await userEvent.click(screen.getByRole('button', { name: /approve/i }))
    expect(onApprove).toHaveBeenCalledWith('vm-42')
  })

  it('calls onReject with resource_id when Reject clicked', async () => {
    const onReject = vi.fn()
    render(
      <ApprovalTable
        resources={[mockResource({ resource_id: 'vm-42' })]}
        approvedIds={new Set(['vm-42'])}
        onApprove={noop}
        onReject={onReject}
      />
    )
    await userEvent.click(screen.getByRole('button', { name: /reject/i }))
    expect(onReject).toHaveBeenCalledWith('vm-42')
  })
})
