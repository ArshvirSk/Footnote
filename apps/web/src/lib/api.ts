/**
 * Minimal typed API client for the Footnote backend.
 *
 * - Base URL: NEXT_PUBLIC_API_URL (default http://localhost:8000)
 * - Auth: JWT from localStorage (`footnote_token`), set by the dev login page
 * - 401 responses clear the token and redirect to /login
 */

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const TOKEN_KEY = "footnote_token";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  window.localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  window.localStorage.removeItem(TOKEN_KEY);
}

export type EngineType = "chatgpt" | "gemini" | "perplexity" | "claude" | "grok" | "google_aio";

export interface Client {
  id: string;
  name: string;
  primary_domain: string;
  status: string;
  is_demo: boolean;
}

export interface ChecklistItem {
  key: string;
  label: string;
  why: string;
  done: boolean;
  detail: string;
  href: string;
}

/** Website row enriched with derived status + list facts. */
export interface ClientSummary extends Client {
  derived_status: string;
  setup_progress: number;
  setup_total: number;
  checklist: ChecklistItem[];
  last_collection_at: string | null;
  visibility_pct: number | null;
  open_issues: number;
  pending_approvals: number;
  active_prompts: number;
}

/** A rate plus its raw numerator/denominator (sample size) and prior window. */
export interface Metric {
  value: number | null;
  current: number;
  base: number;
  prior_value: number | null;
  prior_current: number | null;
  prior_base: number | null;
  formula: string;
}

export interface DashboardKpis {
  visibility: Metric;
  mention_rate: Metric;
  linked_rate: Metric;
  citation_share: Metric;
  share_of_voice: Metric;
  open_gaps: number;
  pending_approvals: number;
  runs_7d: number;
  failed_7d: number;
  collection_health: number | null;
  last_collection_at: string | null;
  last_audit_score: number | null;
  last_audit_at: string | null;
  data_source: string;
  engine_providers_configured: string[];
}

export interface AttentionItem {
  severity: string;
  kind: string;
  title: string;
  detail: string;
  href: string;
}

export interface WinItem {
  kind: string;
  title: string;
  detail: string;
  at: string | null;
}

export interface SetupResponse {
  client_id: string;
  status: string;
  progress: number;
  total: number;
  items: ChecklistItem[];
}

export interface WebsiteDashboard {
  client_id: string;
  client_name: string;
  status: string;
  setup: SetupResponse;
  kpis: DashboardKpis;
  needs_attention: AttentionItem[];
  recent_wins: WinItem[];
  correlation_note: string;
}

export interface BrandProfile {
  client_id?: string;
  voice: string | null;
  positioning: string | null;
  products: { name: string; category?: string }[];
  icp: { summary?: string; segments?: string[] };
  proof_points: { claim: string; source?: string }[];
  banned_claims: string[];
  theme_html: string | null;
  theme_css: string | null;
  aliases: string[];
  updated_at?: string | null;
}

export interface MemoryChunk {
  id: string;
  source: string;
  title: string | null;
  preview: string;
  created_at: string | null;
}

export interface Competitor {
  id: string;
  name: string;
  domain: string | null;
  aliases: string[];
}

export interface Persona {
  id: string;
  name: string;
  description: string | null;
}

export interface Prompt {
  id: string;
  client_id: string;
  text: string;
  kind: string;
  funnel_stage: string | null;
  lead_intent_score: number | null;
  engines: EngineType[];
  source: string | null;
  is_active: boolean;
}

export interface Gap {
  id: string;
  client_id: string;
  prompt_id: string | null;
  prompt_text: string | null;
  gap_type: "slipped" | "competitor_cited" | string;
  details: Record<string, unknown>;
  status: "open" | "in_progress" | "won" | "dismissed" | string;
  detected_at: string | null;
}

// ──── Milestone 2: prompts, collection, research, tracking ────

