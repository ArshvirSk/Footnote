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

export interface ContentBrief {
  id: string;
  client_id: string;
  title: string | null;
  angle: string | null;
  outline: Array<{ heading: string; points: string[]; sources_needed?: string[] }>;
  sources: string[];
  status: string;
  gap_ids: string[];
  grounding_rules: Record<string, any>;
  agent_run_id: string | null;
  created_at: string | null;
  item_count?: number;
  approval_id?: string | null;
  approval_status?: string;
  approval_comment?: string | null;
  prompts?: Array<{ id: string; text: string; funnel_stage?: string; kind?: string }>;
}

export interface ContentVersionSummary {
  id: string;
  version_no: number;
  title: string;
  author_kind: string;
  word_count: number;
  reading_time_min: number | null;
  created_at: string;
  approval_status?: string;
}

export interface ContentVersion extends ContentVersionSummary {
  content_item_id: string;
  body_md: string;
  body_html: string | null;
  jsonld: Record<string, any>;
  meta: Record<string, any>;
  claims: Array<{ text?: string; claim?: string; source?: string; status?: string }>;
  approval_id?: string | null;
  approval_comment?: string | null;
}

export interface ContentItem {
  id: string;
  client_id: string;
  brief_id: string | null;
  brief?: { id: string; title: string; angle: string; outline: any[]; sources: string[] } | null;
  type: string;
  slug: string | null;
  status: "idea" | "briefed" | "drafting" | "in_review" | "client_review" | "approved" | "scheduled" | "published" | "refresh_needed" | "archived";
  title: string;
  current_version_id: string | null;
  current_version?: ContentVersion | null;
  version_no?: number;
  word_count?: number;
  reading_time_min?: number | null;
  claims_count?: number;
  approval_id?: string | null;
  approval_status?: string;
  publish_target_kind?: string | null;
  publish_target_id?: string | null;
  published_url?: string | null;
  published_at?: string | null;
  decay_score?: number;
  created_at: string | null;
  versions?: ContentVersionSummary[];
  prompts?: Array<{ id: string; text: string; funnel_stage?: string; is_primary?: boolean }>;
  publications?: Array<{ id: string; status: string; url?: string; external_id?: string; published_at?: string; error?: string }>;
}

export interface ApprovalItem {
  id: string;
  subject_type: "brief" | "version" | "outreach" | "refresh" | "memo";
  subject_id: string;
  title: string;
  subtitle: string | null;
  item_id: string | null;
  item_status: string | null;
  status: "pending" | "approved" | "rejected" | "changes_requested";
  comment: string | null;
  requested_by: string | null;
  reviewer_id: string | null;
  requested_at: string | null;
  decided_at: string | null;
}

export interface KanbanCard {
  id: string;
  type: "Gap" | "Brief" | "Draft";
  title: string;
  subtitle?: string;
  gap_id?: string;
  brief_id?: string;
  item_id?: string;
  current_version_id?: string;
  status: string;
  approval_id?: string | null;
  approval_status?: string | null;
  published_url?: string | null;
  decay_score?: number;
}

export interface PipelineKanbanColumn {
  id: string;
  name: string;
  count: number;
  items: KanbanCard[];
}

export interface PipelineKanbanResponse {
  columns: PipelineKanbanColumn[];
}

export interface VersionDiffResponse {
  v1: number;
  v2: number;
  diff: string[];
  word_count_change: number;
}

