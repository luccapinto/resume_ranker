export type Stage = "sourced" | "screening" | "interview" | "offer" | "hired" | "rejected";
export type Fit = "forte" | "moderado" | "baixo";

export interface NormalizedSkill {
  original_term: string;
  concept_uri: string | null;
  preferred_label: string | null;
  match_type: "exact" | "fuzzy" | "embedding" | "unmapped";
  score: number;
}

export interface ExtractedProfile {
  seniority?: string;
  skills_raw?: string[];
  skills_normalized?: NormalizedSkill[];
  experience_years?: number;
  education?: { degree: string; field: string; year: number | null }[];
  certifications?: string[];
  languages?: string[];
  narrative_experience?: string;
  headline?: string;
  current_title?: string;
  highlights?: string[];
  role_title?: string;
  must_have_skills?: string[];
  nice_to_have_skills?: string[];
  responsibilities?: string[];
}

export interface Profile {
  id: number;
  type: "candidate" | "job";
  file_name: string | null;
  raw_text: string | null;
  redacted_text: string;
  redaction_map: Record<string, string>;
  extracted_profile: ExtractedProfile;
  has_pdf: boolean;
  trace_id: string | null;
  created_at: string;
}

export interface Candidate {
  id: number;
  profile_id: number;
  display_name: string;
  initials: string;
  headline: string | null;
  location: string | null;
  email: string | null;
  phone: string | null;
  source: string | null;
  seniority?: string;
  experience_years?: number;
  skills: string[];
  certifications: string[];
  languages: string[];
  highlights: string[];
  narrative: string | null;
  created_at: string;
  profile?: Profile;
  applications?: Application[];
}

export interface Job {
  id: number;
  profile_id: number;
  title: string;
  department: string | null;
  location: string | null;
  work_model: string | null;
  employment_type: string | null;
  seniority: string | null;
  salary_min: number | null;
  salary_max: number | null;
  status: "open" | "paused" | "closed";
  headcount: number;
  owner: string | null;
  must_have_skills: string[];
  nice_to_have_skills: string[];
  responsibilities: string[];
  skills: string[];
  experience_years?: number;
  created_at: string;
  funnel?: Record<Stage, number>;
  applications_count?: number;
  profile?: Profile;
}

export interface MatchSignals {
  matched_skills: string[];
  missing_skills: string[];
  extra_skills: string[];
  must_have_matched: string[];
  must_have_missing: string[];
  must_have_coverage: number | null;
  skill_coverage: number;
  candidate_experience_years: number;
  job_experience_years: number;
  experience_delta_years: number;
  meets_experience: boolean;
  candidate_seniority: string | null;
  job_seniority: string | null;
  seniority_gap: number | null;
  candidate_certifications: string[];
  job_certifications: string[];
}

export interface Application {
  id: number;
  candidate_id: number;
  job_id: number;
  stage: Stage;
  stage_label: string;
  ai_score: number | null;
  ai_rank: number | null;
  ai_rrf_score: number | null;
  ai_fit: Fit | null;
  ai_summary: string | null;
  ai_matched_skills: string[];
  ai_missing_skills: string[];
  ai_signals: Record<string, unknown>;
  ranked_at: string | null;
  trace_id: string | null;
  created_at: string;
  updated_at: string;
  candidate?: Candidate;
  job?: Job;
  timeline?: Activity[];
}

export interface Activity {
  id: number;
  application_id?: number;
  type: string;
  actor: string;
  content: string | null;
  payload: Record<string, unknown>;
  created_at: string;
  candidate?: string | null;
  job?: string | null;
}

export interface RankedCandidate {
  rank: number;
  profile_id: number;
  score: number;
  score_normalized: number;
  rrf_score: number;
  rrf_rank: number | null;
  reranked: boolean;
  strategy_ranks: Partial<Record<"skills" | "narrative" | "lexical", number>>;
  strategy_scores: Partial<Record<"skills" | "narrative" | "lexical", number>>;
  fit: Fit;
  signals: MatchSignals;
  candidate: Candidate;
  application_id?: number;
  stage?: Stage;
  explanation?: MatchExplanation;
}

export interface RankResult {
  job: Job;
  trace_id: string | null;
  weights: number[];
  reranked: boolean;
  results: RankedCandidate[];
}

export interface Citation {
  text: string;
  verified: boolean;
}

export interface MatchExplanation {
  fit: Fit;
  confidence: number;
  summary: string;
  explanation: string;
  strengths: string[];
  gaps: string[];
  citations: Citation[];
  interview_questions: string[];
  signals: MatchSignals;
  generated_by: string;
  hallucination_check: { total: number; verified: number; unverified?: number; rate?: number };
  trace_id?: string;
  application_id?: number;
}