export interface PromptSeriesPoint {
  day: string;
  runs: number;
  mentioned: number;
}

export interface EngineRunStatus {
  engine: EngineType;
  status: string; // queued | running | succeeded | failed | none
  last_at: string | null;
}

export interface PromptListItem extends Prompt {
  created_at: string | null;
  retired_at: string | null;
  persona_id: string | null;
  last_run_at: string | null;
  series: PromptSeriesPoint[];
  engine_status: EngineRunStatus[];
}

export interface PromptCandidate {
  id: string;
  text: string;
  kind: string;
  funnel_stage: string | null;
  lead_intent_score: number | null;
  persona_id: string | null;
  rationale: string | null;
  generator: string;
  model: string | null;
  status: string;
  created_at: string;
  resolved_at: string | null;
  accepted_prompt_id: string | null;
}

export interface GenerateResponse {
  generator: string;
  model: string;
  created: number;
  warnings: string[];
  candidates: PromptCandidate[];
}

export interface EngineHealth {
  engine: EngineType;
  scheduled: number;
  succeeded: number;
  failed: number;
  queued: number;
}

export interface FailedRun {
  answer_id: string;
  prompt_id: string;
  prompt_text: string | null;
  engine: EngineType;
  run_index: number;
  day: string | null;
  attempts: number;
  error: string | null;
  collected_at: string | null;
}

export interface CollectionHealth {
  client_id: string;
  days: number;
  scheduled: number;
  succeeded: number;
  failed: number;
  queued: number;
  running: number;
  mock_runs: number;
  rate: number | null;
  per_engine: EngineHealth[];
  failures: FailedRun[];
  last_collection_at: string | null;
  mock_mode: boolean;
}

export interface RunNowResponse {
  day: string;
  trigger: string;
  scheduled: number;
  already_scheduled: number;
  enqueued: number;
  skipped_cap: number;
  answers: { answer_id: string; prompt_id: string; engine: EngineType; run_index: number }[];
}

export interface AnswerCitation {
  url: string;
  title: string | null;
  position: number | null;
  is_brand_owned: boolean;
  competitor_id: string | null;
}

export interface AnswerMention {
  entity_kind: string;
  competitor_id: string | null;
  recommended: boolean | null;
  sentiment: string | null;
  linked: boolean;
  excerpt: string | null;
}

export interface PromptAnswer {
  id: string;
  engine: EngineType;
  run_index: number;
  status: string;
  geo: string | null;
  day: string | null;
  collected_at: string | null;
  latency_ms: number | null;
  model_label: string | null;
  attempts: number;
  error: string | null;
  judge_version: string | null;
  mock: boolean;
  raw_text: string | null;
  citations: AnswerCitation[];
  mentions: AnswerMention[];
}

export interface GapEvidence {
  answer_id: string;
  engine: string;
  run_index: number;
  day: string | null;
  collected_at: string | null;
  brand_mentioned: boolean;
  competitor_mentioned: boolean;
  excerpt: string | null;
  citations: { url: string; title: string | null; owned: boolean }[];
}

export interface GapDetail extends Gap {
  evidence: GapEvidence[];
  why: string;
}

export interface DomainCitation {
  domain: string;
  domain_type: string;
  citations: number;
  answers: number;
  is_brand: boolean;
  is_competitor: boolean;
  share: number;
}

export interface DomainCitationsResponse {
  days: number;
  total_citations: number;
  brand_citations: number;
  brand_share: number | null;
  domains: DomainCitation[];
}

export interface MatrixCompetitor {
  competitor_id: string;
  name: string;
  runs_with_mention: number;
}

export interface MatrixRow {
  prompt_id: string;
  prompt_text: string;
  funnel_stage: string | null;
  runs: number;
  brand_runs: number;
  brand_visible: boolean;
  competitors: MatrixCompetitor[];
}

export interface CompetitorMatrixResponse {
  days: number;
  rows: MatrixRow[];
}

