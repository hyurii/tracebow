export interface Failure {
  id: string;
  source: string;
  job_name?: string | null;
  build_number?: number | null;
  repo?: string | null;
  run_id?: number | null;
  status: string;
  triggered_at: string;
  rca_summary?: string | null;
}

export interface Stacktrace {
  id: string;
  excerpt: string;
  line_count: number;
  language?: string | null;
  full_text?: string | null;
  created_at?: string | null;
}

export interface CommitDiff {
  id: string;
  provider: string;
  ref?: string | null;
  files_changed: number;
  additions: number;
  deletions: number;
  patch?: string | null;
  truncated: boolean;
  created_at?: string | null;
}

export interface RcaReport {
  id: string;
  summary: string;
  branch_taken: string;
  wiki_doc_path?: string | null;
  wiki_doc_created?: boolean;
  model_used?: string | null;
  tool_trace?: Array<Record<string, unknown>> | null;
  latency_ms?: number | null;
  created_at?: string | null;
}

export interface FailureDetail extends Failure {
  pr_number?: string | null;
  commit_sha?: string | null;
  branch?: string | null;
  build_url?: string | null;
  task_id?: string | null;
  stacktraces: Stacktrace[];
  diffs?: CommitDiff[];
  rca?: RcaReport | null;
}

export interface WikiDoc {
  path: string;
  title: string;
  updated_at?: string | null;
  size_bytes?: number | null;
}

export interface WikiDocContent {
  path: string;
  title: string;
  content: string;
  updated_at?: string | null;
}

export interface WikiSearchHit {
  path: string;
  title: string;
  score: number;
  snippet: string;
}

export interface BackupSettings {
  enabled: boolean;
  remote_url?: string | null;
  branch: string;
  auto_backup_hours?: number | null;
  has_deploy_key: boolean;
  deploy_key_fingerprint?: string | null;
  last_backup_at?: string | null;
  last_backup_status?: string | null;
  last_backup_error?: string | null;
}

export interface BackupSettingsUpdate {
  enabled: boolean;
  remote_url?: string | null;
  branch?: string;
  auto_backup_hours?: number | null;
  /**
   * Raw SSH private key. Only send on save when rotating the key.
   * Never returned by the API.
   */
  deploy_key?: string | null;
}

export interface Repository {
  id: string;
  provider: string;
  identifier: string;
  display_name?: string | null;
  access_status: "allowed" | "denied" | "pending";
  auth_method: "none" | "github_pat" | "ssh_deploy_key" | "github_app" | "oauth";
  has_credential: boolean;
  credential_fingerprint?: string | null;
  last_seen_at?: string | null;
  created_at?: string | null;
}

export interface RepositoryUpdate {
  access_status?: "allowed" | "denied" | "pending";
  auth_method?: Repository["auth_method"];
  display_name?: string | null;
  credential?: string | null;
}

export interface AccessRequest {
  id: string;
  provider: string;
  identifier: string;
  repository_id?: string | null;
  reason?: string | null;
  status: "pending" | "approved" | "denied";
  requested_by: string;
  resolved_at?: string | null;
  created_at?: string | null;
}

export interface EgressEvent {
  id: string;
  destination_host: string;
  destination_kind: "internal" | "external";
  purpose?: string | null;
  method?: string | null;
  request_bytes: number;
  response_bytes: number;
  status?: string | null;
  sensitive_flags: string[];
  blocked: boolean;
  created_at?: string | null;
}

export interface SecuritySummary {
  posture: "internal_only" | "external_configured";
  external_integrations: string[];
  total_events: number;
  external_events: number;
  internal_events: number;
  sensitive_events: number;
  blocked_events: number;
  destinations: Array<{
    host: string;
    kind: "internal" | "external";
    count: number;
    last_seen?: string | null;
  }>;
}

export interface TaskAccepted {
  task_id: string;
  status: string;
}

export interface TaskStatus {
  task_id: string;
  status: string;
  result?: unknown;
  error?: string | null;
}
