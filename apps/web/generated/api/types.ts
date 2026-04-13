export type ApiEnvelope<T> = T;

export type ProjectRole = "owner" | "editor" | "viewer" | "admin";

export interface Project {
  id: string;
  owner_user_id: string | null;
  title: string;
  genre: string | null;
  premise: string | null;
  metadata_json: Record<string, unknown>;
  created_at: string | null;
  updated_at: string | null;
}

export interface WorkflowStep {
  id: number;
  step_key: string;
  step_type: string;
  workflow_type?: string;
  status: string;
  attempt_count: number;
  error_code?: string | null;
  error_message?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
}

export interface ChapterCandidate {
  id: string;
  workflow_step_id: number | null;
  chapter_no: number;
  title: string | null;
  status: string;
  approved_chapter_id?: string | null;
  approved_version_id?: number | null;
  created_at?: string | null;
  updated_at?: string | null;
  approved_at?: string | null;
  rejected_at?: string | null;
}

export interface WorkflowRunDetail {
  id: string;
  project_id: string;
  workflow_type: string;
  status: string;
  trace_id: string | null;
  request_id: string | null;
  created_at: string | null;
  updated_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  error_code: string | null;
  error_message: string | null;
  output_json: Record<string, unknown>;
  steps: WorkflowStep[];
  candidates: ChapterCandidate[];
}

export interface MetricsJson {
  generated_at: string;
  workflow: {
    queue_depth: number;
    recent_by_status: Record<string, number>;
    runs_success_total: number;
    runs_failed_total: number;
    steps_failed_total: number;
  };
  retrieval: {
    rounds_total: number;
    coverage_avg: number;
  };
  skills: {
    executed_count: number;
    effective_delta: number;
    fallback_used_count: number;
    no_effect_count: number;
    mode_coverage: Record<string, number>;
    findings_total: number;
    evidence_total: number;
    metrics_rows_total: number;
    fact_external_evidence_total: number;
  };
  schema_contract: {
    required_covered_rate: number;
    dead_required_count: number;
    deprecated_unowned_count: number;
    deprecated_missing_retire_by_count: number;
    invalid_consumption_declaration_count: number;
    consumed_by_code_count: number;
    consumed_by_downstream_prompt_count: number;
    consumed_by_audit_only_count: number;
  };
  webhooks: {
    delivery_success_total: number;
    delivery_dead_total: number;
  };
}

export interface RunWsEvent {
  event_id: string;
  run_id: string;
  seq: number;
  event_type:
    | "run_status_changed"
    | "step_started"
    | "step_succeeded"
    | "step_failed"
    | "candidate_waiting_review"
    | "candidate_approved"
    | "candidate_rejected"
    | "run_completed"
    | "heartbeat";
  ts: string;
  payload: Record<string, unknown>;
  trace_id: string | null;
}
