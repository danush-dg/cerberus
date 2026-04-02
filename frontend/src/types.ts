export interface CostBreakdownRow {
  owner_email: string
  cost_usd: number
}

export interface ProjectCostSummary {
  project_id: string
  total_usd: number
  attributed_usd: number
  unattributed_usd: number
  period: string
  breakdown: CostBreakdownRow[]
}

export interface UserCostResource {
  resource_id: string
  resource_type: string
  cost_usd: number
}

export interface UserCostSummary {
  owner_email: string
  project_id: string
  total_usd: number
  resource_count: number
  resources: UserCostResource[]
}

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

export type NavSection = 'dashboard' | 'iam' | 'cost' | 'security' | 'tickets'

export interface IamPlan {
  requester_email: string
  project_id?: string
  // user-supplied GCP role (e.g. "roles/storage.objectViewer")
  role?: string
  // legacy field from old synthesize endpoint — kept for ticket display fallback
  custom_role_id?: string
  permissions: string[]
  justification?: string
  reasoning?: string
  binding_condition?: string
  budget_alert_threshold_usd?: number
  review_after_days?: number
  checklist?: string[]
}

export interface IamTicket {
  id: string
  ts: string
  plan: IamPlan
  status: 'pending' | 'approved' | 'rejected' | 'provisioned'
}

export interface IdentityRecord {
  email: string
  role: string
  project_id: string
  status: 'active' | 'stale' | 'departed'
  last_activity: string | null
  days_inactive: number | null
}

export interface SecurityAlert {
  id: string
  type: 'over_permission' | 'idle_resource' | 'budget_breach' | 'departed_owner'
  severity: 'high' | 'medium' | 'low'
  message: string
  resource: string
  ts: string
}

export const MOCK_IDENTITY_DATA: IdentityRecord[] = [
  {
    email: 'alice.chen@nexus-tech.com',
    role: 'roles/bigquery.dataEditor',
    project_id: 'nexus-tech-dev-sandbox',
    status: 'active',
    last_activity: '2026-03-30',
    days_inactive: 1,
  },
  {
    email: 'bob.wilson@nexus-tech.com',
    role: 'roles/owner',
    project_id: 'nexus-tech-dev-sandbox',
    status: 'stale',
    last_activity: '2025-11-15',
    days_inactive: 136,
  },
  {
    email: 'carol.martinez@nexus-tech.com',
    role: 'roles/editor',
    project_id: 'nexus-tech-dev-sandbox',
    status: 'stale',
    last_activity: '2025-12-01',
    days_inactive: 120,
  },
  {
    email: 'svc-ml-pipeline@nexus-tech-dev-sandbox.iam.gserviceaccount.com',
    role: 'roles/aiplatform.user',
    project_id: 'nexus-tech-dev-sandbox',
    status: 'active',
    last_activity: '2026-03-29',
    days_inactive: 2,
  },
  {
    email: 'david.kim@nexus-tech.com',
    role: 'roles/storage.admin',
    project_id: 'nexus-tech-dev-sandbox',
    status: 'stale',
    last_activity: '2026-01-05',
    days_inactive: 85,
  },
  {
    email: 'svc-cerberus-agent@nexus-tech-dev-sandbox.iam.gserviceaccount.com',
    role: 'roles/compute.viewer',
    project_id: 'nexus-tech-dev-sandbox',
    status: 'active',
    last_activity: '2026-03-31',
    days_inactive: 0,
  },
  {
    email: 'eve.johnson@nexus-tech.com',
    role: 'roles/owner',
    project_id: 'nexus-tech-dev-sandbox',
    status: 'departed',
    last_activity: '2024-08-20',
    days_inactive: 589,
  },
  {
    email: 'frank.nguyen@nexus-tech.com',
    role: 'roles/compute.instanceAdmin',
    project_id: 'nexus-tech-dev-sandbox',
    status: 'active',
    last_activity: '2026-03-25',
    days_inactive: 6,
  },
  {
    email: 'svc-data-pipeline@nexus-tech-dev-sandbox.iam.gserviceaccount.com',
    role: 'roles/bigquery.jobUser',
    project_id: 'nexus-tech-dev-sandbox',
    status: 'active',
    last_activity: '2026-03-30',
    days_inactive: 1,
  },
  {
    email: 'grace.lee@nexus-tech.com',
    role: 'roles/logging.viewer',
    project_id: 'nexus-tech-dev-sandbox',
    status: 'stale',
    last_activity: '2025-12-10',
    days_inactive: 111,
  },
]