export interface CompetitorPage {
  url: string;
  title: string | null;
  citations: number;
}

export interface CompetitorPrompt {
  prompt_id: string;
  prompt_text: string;
  hits: number;
}

export interface CompetitorIntel {
  competitor_id: string;
  name: string;
  domain: string | null;
  mentions: number;
  prompts_present: number;
  citations: number;
  share_of_voice: number | null;
  top_pages: CompetitorPage[];
  gap_prompts: CompetitorPrompt[];
}

export interface CompetitorIntelligenceResponse {
  days: number;
  total_brand_mentions: number;
  total_competitor_mentions: number;
  competitors: CompetitorIntel[];
}

export interface DailyMetric {
  day: string;
  engine: string;
  prompts_tracked: number;
  prompts_visible: number;
  mention_rate: number;
  linked_rate: number;
  brand_citations: number;
  total_citations: number;
  citation_share: number;
  share_of_voice: number;
  avg_sentiment: number;
}

export interface AuditFinding {
  id: string;
  category: string;
  severity: "critical" | "high" | "medium" | "low" | string;
  rule: string;
  detail: string;
  url: string | null;
  fix_owner: string;
  status: string;
  suggested_fix: string | null;
  verified_at: string | null;
}

export interface AuditRerunResponse {
  audit: AuditDetail;
  rerun_of: string;
  fixed: AuditFinding[];
  still_present: AuditFinding[];
  regressed: AuditFinding[];
  new: AuditFinding[];
}

export interface DevBriefResponse {
  filename: string;
  markdown: string;
}

/** Effective robots.txt decision for one AI crawler (M3). */
export interface RobotsBotRule {
  bot: string;
  group: string;
  allowed: boolean;
  rule: string | null;
}

/** PageSpeed Insights summary persisted in the audit summary (M3). */
export interface AuditSpeed {
  status: "ok" | "not_configured" | "error" | string;
  strategy?: string;
  performance_score?: number | null;
  lcp_ms?: number | null;
  cls?: number | null;
  tbt_ms?: number | null;
  fcp_ms?: number | null;
  si_ms?: number | null;
  final_url?: string;
  fetched_at?: string;
  reason?: string;
}

export interface AuditPage {
  url: string;
  status_code: number | null;
  title: string | null;
  word_count: number | null;
  description: string | null;
  last_crawled_at: string | null;
}

export interface Audit {
  id: string;
  client_id: string;
  started_at: string | null;
  finished_at: string | null;
  score: number | null;
  summary: Record<string, unknown>;
  rerun_of: string | null;
}

export interface AuditDetail extends Audit {
  findings: AuditFinding[];
  pages: AuditPage[];
}

export interface Me {
  user_id: string;
  email: string;
  org_id: string | null;
  role: string | null;
  client_ids: string[];
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Content-Type", "application/json");
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);

  const response = await fetch(`${API_BASE}/api/v1${path}`, { ...init, headers });

  if (response.status === 401 && typeof window !== "undefined") {
    clearToken();
    window.location.href = "/login";
    throw new ApiError(401, "Unauthorized");
  }

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = (await response.json()) as { detail?: string };
      if (body.detail) detail = body.detail;
    } catch {
      // non-JSON error body; keep statusText
    }
    throw new ApiError(response.status, detail);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) }),
  put: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "PUT", body: body === undefined ? undefined : JSON.stringify(body) }),
  patch: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "PATCH", body: body === undefined ? undefined : JSON.stringify(body) }),
  delete: <T>(path: string) => request<T>(path, { method: "DELETE" }),
};

