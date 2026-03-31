export interface ResourceRow {
  resource_id: string
  resource_type: string
  region: string
  owner_email: string | null
  ownership_status: string | null
  decision: string | null
  reasoning: string | null
  estimated_monthly_savings: number | null
  outcome: string | null
}

export type RevalidationStatus = 'idle' | 'running' | 'complete' | 'drift_detected'