export const contentApi = {
  pipeline: (clientId: string) =>
    api.get<PipelineKanbanResponse>(`/clients/${clientId}/content/pipeline`),
  listItems: (clientId: string, params?: { status?: string; type?: string; limit?: number; offset?: number }) => {
    const q = new URLSearchParams();
    if (params?.status) q.set("status", params.status);
    if (params?.type) q.set("type", params.type);
    if (params?.limit) q.set("limit", String(params.limit));
    if (params?.offset) q.set("offset", String(params.offset));
    const qs = q.toString() ? `?${q.toString()}` : "";
    return api.get<ContentItem[]>(`/clients/${clientId}/content/items${qs}`);
  },
  getItem: (clientId: string, itemId: string) =>
    api.get<ContentItem>(`/clients/${clientId}/content/items/${itemId}`),
  createItem: (clientId: string, body: { brief_id?: string; type?: string; title?: string; slug?: string }) =>
    api.post<{ id: string; status: string; created_at: string }>(`/clients/${clientId}/content/items`, body),
  updateItem: (clientId: string, itemId: string, body: { status?: string; slug?: string; type?: string; publish_target_id?: string }) =>
    api.patch<{ id: string; status: string }>(`/clients/${clientId}/content/items/${itemId}`, body),
  listBriefs: (clientId: string, status?: string) =>
    api.get<ContentBrief[]>(`/clients/${clientId}/content/briefs${status ? `?status=${status}` : ""}`),
  getBrief: (clientId: string, briefId: string) =>
    api.get<ContentBrief>(`/clients/${clientId}/content/briefs/${briefId}`),
  createBrief: (clientId: string, body: Partial<ContentBrief>) =>
    api.post<{ id: string; status: string; created_at: string }>(`/clients/${clientId}/content/briefs`, body),
  generateBrief: (clientId: string, gapId: string) =>
    api.post<{ brief_id: string; title: string; outline: any }>(`/clients/${clientId}/content/briefs/generate`, { gap_id: gapId }),
  generateDraft: (clientId: string, briefId: string, itemId?: string) =>
    api.post<{ content_item_id: string; version_id: string; version_no: number; title: string; body_md: string; claims: any[] }>(
      `/clients/${clientId}/content/drafts/generate`,
      { brief_id: briefId, content_item_id: itemId }
    ),
  listVersions: (clientId: string, itemId: string) =>
    api.get<ContentVersionSummary[]>(`/clients/${clientId}/content/items/${itemId}/versions`),
  getVersion: (clientId: string, itemId: string, versionId: string) =>
    api.get<ContentVersion>(`/clients/${clientId}/content/items/${itemId}/versions/${versionId}`),
  createVersion: (clientId: string, itemId: string, body: { title: string; body_md: string; body_html?: string; claims?: any[]; meta?: any }) =>
    api.post<{ id: string; version_no: number; word_count: number; reading_time_min: number; status: string }>(
      `/clients/${clientId}/content/items/${itemId}/versions`,
      body
    ),
  diffVersions: (clientId: string, itemId: string, v1: number, v2: number) =>
    api.get<VersionDiffResponse>(`/clients/${clientId}/content/items/${itemId}/diff?v1=${v1}&v2=${v2}`),
  listApprovals: (clientId: string, status?: string) =>
    api.get<ApprovalItem[]>(`/clients/${clientId}/content/approvals${status ? `?status=${status}` : ""}`),
  actionApproval: (clientId: string, approvalId: string, action: "approve" | "reject" | "request_changes", comment?: string) =>
    api.post<{ status: string; new_status: string }>(`/clients/${clientId}/content/approvals/${approvalId}/action`, { action, comment }),
};

export interface PublishTarget {
  id: string;
  client_id: string;
  name?: string;
  kind: "wordpress" | "feeds" | "webhook" | "webflow" | "shopify" | "ghost" | string;
  is_default: boolean;
  status: string;
  config: Record<string, any>;
  last_tested_at?: string;
  last_test_status?: string;
  last_test_error?: string;
  created_at?: string;
  updated_at?: string;
}

export interface PublishTargetCreate {
  name: string;
  kind: string;
  is_default?: boolean;
  config: Record<string, any>;
}

export interface PublishTargetTestResponse {
  status: "success" | "failed";
  detail: string;
  latency_ms: number;
  data?: Record<string, any>;
}

export interface PublicationRecord {
  id: string;
  content_item_id: string;
  client_id: string;
  version_id?: string;
  target_id?: string;
  external_id?: string;
  url?: string;
  status: "queued" | "running" | "succeeded" | "failed" | string;
  error?: string;
  title?: string;
  jsonld_verified: boolean;
  canonical_verified: boolean;
  http_status?: number;
  verified_at?: string;
  published_at?: string;
}

