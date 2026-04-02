# Cerberus Demoflow

## Demo Walkthrough: Resource Cleanup Workflow

### 1. **Scan Initiation (`scan_node`)**
The user clicks "Analyze" from the Frontend. The backend starts a new agent invocation, calling the `scan_node`.
- **Action**: Lists all VM instances, Cloud SQL instances, Disks, and Static IPs in the specified `dev-*` GCP project.
- **Output**: JSON list of resource IDs and basic metadata.

### 2. **Enrichment (`enrich_node`)**
The agent calls the `enrich_node`.
- **Action**: Correlates each resource with IAM labels (`owner`, `created-by`), the resource's last activity timestamp (from Cloud Audit Logs), and its current daily cost.
- **Output**: Enriched resource context.

### 3. **Reasoning (`reason_node`)**
The agent calls the `reason_node` with Gemini 1.5 Pro.
- **Action**: For each resource, the LLM evaluates the ownership against current IAM membership. If the owner is departed or the resource is idle for >90 days, it's classified as `safe_to_delete` or `safe_to_stop`.
- **Output**: Structured JSON output with `decision`, `reasoning`, and `estimated_monthly_saving`.

### 4. **Human Approval Gate (`approve_node`)**
The agent invocation **interrupts** and waits.
- **Action**: The frontend displays an approval table. The user reviews each classified resource (e.g., "This VM is $50/mo and its owner left NexusTech 4 months ago").
- **Action**: The user selects specific rows to approve/reject.

### 5. **Execution (`execute_node`)**
The user clicks "Execute Selected". The agent invocation **resumes**.
- **Action**: The `revalidate_node` first re-checks if any resource state has changed (e.g., a "stopped" VM was started manually since the scan).
- **Action**: The `execute_node` performs the live mutations via GCP APIs (Stop VM, Delete Disk).
- **Action**: The `audit_node` logs everything, and the user sees a "Summary of Recovered Savings" on the UI.

---

## Demo Walkthrough: IAM Access Head Workflow

### 1. **Access Request Submission**
A new team member goes to the "Request Access" tab and enters:
"I need read-only access to BigQuery for project development-sandbox-3."

### 2. **Permission Synthesis**
The backend calls the IAM Head. Gemini 1.5 Pro decomposes the request into its minimum-privilege components.
- **Justification**: "Granting BigQuery data viewer access as requested for sandbox development."
- **Permissions**: `bigquery.datasets.get`, `bigquery.tables.get`, `bigquery.tables.getData`, `bigquery.jobs.create`.

### 3. **Ticket Creation & Approval**
A new ticket is created and stored in the "Admin Queue".
- **Action**: An administrator reviews the ticket on their dashboard.
- **Action**: Admin clicks "Approve & Provision".

### 4. **Live Provisioning**
The IAM Head calls the GCP IAM API.
- **Action**: Dynamically creates a **Project-Level Custom Role** with ONLY the synthesized permissions.
- **Action**: Binds that custom role to the requester's identity.
- **Action**: Updates the persistent history in ChromaDB.
