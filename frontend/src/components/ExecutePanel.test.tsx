import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import { ExecutePanel } from './ExecutePanel'
import type { ExecutePanelProps } from './ExecutePanel'

const defaults: ExecutePanelProps = {
  approvedCount: 0,
  dryRun: true,
  onToggleDryRun: () => {},
  onExecute: () => {},
  revalidationStatus: 'idle',
  langsmithTraceUrl: null,
}

// ---------------------------------------------------------------------------
// INV-UI-02: Execute disabled when approvedCount === 0
// ---------------------------------------------------------------------------

describe('ExecutePanel — execute button disabled state', () => {
  it('execute disabled when no approvals', () => {
    render(<ExecutePanel {...defaults} approvedCount={0} dryRun={false} />)
    expect(screen.getByRole('button', { name: /execute/i })).toBeDisabled()
  })

  it('execute enabled when approvals > 0', () => {
    render(<ExecutePanel {...defaults} approvedCount={2} dryRun={true} />)
    expect(screen.getByRole('button', { name: /execute/i })).not.toBeDisabled()
  })
})

// ---------------------------------------------------------------------------
// INV-UI-03: Dry-run modal is the last human checkpoint
// ---------------------------------------------------------------------------

describe('ExecutePanel — live mode modal', () => {
  it('live mode shows modal before executing', async () => {
    const onExecute = vi.fn()
    render(
      <ExecutePanel
        {...defaults}
        approvedCount={1}
        dryRun={false}
        onExecute={onExecute}
      />
    )
    fireEvent.click(screen.getByRole('button', { name: /execute/i }))
    expect(screen.getByText(/live GCP action/i)).toBeInTheDocument()
    expect(onExecute).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: /execute live/i }))
    expect(onExecute).toHaveBeenCalledTimes(1)
  })

  it('cancel modal does not execute', () => {
    const onExecute = vi.fn()
    render(
      <ExecutePanel
        {...defaults}
        approvedCount={1}
        dryRun={false}
        onExecute={onExecute}
      />
    )
    fireEvent.click(screen.getByRole('button', { name: /execute/i }))
    fireEvent.click(screen.getByRole('button', { name: /cancel/i }))
    expect(onExecute).not.toHaveBeenCalled()
  })

  it('dry run mode calls onExecute directly without modal', () => {
    const onExecute = vi.fn()
    render(
      <ExecutePanel
        {...defaults}
        approvedCount={1}
        dryRun={true}
        onExecute={onExecute}
      />
    )
    fireEvent.click(screen.getByRole('button', { name: /execute/i }))
    expect(onExecute).toHaveBeenCalledTimes(1)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------
// LangSmith fallback — visible, not display:none
// ---------------------------------------------------------------------------

describe('ExecutePanel — LangSmith section', () => {
  it('langsmith null shows fallback not silence', () => {
    render(<ExecutePanel {...defaults} langsmithTraceUrl={null} />)
    expect(screen.getByRole('status')).toHaveTextContent(/local audit log/)
  })

  it('langsmith url renders link', () => {
    render(
      <ExecutePanel
        {...defaults}
        langsmithTraceUrl="https://smith.langchain.com/trace/abc123"
      />
    )
    expect(screen.getByRole('link', { name: /langsmith/i })).toHaveAttribute(
      'href',
      'https://smith.langchain.com/trace/abc123'
    )
  })
})

// ---------------------------------------------------------------------------
// Revalidation status bar
// ---------------------------------------------------------------------------

describe('ExecutePanel — revalidation status', () => {
  it('revalidation running shows spinner', () => {
    render(<ExecutePanel {...defaults} revalidationStatus="running" />)
    expect(screen.getByLabelText(/loading/i)).toBeInTheDocument()
  })

  it('idle renders nothing for revalidation', () => {
    render(<ExecutePanel {...defaults} revalidationStatus="idle" />)
    expect(screen.queryByText(/verifying/i)).not.toBeInTheDocument()
  })

  it('complete renders verified message', () => {
    render(<ExecutePanel {...defaults} revalidationStatus="complete" />)
    expect(screen.getByText(/state verified/i)).toBeInTheDocument()
  })

  it('drift_detected renders amber message', () => {
    render(<ExecutePanel {...defaults} revalidationStatus="drift_detected" />)
    expect(screen.getByText(/changed state since approval/i)).toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------
// Modal shows exact count
// ---------------------------------------------------------------------------

describe('ExecutePanel — modal count', () => {
  it('modal text includes exact approvedCount', () => {
    render(
      <ExecutePanel
        {...defaults}
        approvedCount={5}
        dryRun={false}
        onExecute={() => {}}
      />
    )
    fireEvent.click(screen.getByRole('button', { name: /execute/i }))
    expect(screen.getByText(/5 live GCP action/i)).toBeInTheDocument()
  })
})
