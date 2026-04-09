export interface Failure {
  id: string;
  source: string;
  job_name?: string;
  build_number?: number;
  repo?: string;
  run_id?: number;
  status: string;
  triggered_at: string;
  rca_summary?: string;
}