/** Dev login: exchange email for a JWT (ENVIRONMENT != production only). */
export async function devLogin(email: string): Promise<string> {
  const res = await fetch(`${API_BASE}/api/v1/auth/dev-login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email }),
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = (await res.json()) as { detail?: string };
      if (body.detail) detail = body.detail;
    } catch {
      // ignore
    }
    throw new ApiError(res.status, detail);
  }
  const data = (await res.json()) as { access_token: string };
  setToken(data.access_token);
  return data.access_token;
}

export const audits = {
  list: (clientId: string) => api.get<Audit[]>(`/clients/${clientId}/audits`),
  get: (clientId: string, auditId: string) =>
    api.get<AuditDetail>(`/clients/${clientId}/audits/${auditId}`),
  start: (clientId: string, url?: string) =>
    api.post<AuditDetail>(`/clients/${clientId}/audits`, url ? { url } : {}),
  rerun: (clientId: string, auditId: string) =>
    api.post<AuditRerunResponse>(`/clients/${clientId}/audits/${auditId}/rerun`),
  updateFinding: (clientId: string, auditId: string, findingId: string, status: string) =>
    api.patch<AuditFinding>(`/clients/${clientId}/audits/${auditId}/findings/${findingId}`, { status }),
  brief: (clientId: string, auditId: string) =>
    api.get<DevBriefResponse>(`/clients/${clientId}/audits/${auditId}/brief`),
};

const SELECTED_CLIENT_KEY = "footnote_client_id";

export function getSelectedClientId(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(SELECTED_CLIENT_KEY);
}

/** Emitted on window whenever the active client changes (OpsHeader listens). */
export const CLIENT_CHANGED_EVENT = "footnote:client-changed";

export function setSelectedClientId(id: string): void {
  window.localStorage.setItem(SELECTED_CLIENT_KEY, id);
  window.dispatchEvent(new CustomEvent(CLIENT_CHANGED_EVENT, { detail: id }));
}

export const clients = {
  list: (includeDemo = false) =>
    api.get<ClientSummary[]>(`/clients${includeDemo ? "?include_demo=true" : ""}`),
  create: (input: { name: string; primary_domain: string; industry?: string }) =>
    api.post<Client>("/clients", input),
};

/** Website-scoped API: setup checklist, dashboard, brand memory and entities. */
export const websites = {
  list: (includeDemo = false) =>
    api.get<ClientSummary[]>(`/clients${includeDemo ? "?include_demo=true" : ""}`),
  setup: (id: string) => api.get<SetupResponse>(`/clients/${id}/setup`),
  dashboard: (id: string) => api.get<WebsiteDashboard>(`/clients/${id}/dashboard`),
  brandProfile: {
    get: (id: string) => api.get<BrandProfile>(`/clients/${id}/brand-profile`),
    put: (id: string, profile: Omit<BrandProfile, "client_id" | "updated_at">) =>
      api.put<BrandProfile>(`/clients/${id}/brand-profile`, profile),
  },
  brandMemory: {
    list: (id: string) => api.get<MemoryChunk[]>(`/clients/${id}/brand-memory`),
    ingest: (id: string, body: { kind: "url" | "text"; url?: string; text?: string; title?: string }) =>
      api.post<{ chunks: number; tokens: number; cost_usd: number; title: string }>(
        `/clients/${id}/brand-memory/ingest`,
        body,
      ),
    remove: (id: string, chunkId: string) =>
      api.delete<void>(`/clients/${id}/brand-memory/${chunkId}`),
  },
  competitors: {
    list: (id: string) => api.get<Competitor[]>(`/clients/${id}/competitors`),
    create: (id: string, body: { name: string; domain?: string; aliases?: string[] }) =>
      api.post<Competitor>(`/clients/${id}/competitors`, body),
    remove: (id: string, competitorId: string) =>
      api.delete<void>(`/clients/${id}/competitors/${competitorId}`),
  },
  personas: {
    list: (id: string) => api.get<Persona[]>(`/clients/${id}/personas`),
    create: (id: string, body: { name: string; description?: string }) =>
      api.post<Persona>(`/clients/${id}/personas`, body),
    remove: (id: string, personaId: string) => api.delete<void>(`/clients/${id}/personas/${personaId}`),
  },
};

export const promptsApi = {
  list: (clientId: string) => api.get<PromptListItem[]>(`/clients/${clientId}/prompts`),
  create: (clientId: string, body: { text: string; engines?: EngineType[] }) =>
    api.post<Prompt>(`/clients/${clientId}/prompts`, body),
  update: (clientId: string, promptId: string, body: Partial<Pick<Prompt, "text" | "is_active">>) =>
    api.patch<Prompt>(`/clients/${clientId}/prompts/${promptId}`, body),
};

export const collectionApi = {
  health: (clientId: string, days = 7) =>
    api.get<CollectionHealth>(`/clients/${clientId}/collection/health?days=${days}`),
  runNow: (clientId: string, promptId?: string) =>
    api.post<RunNowResponse>(`/clients/${clientId}/collection/run`, promptId ? { prompt_id: promptId } : {}),
  answers: (clientId: string, promptId: string, days = 14) =>
    api.get<PromptAnswer[]>(`/clients/${clientId}/prompts/${promptId}/answers?days=${days}`),
  series: (clientId: string, promptId: string, days = 14) =>
    api.get<PromptSeriesPoint[]>(`/clients/${clientId}/prompts/${promptId}/series?days=${days}`),
};

export const researchApi = {
  generate: (clientId: string, limit = 20) =>
    api.post<GenerateResponse>(`/clients/${clientId}/research/generate`, { limit }),
  candidates: (clientId: string, status: string = "pending") =>
    api.get<PromptCandidate[]>(`/clients/${clientId}/research/candidates?status=${status}`),
  accept: (clientId: string, candidateId: string, body: { text?: string }) =>
    api.post<{ candidate: PromptCandidate; prompt_id: string | null }>(
      `/clients/${clientId}/research/candidates/${candidateId}/accept`,
      body,
    ),
  reject: (clientId: string, candidateId: string) =>
    api.post<{ candidate: PromptCandidate; prompt_id: string | null }>(
      `/clients/${clientId}/research/candidates/${candidateId}/reject`,
    ),
};

export const gapsApi = {
  list: (clientId: string) => api.get<Gap[]>(`/clients/${clientId}/gaps`),
  detail: (clientId: string, gapId: string) =>
    api.get<GapDetail>(`/clients/${clientId}/gaps/${gapId}`),
  setStatus: (clientId: string, gapId: string, status: string) =>
    api.patch<Gap>(`/clients/${clientId}/gaps/${gapId}`, { status }),
};

export const trackingApi = {
  domains: (clientId: string, days = 7) =>
    api.get<DomainCitationsResponse>(`/clients/${clientId}/citations/domains?days=${days}`),
  matrix: (clientId: string, days = 7) =>
    api.get<CompetitorMatrixResponse>(`/clients/${clientId}/competitors/matrix?days=${days}`),
  competitorIntelligence: (clientId: string, days = 7) =>
    api.get<CompetitorIntelligenceResponse>(
      `/clients/${clientId}/competitors/intelligence?days=${days}`,
    ),
  dailyMetrics: (clientId: string, days = 14) =>
    api.get<DailyMetric[]>(`/clients/${clientId}/metrics/daily?days=${days}`),
};

export const me = () => api.get<Me>("/auth/me");

/** Resolve the client every ops page should operate on.
 * Prefers the user's explicit selection, else the most recently created client. */
export async function getDefaultClientId(): Promise<string> {
  // Include demo websites: the header select allows them (badged), so the
  // resolver must keep a demo selection instead of silently resetting it.
  const list = await clients.list(true);
  if (list.length === 0) throw new ApiError(404, "No clients — add a website first");
  const selected = getSelectedClientId();
  if (selected && list.some((c) => c.id === selected)) return selected;
  setSelectedClientId(list[0].id);
  return list[0].id;
}
