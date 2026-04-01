// ---------------------------------------------------------------------------
// API client — all calls proxied via Vite dev server → FastAPI on :8000
// ---------------------------------------------------------------------------

const API_BASE = '/api'

// ---------------------------------------------------------------------------
// Response shapes
// ---------------------------------------------------------------------------

export interface RunResponse {
  run_id: string
}

export interface ResourceRecord {
  resource_id: string
  resource_type: string
  region: string
  owner_email: string | null
  ownership_status: string | null
  decision: string | null
  reasoning: string | null
  estimated_monthly_savings: number | null
  estimated_monthly_cost: number | null
  flagged_for_review: boolean
  outcome: string | null
}

export interface PlanResponse {
  status: string
  plan: ResourceRecord[] | null
}

export interface StatusResponse {
  run_id: string
  status: string
  resources: ResourceRecord[]
  error_message: string | null
  run_complete: boolean
  dry_run: boolean
  langsmith_trace_url: string | null
  mutation_count: number
}

export interface RunSummary {
  resources_scanned: number
  total_waste_identified: number
  actions_approved: number
  actions_executed: number
  estimated_monthly_savings_recovered: number
}

export interface IamTicketResponse {
  id: string
  ts: string
  plan: Record<string, unknown>
  status: 'pending' | 'approved' | 'rejected'
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let message = `HTTP ${res.status}`
    try {
      const body = await res.json()
      message = body.error ?? message
    } catch {
      // ignore parse error — keep the status string
    }
    throw new Error(message)
  }
  return res.json() as Promise<T>
}

// ---------------------------------------------------------------------------
// Run endpoints
// ---------------------------------------------------------------------------

export async function startRun(
  projectId: string,
  dryRun: boolean,
): Promise<RunResponse> {
  const res = await fetch(`${API_BASE}/run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ project_id: projectId, dry_run: dryRun }),
  })
  return handleResponse<RunResponse>(res)
}

export async function pollPlan(runId: string): Promise<PlanResponse> {
  const res = await fetch(`${API_BASE}/run/${runId}/plan`)
  return handleResponse<PlanResponse>(res)
}

export async function approvePlan(
  runId: string,
  approvedIds: string[],
): Promise<void> {
  const res = await fetch(`${API_BASE}/run/${runId}/approve`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ approved_ids: approvedIds }),
  })
  return handleResponse<void>(res)
}

export async function getStatus(runId: string): Promise<StatusResponse> {
  const res = await fetch(`${API_BASE}/run/${runId}/status`)
  return handleResponse<StatusResponse>(res)
}

export async function getSummary(runId: string): Promise<RunSummary> {
  const res = await fetch(`${API_BASE}/run/${runId}/summary`)
  return handleResponse<RunSummary>(res)
}

// ---------------------------------------------------------------------------
// IAM ticket endpoints
// ---------------------------------------------------------------------------

export async function submitTicket(plan: Record<string, unknown>): Promise<{ id: string }> {
  const res = await fetch(`${API_BASE}/iam/tickets`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ plan }),
  })
  return handleResponse<{ id: string }>(res)
}

export async function getTickets(): Promise<IamTicketResponse[]> {
  const res = await fetch(`${API_BASE}/iam/tickets`)
  return handleResponse<IamTicketResponse[]>(res)
}

export async function reviewTicket(
  ticketId: string,
  action: 'approved' | 'rejected',
): Promise<void> {
  const res = await fetch(`${API_BASE}/iam/tickets/${ticketId}/review`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action }),
  })
  return handleResponse<void>(res)
}