export const publishingApi = {
  listTargets: (clientId: string) =>
    api.get<PublishTarget[]>(`/clients/${clientId}/publish-targets`),
  createTarget: (clientId: string, body: PublishTargetCreate) =>
    api.post<PublishTarget>(`/clients/${clientId}/publish-targets`, body),
  getTarget: (clientId: string, targetId: string) =>
    api.get<PublishTarget>(`/clients/${clientId}/publish-targets/${targetId}`),
  updateTarget: (clientId: string, targetId: string, body: Partial<PublishTargetCreate> & { status?: string }) =>
    api.patch<PublishTarget>(`/clients/${clientId}/publish-targets/${targetId}`, body),
  deleteTarget: (clientId: string, targetId: string) =>
    api.delete<{ status: string }>(`/clients/${clientId}/publish-targets/${targetId}`),
  testTarget: (clientId: string, targetId: string) =>
    api.post<PublishTargetTestResponse>(`/clients/${clientId}/publish-targets/${targetId}/test`),
  publishItem: (clientId: string, itemId: string, body?: { target_id?: string; post_status?: string }) =>
    api.post<{ status: string; publication_id: string; target_id: string; message: string }>(
      `/clients/${clientId}/content-items/${itemId}/publish`,
      body || {}
    ),
  listPublications: (clientId: string, itemId?: string) =>
    api.get<PublicationRecord[]>(`/clients/${clientId}/publications${itemId ? `?content_item_id=${itemId}` : ""}`),
};

// ───────────── M6 Growth & Retention APIs ─────────────

export interface KPIOverview {
  published_content: number;
  won_gaps: number;
  ai_mentions: number;
  citation_share_pct: number;
  estimated_referral_value: number;
  days: number;
}

export interface TimeseriesPoint {
  day: string;
  brand_mentions: number;
  competitor_mentions: number;
  citation_share: number;
}

export interface WonGap {
  id: string;
  prompt_text: string | null;
  gap_type: string;
  closed_at: string | null;
  proof_citations: any[];
  published_url: string | null;
}

export interface EngineShare {
  engine: string;
  mention_rate: number;
  citation_share: number;
  prompts_visible: number;
  prompts_tracked: number;
}

export const analyticsApi = {
  getOverview: (clientId: string, days: number = 30) =>
    api.get<KPIOverview>(`/clients/${clientId}/analytics/overview?days=${days}`),
  getTimeseries: (clientId: string, days: number = 30) =>
    api.get<TimeseriesPoint[]>(`/clients/${clientId}/analytics/timeseries?days=${days}`),
  getWonGaps: (clientId: string, days: number = 30) =>
    api.get<WonGap[]>(`/clients/${clientId}/analytics/won-gaps?days=${days}`),
  getEngineShare: (clientId: string, days: number = 30) =>
    api.get<EngineShare[]>(`/clients/${clientId}/analytics/engine-share?days=${days}`),
};

export interface RefreshProposal {
  id: string;
  client_id: string;
  content_item_id: string;
  status: "pending" | "approved" | "rejected" | string;
  reason_json?: Record<string, any>;
  diff_summary?: string;
  proposed_version_id?: string;
  reviewer_id?: string;
  decided_at?: string;
  created_at?: string;
  item_title?: string;
  slug?: string;
  decay_score?: number;
}

export const refreshApi = {
  scan: (clientId: string) =>
    api.post<{ scanned: number; decayed_found: number; proposals_created: number; decay_threshold: number }>(
      `/clients/${clientId}/refresh/scan`
    ),
  listProposals: (clientId: string, status?: string) =>
    api.get<RefreshProposal[]>(`/clients/${clientId}/refresh/proposals${status ? `?status=${status}` : ""}`),
  getProposal: (clientId: string, proposalId: string) =>
    api.get<RefreshProposal>(`/clients/${clientId}/refresh/proposals/${proposalId}`),
  decideProposal: (clientId: string, proposalId: string, decision: "approved" | "rejected", notes?: string) =>
    api.post<{ status: string; proposal_id: string; decision: string }>(
      `/clients/${clientId}/refresh/proposals/${proposalId}/decide`,
      { decision, notes }
    ),
  proposeItem: (clientId: string, itemId: string, reason?: string) =>
    api.post<RefreshProposal>(`/clients/${clientId}/refresh/items/${itemId}/propose`, { reason }),
};

export interface ThirdPartyTask {
  id: string;
  client_id: string;
  platform: "reddit" | "quora" | "hackernews" | "forum" | string;
  thread_url: string;
  thread_title?: string;
  prompt_context?: string;
  status: "todo" | "drafting" | "review" | "posted" | string;
  assigned_to?: string;
  response_draft?: string;
  posted_url?: string;
  posted_at?: string;
  due_at?: string;
  created_at?: string;
  updated_at?: string;
}

