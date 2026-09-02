import type {
  Activity,
  AuditLog,
  Candidate,
  CopilotResponse,
  CopilotTools,
  FairnessAudit,
  Job,
  KanbanBoard,
  MatchedJob,
  MatchExplanation,
  Metrics,
  Overview,
  Profile,
  RankResult,
  RuntimeConfig,
  Stage,
  Trace,
} from "./types";

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE?.replace(/\/$/, "") ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly detail?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** Latency of the last request, surfaced in the UI so nothing hides behind a spinner. */
export let lastLatencyMs = 0;

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const started = performance.now();
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: {
        ...(init?.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
        ...init?.headers,
      },
      cache: "no-store",
    });
  } catch (cause) {
    throw new ApiError(
      `Não foi possível falar com a API em ${API_BASE}. O backend está rodando?`,
      0,
      cause,
    );
  }
  lastLatencyMs = performance.now() - started;

  if (!response.ok) {
    let detail: unknown;
    try {
      detail = (await response.json())?.detail;
    } catch {
      detail = await response.text().catch(() => undefined);
    }
    const message =
      typeof detail === "string"
        ? detail
        : `Requisição falhou (${response.status}) em ${path}`;
    throw new ApiError(message, response.status, detail);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

const json = (body: unknown): RequestInit => ({
  method: "POST",
  body: JSON.stringify(body),
});

export const api = {
  /* ── system ─────────────────────────────────────────────────────── */
  health: () => request<{ status: string; postgres: string; qdrant: string }>("/health"),
  config: () => request<RuntimeConfig>("/config"),

  /* ── ATS ────────────────────────────────────────────────────────── */
  overview: () => request<Overview>("/ats/overview"),

  jobs: (status?: string) =>
    request<Job[]>(`/ats/jobs${status ? `?status=${encodeURIComponent(status)}` : ""}`),
  job: (id: number) => request<Job>(`/ats/jobs/${id}`),
  createJob: (form: FormData) => request<Job>("/ats/jobs", { method: "POST", body: form }),
  updateJobStatus: (id: number, status: string) =>
    request<Job>(`/ats/jobs/${id}/status?status=${status}`, { method: "PATCH" }),
  deleteJob: (id: number) => request<{ deleted: number }>(`/ats/jobs/${id}`, { method: "DELETE" }),

  candidates: (q?: string) =>
    request<Candidate[]>(`/ats/candidates${q ? `?q=${encodeURIComponent(q)}` : ""}`),
  candidate: (id: number) => request<Candidate>(`/ats/candidates/${id}`),
  createCandidate: (form: FormData) =>
    request<Candidate>("/ats/candidates", { method: "POST", body: form }),

  rankJob: (
    id: number,
    body: {
      top_n?: number;
      rerank?: boolean;
      weights?: number[] | null;
      min_experience_years?: number | null;
      seniorities?: string[] | null;
      explain_top?: number;
    } = {},
  ) => request<RankResult>(`/ats/jobs/${id}/rank`, json({ job_id: id, ...body })),

  board: (jobId: number) => request<KanbanBoard>(`/ats/jobs/${jobId}/applications`),
  application: (id: number) => request<import("./types").Application>(`/ats/applications/${id}`),
  moveApplication: (id: number, stage: Stage, note?: string, actor = "Recrutador") =>
    request<import("./types").Application>(`/ats/applications/${id}/stage`, {
      method: "PATCH",
      body: JSON.stringify({ stage, note, actor }),
    }),
  addNote: (id: number, content: string, actor = "Recrutador") =>
    request<Activity>(`/ats/applications/${id}/notes`, json({ content, actor })),
  explainApplication: (id: number) =>
    request<MatchExplanation>(`/ats/applications/${id}/explain`, { method: "POST" }),

  /* ── matching engine ────────────────────────────────────────────── */
  /** Reverse direction: which openings fit this candidate? */
  matchJobsForCandidate: (candidateProfileId: number, topN = 5) =>
    request<MatchedJob[]>(
      `/matching/jobs?candidate_id=${candidateProfileId}&top_n=${topN}&top_k=20`,
      { method: "POST" },
    ),

  explainPair: (candidateProfileId: number, jobProfileId: number) =>
    request<MatchExplanation>(
      `/matching/explain?candidate_id=${candidateProfileId}&job_id=${jobProfileId}`,
      { method: "POST" },
    ),
  auditBias: (candidateProfileId: number, jobProfileId: number, deep = false) =>
    request<FairnessAudit>(
      `/matching/audit-bias?candidate_id=${candidateProfileId}&job_id=${jobProfileId}&deep=${deep}`,
      { method: "POST" },
    ),
  auditLogs: (limit = 50) => request<AuditLog[]>(`/audit/logs?limit=${limit}`),

  profile: (id: number) => request<Profile>(`/profiles/${id}`),
  profilePdfUrl: (id: number) => `${API_BASE}/profiles/${id}/pdf`,

  /* ── copilot ────────────────────────────────────────────────────── */
  chat: (message: string, history: { role: string; content: string }[], jobId?: number | null) =>
    request<CopilotResponse>("/copilot/chat", json({ message, history, job_id: jobId ?? null })),
  copilotTools: () => request<CopilotTools>("/copilot/tools"),

  /* ── observability ──────────────────────────────────────────────── */
  traces: (params: { limit?: number; status?: string; name?: string } = {}) => {
    const search = new URLSearchParams();
    if (params.limit) search.set("limit", String(params.limit));
    if (params.status) search.set("status", params.status);
    if (params.name) search.set("name", params.name);
    return request<Trace[]>(`/observability/traces?${search.toString()}`);
  },
  trace: (id: string) => request<Trace>(`/observability/traces/${id}`),
  metrics: (windowHours = 24) =>
    request<Metrics>(`/observability/metrics?window_hours=${windowHours}`),
};
