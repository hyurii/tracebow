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