export interface FairnessAxis {
  axis: string;
  description: string;
  applicable: boolean;
  reason?: string;
  swaps: { original: string; replacement: string; count: number }[];
  swap_count?: number;
  original_score: number;
  counterfactual_score: number;
  score_pct_delta: number;
  original_rank: number;
  counterfactual_rank: number;
  rank_delta: number;
  passed: boolean;
}

export interface FairnessAudit {
  candidate_id: number;
  job_id: number;
  audit_passed: boolean;
  max_score_pct_delta: number;
  threshold_pct: number;
  original_score: number;
  original_rank: number;
  pool_size: number;
  deep: boolean;
  axes: FairnessAxis[];
  duration_ms: number;
  trace_id: string | null;
}

export interface Overview {
  jobs_total: number;
  jobs_open: number;
  candidates_total: number;
  applications_total: number;
  by_stage: { stage: Stage; label: string; count: number }[];
  avg_ai_score: number;
  strong_fit_count: number;
  hired: number;
  rejected: number;
  recent_activity: Activity[];
  stages: { key: Stage; label: string }[];
}

export interface KanbanColumn {
  key: Stage;
  label: string;
  applications: Application[];
}

export interface KanbanBoard {
  job: Job;
  stages: KanbanColumn[];
  total: number;
}

/* ── Copilot ─────────────────────────────────────────────────────────── */
export type CopilotCard =
  | { type: "ranking"; job: Job; results: RankedCandidate[]; trace_id: string | null }
  | { type: "jobs"; jobs: Job[] }
  | { type: "candidates"; query: string; candidates: (Candidate & { score: number; rank: number })[] }
  | { type: "candidate"; candidate: Candidate; applications: unknown[] }
  | { type: "explanation"; candidate: Candidate; job: Job; explanation: MatchExplanation }
  | { type: "application"; application: Application }
  | { type: "overview"; overview: Overview }
  | { type: "fairness"; candidate: Candidate; job: Job; audit: FairnessAudit };

export interface CopilotResponse {
  reply: string;
  cards: CopilotCard[];
  tool_calls: { name: string; arguments: Record<string, unknown>; ok: boolean }[];
  model: string;
  trace_id: string | null;
}

export interface CopilotTools {
  tools: { name: string; description: string; parameters: string[] }[];
  suggestions: string[];
}

/* ── Observability ───────────────────────────────────────────────────── */
export type SpanKind =
  | "llm"
  | "embedding"
  | "vector"
  | "rerank"
  | "pii"
  | "db"
  | "logic"
  | "tool"
  | "parse";

export interface Span {
  id: string;
  parent_id: string | null;
  name: string;
  kind: SpanKind;
  status: "ok" | "error";
  depth: number;
  duration_ms: number;
  started_at_offset_ms: number;
  model: string | null;
  prompt_tokens: number;
  completion_tokens: number;
  cost_usd: number;
  error_type: string | null;
  error_message: string | null;
  input_preview: string | null;
  output_preview: string | null;
  attributes: Record<string, unknown>;
}

export interface Trace {
  id: string;
  name: string;
  status: "ok" | "error";
  duration_ms: number;
  total_tokens: number;
  total_cost_usd: number;
  llm_calls: number;
  span_count: number;
  error_message: string | null;
  metadata: Record<string, unknown>;
  started_at: string;
  spans?: Span[];
}

export interface Metrics {
  window_hours: number;
  totals: {
    traces: number;
    spans: number;
    errors: number;
    error_rate: number;
    llm_calls: number;
    tokens: number;
    cost_usd: number;
    p50_ms: number;
    p95_ms: number;
    p99_ms: number;
    avg_ms: number;
  };
  by_kind: {
    kind: SpanKind;
    count: number;
    errors: number;
    cost_usd: number;
    tokens: number;
    p50_ms: number;
    p95_ms: number;
    avg_ms: number;
    total_ms: number;
  }[];
  by_operation: {
    name: string;
    count: number;
    errors: number;
    cost_usd: number;
    p50_ms: number;
    p95_ms: number;
    error_rate: number;
  }[];
  by_model: {
    model: string;
    calls: number;
    errors: number;
    tokens: number;
    cost_usd: number;
    p95_ms: number;
    avg_ms: number;
  }[];
  timeseries: { bucket: string; count: number; errors: number; cost_usd: number; p95_ms: number }[];
  recent_errors: {
    trace_id: string;
    span: string;
    kind: SpanKind;
    error_type: string | null;
    error_message: string | null;
  }[];
}

export interface RuntimeConfig {
  llm_model: string;
  llm_configured: boolean;
  embedding_provider: string;
  embedding_model: string;
  reranker_model: string;
  vector_store: string;
}

export interface AuditLog {
  id: number;
  query_type: string;
  query_id: number;
  embedding_model: string;
  reranker_model: string;
  execution_time_ms: number;
  bias_audit_passed: boolean;
  bias_audit_results: Partial<FairnessAudit> & { axes?: FairnessAxis[] };
  trace_id: string | null;
  created_at: string;
}
