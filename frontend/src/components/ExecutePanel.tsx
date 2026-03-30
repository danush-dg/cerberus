import { useState } from 'react'

export interface ExecutePanelProps {
  approvedCount: number
  dryRun: boolean
  onToggleDryRun: () => void
  onExecute: () => void
  revalidationStatus: 'idle' | 'running' | 'complete' | 'drift_detected'
  langsmithTraceUrl: string | null
}

export function ExecutePanel({
  approvedCount,
  dryRun,
  onToggleDryRun,
  onExecute,
  revalidationStatus,
  langsmithTraceUrl,
}: ExecutePanelProps) {
  const [modalOpen, setModalOpen] = useState(false)

  function handleExecuteClick() {
    if (!dryRun) {
      setModalOpen(true)
    } else {
      onExecute()
    }
  }

  function handleConfirmExecute() {
    setModalOpen(false)
    onExecute()
  }

  function handleCancelModal() {
    setModalOpen(false)
  }

  return (
    <div>
      {/* Dry-run toggle */}
      <label style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
        <input
          type="checkbox"
          checked={dryRun}
          onChange={onToggleDryRun}
          aria-label="Dry run mode"
        />
        Dry run mode
      </label>

      {/* Revalidation status bar */}
      {revalidationStatus === 'running' && (
        <div style={{ marginBottom: 8 }}>
          <span aria-label="loading" role="status">⟳</span>
          {' Verifying current resource state...'}
        </div>
      )}
      {revalidationStatus === 'complete' && (
        <div style={{ marginBottom: 8, color: '#155724' }}>
          State verified — ready to execute
        </div>
      )}
      {revalidationStatus === 'drift_detected' && (
        <div style={{ marginBottom: 8, color: '#856404' }}>
          Resources changed state since approval — plan updated
        </div>
      )}

      {/* Execute button — INV-UI-02 */}
      <button
        disabled={approvedCount === 0}
        onClick={handleExecuteClick}
        style={
          approvedCount === 0
            ? { opacity: 0.4, cursor: 'not-allowed' }
            : undefined
        }
      >
        Execute ({approvedCount})
      </button>

      {/* LangSmith section — always rendered, never hidden — INV-NFR-03 gap closure */}
      <div style={{ marginTop: 16 }}>
        {langsmithTraceUrl !== null ? (
          <a href={langsmithTraceUrl}>View reasoning trace in LangSmith</a>
        ) : (
          <span role="status">
            LangSmith trace unavailable — local audit log is the authoritative record
          </span>
        )}
      </div>

      {/* Live-execution confirmation modal — INV-UI-03 */}
      {modalOpen && (
        <div role="dialog" aria-modal="true">
          <p>
            You are about to execute {approvedCount} live GCP action(s).
            This will modify real infrastructure. This cannot be undone.
          </p>
          <button onClick={handleCancelModal}>Cancel</button>
          <button onClick={handleConfirmExecute}>Execute live</button>
        </div>
      )}
    </div>
  )
}