export const thirdPartyApi = {
  listTasks: (clientId: string, params?: { status?: string; platform?: string }) => {
    const q = new URLSearchParams();
    if (params?.status) q.set("status", params.status);
    if (params?.platform) q.set("platform", params.platform);
    const qs = q.toString();
    return api.get<ThirdPartyTask[]>(`/clients/${clientId}/third-party/tasks${qs ? `?${qs}` : ""}`);
  },
  createTask: (clientId: string, body: { platform: string; thread_url: string; thread_title?: string; prompt_context?: string }) =>
    api.post<ThirdPartyTask>(`/clients/${clientId}/third-party/tasks`, body),
  getTask: (clientId: string, taskId: string) =>
    api.get<ThirdPartyTask>(`/clients/${clientId}/third-party/tasks/${taskId}`),
  updateTask: (clientId: string, taskId: string, body: Partial<ThirdPartyTask>) =>
    api.patch<ThirdPartyTask>(`/clients/${clientId}/third-party/tasks/${taskId}`, body),
  deleteTask: (clientId: string, taskId: string) =>
    api.delete<{ status: string }>(`/clients/${clientId}/third-party/tasks/${taskId}`),
  draftResponse: (clientId: string, taskId: string, instructions?: string) =>
    api.post<{ status: string; response_draft: string }>(
      `/clients/${clientId}/third-party/tasks/${taskId}/draft`,
      { instructions }
    ),
};

export interface OutreachTarget {
  id: string;
  client_id: string;
  domain: string;
  target_url?: string;
  status: "discovered" | "pitch_ready" | "contacted" | "won" | "declined" | string;
  citation_frequency?: number;
  relevance_notes?: string;
  created_at?: string;
  messages_count?: number;
}

export interface OutreachMessage {
  id: string;
  target_id: string;
  pitch_type: string;
  subject: string;
  body: string;
  status: "draft" | "pending_approval" | "approved" | "sent" | "rejected" | string;
  approval_id?: string;
  sent_at?: string;
  created_at?: string;
}

export const outreachApi = {
  discoverTargets: (clientId: string, limit?: number) =>
    api.post<{ discovered: number; inserted: number }>(
      `/clients/${clientId}/outreach/discover${limit ? `?limit=${limit}` : ""}`
    ),
  listTargets: (clientId: string, status?: string) =>
    api.get<OutreachTarget[]>(`/clients/${clientId}/outreach/targets${status ? `?status=${status}` : ""}`),
  createTarget: (clientId: string, body: { domain: string; target_url?: string; relevance_notes?: string }) =>
    api.post<OutreachTarget>(`/clients/${clientId}/outreach/targets`, body),
  getTarget: (clientId: string, targetId: string) =>
    api.get<OutreachTarget & { messages: OutreachMessage[] }>(`/clients/${clientId}/outreach/targets/${targetId}`),
  draftPitch: (clientId: string, targetId: string, pitchType?: string) =>
    api.post<OutreachMessage>(`/clients/${clientId}/outreach/targets/${targetId}/draft-pitch`, { pitch_type: pitchType }),
  dispatchMessage: (clientId: string, messageId: string, simulate: boolean = true) =>
    api.post<{ status: string; message_id: string; detail: string }>(
      `/clients/${clientId}/outreach/messages/${messageId}/dispatch`,
      { simulate }
    ),
};

export interface MemoRecord {
  id: string;
  client_id: string;
  period_start: string;
  period_end: string;
  title?: string;
  status: "draft" | "review" | "approved" | "published" | "rejected" | string;
  metrics_summary_json?: Record<string, any>;
  markdown_body?: string;
  published_url?: string;
  published_at?: string;
  created_at?: string;
  reviewer_id?: string;
  approval_status?: string;
}

