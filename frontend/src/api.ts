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
  status: 'pending' | 'approved' | 'rejected' | 'provisioned'
}

export interface CostBreakdownRow {
  owner_email: string
  cost_usd: number
}

export interface ProjectResourceRecord {
  resource_id: string
  resource_type: string
  region: string
  owner_email: string
  ownership_status: string
  decision: string
  reasoning: string | null
  estimated_monthly_cost: number
  estimated_monthly_savings: number
}

export interface ExecuteResourceResponse {
  outcome: string
  resource_id: string
  action: string
  detail: string
}

export interface IAMBindingResponse {
  identity: string
  role: string
  project_id: string
  binding_type: string
  status: string
  last_activity: string | null
  days_inactive: string
}

export interface ProjectCostSummaryResponse {
  project_id: string
  total_usd: number
  attributed_usd: number
  unattributed_usd: number
  period: string
  breakdown: CostBreakdownRow[]
  resources: ProjectResourceRecord[]
}

export interface UserCostResourceResponse {
  resource_id: string
  resource_type: string
  cost_usd: number
}

export interface UserCostSummaryResponse {
  owner_email: string
  project_id: string
  total_usd: number
  resource_count: number
  resources: UserCostResourceResponse[]
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

export interface TraceEvent {
  type: 'node_start' | 'node_end' | string
  node: string
  icon: string
  color: string
  ts: string
  message: string
  detail?: Array<{
    resource_id: string
    resource_type: string
    decision?: string
    reasoning?: string
    savings?: number | null
    outcome?: string
  }>
}

export interface RunEventsResponse {
  run_id: string
  status: string
  total: number
  events: TraceEvent[]
}

export async function getRunEvents(runId: string, offset: number = 0): Promise<RunEventsResponse> {
  const res = await fetch(`${API_BASE}/run/${runId}/events?offset=${offset}`)
  return handleResponse<RunEventsResponse>(res)
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
  await handleResponse<void>(res)
}

export interface ProvisionResult {
  status: 'DRY_RUN' | 'SUCCESS' | 'FAILED'
  role?: string
  error?: string
}

export async function provisionTicket(
  ticketId: string,
  dryRun: boolean,
): Promise<ProvisionResult> {
  const res = await fetch(`${API_BASE}/tickets/${ticketId}/provision`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ dry_run: dryRun }),
  })
  return handleResponse<ProvisionResult>(res)
}

// ---------------------------------------------------------------------------
// Cost endpoints (Task 10.3)
// ---------------------------------------------------------------------------

export async function getProjectCostSummary(
  projectId: string,
): Promise<ProjectCostSummaryResponse> {
  const res = await fetch(`${API_BASE}/cost/project/${encodeURIComponent(projectId)}`)
  return handleResponse<ProjectCostSummaryResponse>(res)
}

export async function getUserCostSummary(
  ownerEmail: string,
  projectId: string,
): Promise<UserCostSummaryResponse> {
  const params = new URLSearchParams({ owner_email: ownerEmail, project_id: projectId })
  const res = await fetch(`${API_BASE}/cost/user?${params}`)
  return handleResponse<UserCostSummaryResponse>(res)
}

export async function getRecentProjects(): Promise<string[]> {
  const res = await fetch(`${API_BASE}/cost/projects`)
  const data = await handleResponse<{ project_ids: string[] }>(res)
  return data.project_ids
}

export async function executeResourceAction(
  resourceId: string,
  resourceType: string,
  decision: string,
  projectId: string,
  dryRun: boolean,
): Promise<ExecuteResourceResponse> {
  const res = await fetch(`${API_BASE}/cost/resource/execute`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      resource_id: resourceId,
      resource_type: resourceType,
      decision: decision,
      project_id: projectId,
      dry_run: dryRun,
    }),
  })
  return handleResponse<ExecuteResourceResponse>(res)
}

// ---------------------------------------------------------------------------
// IAM inventory endpoint (Task 10.2)
// ---------------------------------------------------------------------------

export async function getIamInventory(projectId: string): Promise<IAMBindingResponse[]> {
  const res = await fetch(`${API_BASE}/iam/inventory?project_id=${encodeURIComponent(projectId)}`)
  return handleResponse<IAMBindingResponse[]>(res)
}