export const memosApi = {
  listMemos: (clientId: string, status?: string) =>
    api.get<MemoRecord[]>(`/clients/${clientId}/memos${status ? `?status=${status}` : ""}`),
  generateMemo: (clientId: string, days: number = 30) =>
    api.post<{ status: string; memo_id: string; title: string }>(`/clients/${clientId}/memos/generate`, { days }),
  getMemo: (clientId: string, memoId: string) =>
    api.get<MemoRecord>(`/clients/${clientId}/memos/${memoId}`),
  decideMemo: (clientId: string, memoId: string, decision: "approved" | "rejected" | "revise", feedback?: string) =>
    api.post<{ status: string; memo_id: string; new_status: string }>(
      `/clients/${clientId}/memos/${memoId}/decide`,
      { decision, feedback }
    ),
  publishMemo: (clientId: string, memoId: string) =>
    api.post<{ status: string; memo_id: string; published_url: string }>(
      `/clients/${clientId}/memos/${memoId}/publish`
    ),
  exportMemo: (clientId: string, memoId: string) =>
    api.get<{ memo_id: string; title: string; markdown: string }>(`/clients/${clientId}/memos/${memoId}/export`),
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

// ─────────────────────────────────────────────────────────────────────────────
// Milestone 7: Client Portal & Admin Typed APIs
// ─────────────────────────────────────────────────────────────────────────────

export interface PortalMe {
  user_id: string;
  email: string;
  role: string;
  active_client_id: string | null;
  active_client_name: string | null;
  is_preview: boolean;
  clients: {
    id: string;
    name: string;
    primary_domain: string;
    industry: string | null;
    status: string;
  }[];
}

export interface PortalRecentMention {
  engine: string;
  query_text: string;
  snippet: string;
  collected_at: string | null;
}

export interface PortalDashboard {
  client_id: string;
  client_name: string;
  primary_domain: string;
  visibility_pct: number;
  citation_share_pct: number;
  content_shipped: number;
  pending_actions: number;
  recent_mentions: PortalRecentMention[];
}

export interface PortalApprovalItem {
  id: string;
  subject_type: string;
  subject_id: string;
  status: string;
  title: string;
  subtitle: string | null;
  requested_at: string;
  comment: string | null;
  preview: {
    excerpt?: string | null;
    word_count?: number | null;
    angle?: string | null;
    url?: string | null;
    diff_summary?: string | null;
  };
}

export interface PortalContentItem {
  id: string;
  slug: string | null;
  type: string;
  status: string;
  title: string;
  word_count: number;
  published_url: string | null;
  published_at: string | null;
  created_at: string;
}

export interface PortalSettings {
  client_id: string;
  name: string;
  primary_domain: string;
  industry: string | null;
  status: string;
  voice: string | null;
  positioning: string | null;
  products_count: number;
  proof_points_count: number;
  banned_claims_count: number;
  publish_targets: { kind: string; status: string }[];
  competitor_domains: string[];
}

export const portalApi = {
  getMe: (clientId?: string) =>
    api.get<PortalMe>(`/portal/me${clientId ? `?client_id=${clientId}` : ""}`),
  getDashboard: (clientId?: string) =>
    api.get<PortalDashboard>(`/portal/dashboard${clientId ? `?client_id=${clientId}` : ""}`),
  listApprovals: (clientId?: string, status?: string) => {
    const params = new URLSearchParams();
    if (clientId) params.set("client_id", clientId);
    if (status) params.set("status", status);
    const qs = params.toString();
    return api.get<PortalApprovalItem[]>(`/portal/approvals${qs ? `?${qs}` : ""}`);
  },
  decideApproval: (
    approvalId: string,
    decision: "approved" | "rejected" | "changes_requested",
    comment?: string
  ) =>
    api.post<PortalApprovalItem>(`/portal/approvals/${approvalId}/decide`, {
      decision,
      comment,
    }),
  listContent: (clientId?: string, status?: string) => {
    const params = new URLSearchParams();
    if (clientId) params.set("client_id", clientId);
    if (status) params.set("status", status);
    const qs = params.toString();
    return api.get<PortalContentItem[]>(`/portal/content${qs ? `?${qs}` : ""}`);
  },
  getSettings: (clientId?: string) =>
    api.get<PortalSettings>(`/portal/settings${clientId ? `?client_id=${clientId}` : ""}`),
};

export interface AdminUser {
  user_id: string;
  email: string;
  role: string;
  org_id: string | null;
  client_ids: string[];
  clients: { id: string; name: string }[];
  created_at: string | null;
}

export interface AuditLogItem {
  id: number;
  org_id: string | null;
  actor: string | null;
  actor_email: string | null;
  action: string;
  entity: string;
  entity_id: string | null;
  meta: Record<string, any>;
  at: string;
}

export interface AuditLogResponse {
  items: AuditLogItem[];
  total: number;
}

export interface AgentRunItem {
  id: string;
  client_id: string | null;
  client_name: string | null;
  agent: string;
  model: string | null;
  tokens_in: number | null;
  tokens_out: number | null;
  cost_usd: number | null;
  status: string;
  started_at: string | null;
  finished_at: string | null;
  trace_url: string | null;
}

export interface AdminSpendResponse {
  total_spend_usd: number;
  spend_30d_usd: number;
  total_tokens_in: number;
  total_tokens_out: number;
  total_runs: number;
  by_agent: { agent: string; runs: number; spend_usd: number; tokens: number }[];
  by_model: { model: string; runs: number; spend_usd: number }[];
  by_client: { client_id: string; client_name: string; runs: number; spend_usd: number }[];
}

export interface EngineStatusItem {
  engine: string;
  configured: boolean;
  model: string;
  key_preview: string;
}

export const adminApi = {
  listUsers: () => api.get<AdminUser[]>("/admin/users"),
  createUser: (data: { email: string; role: string; client_ids?: string[]; org_id?: string }) =>
    api.post<AdminUser>("/admin/users", data),
  updateUser: (userId: string, data: { role?: string; client_ids?: string[] }) =>
    api.patch<AdminUser>(`/admin/users/${userId}`, data),
  deleteUser: (userId: string) => api.delete<{ status: string; user_id: string }>(`/admin/users/${userId}`),
  listAuditLogs: (params?: { actor?: string; action?: string; entity?: string; limit?: number; offset?: number }) => {
    const p = new URLSearchParams();
    if (params?.actor) p.set("actor", params.actor);
    if (params?.action) p.set("action", params.action);
    if (params?.entity) p.set("entity", params.entity);
    if (params?.limit) p.set("limit", String(params.limit));
    if (params?.offset) p.set("offset", String(params.offset));
    const qs = p.toString();
    return api.get<AuditLogResponse>(`/admin/audit-logs${qs ? `?${qs}` : ""}`);
  },
  listAgentRuns: (params?: { client_id?: string; agent?: string; status?: string; limit?: number; offset?: number }) => {
    const p = new URLSearchParams();
    if (params?.client_id) p.set("client_id", params.client_id);
    if (params?.agent) p.set("agent", params.agent);
    if (params?.status) p.set("status", params.status);
    if (params?.limit) p.set("limit", String(params.limit));
    if (params?.offset) p.set("offset", String(params.offset));
    const qs = p.toString();
    return api.get<AgentRunItem[]>(`/admin/agent-runs${qs ? `?${qs}` : ""}`);
  },
  getSpend: () => api.get<AdminSpendResponse>("/admin/spend"),
  getEngineStatus: () => api.get<EngineStatusItem[]>("/admin/engine-status"),
  triggerReparse: (clientId?: string, engine?: string) =>
    api.post<{ status: string; count: number }>("/admin/reparse", { client_id: clientId, engine }),
  updateBillingLimits: (
    clientId: string,
    limits: { max_prompts?: number; max_monthly_spend_usd?: number; max_runs_per_day?: number }
  ) =>
    api.patch<{ client_id: string; billing_limits: any }>(`/admin/clients/${clientId}/billing-limits`, limits),
  listModelReleases: (engine?: string) =>
    api.get<ModelReleaseEventItem[]>(`/admin/model-releases${engine ? `?engine=${engine}` : ""}`),
  getModelDriftSummary: (clientId?: string) =>
    api.get<ModelDriftSummary>(`/admin/model-releases/summary${clientId ? `?client_id=${clientId}` : ""}`),
  checkModelReleases: (customCandidates?: Array<{ engine: string; model_label: string; source_url?: string }>) =>
    api.post<{ newly_detected: ModelReleaseEventItem[]; total_events: number }>("/admin/model-releases/check", {
      custom_candidates: customCandidates,
    }),
  rebaselinePrompts: (data?: { engine?: string; client_id?: string; prompt_ids?: string[] }) =>
    api.post<{ status: string; updated_prompts: number }>("/admin/model-releases/rebaseline", data ?? {}),
  rebaselineForRelease: (releaseId: string) =>
    api.post<{ status: string; updated_prompts: number }>(`/admin/model-releases/${releaseId}/rebaseline`, {}),
  getDaemonStatus: () => api.get<DaemonStatus>("/admin/daemon/status"),
  triggerDaemon: (tasks?: string[]) =>
    api.post<{ cycle_status: string; executed_at: string; tasks: Record<string, any> }>("/admin/daemon/trigger", {
      tasks,
    }),
  getMaintenanceTables: () => api.get<Record<string, number>>("/admin/maintenance/tables"),
  pruneMaintenanceData: (params?: {
    failed_answers_days?: number;
    historical_answers_days?: number;
    agent_runs_days?: number;
    audit_logs_days?: number;
    client_id?: string;
  }) => api.post<MaintenancePruneResponse>("/admin/maintenance/prune", params ?? {}),
};

export interface ModelReleaseEventItem {
  id: string;
  engine: string;
  model_label: string;
  detected_at?: string;
  source_url?: string;
}

export interface ModelDriftSummary {
  total_active_prompts: number;
  never_baselined_prompts: number;
  baselined_prompts: number;
  recent_releases_count: number;
  has_unbaselined_drift: boolean;
  latest_release?: ModelReleaseEventItem;
}

export interface DaemonStatus {
  status: string;
  uptime_seconds: number;
  started_at: string;
  last_run: Record<string, string>;
  task_counts: Record<string, number>;
  last_errors: Record<string, string>;
  queue_depth: number;
  supported_tasks: string[];
}

export interface MaintenancePruneResponse {
  pruned_failed_answers: number;
  pruned_historical_answers: number;
  pruned_agent_runs: number;
  pruned_audit_logs: number;
  total_pruned: number;
  retention_cutoffs: Record<string, string>;
}

export interface ExecutiveReportItem {
  id: string;
  client_id: string;
  title: string;
  report_type: string;
  metrics_summary: Record<string, any>;
  storage_url?: string;
  created_at?: string;
}

export const reportsApi = {
  generate: (clientId: string, data?: { title?: string; report_type?: string }) =>
    api.post<ExecutiveReportItem>(`/reports/${clientId}/generate`, data ?? {}),
  list: (clientId: string) =>
    api.get<ExecutiveReportItem[]>(`/reports/${clientId}`),
  exportUrl: (reportId: string, format: "html" | "json" = "html") =>
    `/api/v1/reports/${reportId}/export?format=${format}`,
};

export interface SearchSummary {
  client_id: string;
  days: number;
  total_clicks: number;
  total_impressions: number;
  average_ctr: number;
  average_position: number;
  total_aio_impressions: number;
  total_sessions: number;
  total_ai_sessions: number;
  ai_session_share_pct: number;
  ai_engaged_sessions: number;
  ai_conversions: number;
  estimated_referral_value_usd: number;
  attribution_disclaimer: string;
}

export interface SearchTimeseriesPoint {
  day: string;
  clicks: number;
  impressions: number;
  aio_impressions: number;
  ai_sessions: number;
  total_sessions: number;
}

export interface AIReferrerBreakdown {
  source: string;
  engine: string;
  sessions: number;
  engaged_sessions: number;
  conversions: number;
  share_of_ai_pct: number;
}

export interface TopSearchQuery {
  query: string;
  page?: string | null;
  clicks: number;
  impressions: number;
  position: number;
  is_tracked_prompt: boolean;
  prompt_id?: string | null;
}

export interface IntegrationStatus {
  provider: string;
  account_ref?: string | null;
  status: string;
  last_synced_at?: string | null;
  sync_status: string;
  sync_error?: string | null;
}

export const searchAnalyticsApi = {
  getSummary: (clientId: string, days: number = 30) =>
    api.get<SearchSummary>(`/clients/${clientId}/analytics/search/summary?days=${days}`),
  getTimeseries: (clientId: string, days: number = 30) =>
    api.get<SearchTimeseriesPoint[]>(`/clients/${clientId}/analytics/search/timeseries?days=${days}`),
  getAIReferrals: (clientId: string, days: number = 30) =>
    api.get<AIReferrerBreakdown[]>(`/clients/${clientId}/analytics/search/ai-referrals?days=${days}`),
  getQueries: (clientId: string, days: number = 30, limit: number = 25) =>
    api.get<TopSearchQuery[]>(`/clients/${clientId}/analytics/search/queries?days=${days}&limit=${limit}`),
  syncNow: (clientId: string, days: number = 14) =>
    api.post<{ status: string; client_id: string; synced_days: number }>(`/clients/${clientId}/analytics/search/sync-now?days=${days}`, {}),
};

export const integrationsApi = {
  getStatus: (clientId: string) =>
    api.get<IntegrationStatus[]>(`/clients/${clientId}/integrations/status`),
  connectDemo: (clientId: string) =>
    api.post<{ status: string; details: any }>(`/clients/${clientId}/integrations/connect-demo`, {}),
};

