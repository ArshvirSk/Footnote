"use client";

import { useEffect, useState } from "react";
import { Globe, Loader2, Play } from "lucide-react";
import {
  audits,
  clients,
  getDefaultClientId,
  getSelectedClientId,
  setSelectedClientId,
  type Audit,
  type AuditDetail,
  type Client,
} from "../../../../lib/api";

const SEVERITY_STYLES: Record<string, string> = {
  critical: "bg-rose-50 text-rose-700 border-rose-200",
  high: "bg-orange-50 text-orange-700 border-orange-200",
  medium: "bg-amber-50 text-amber-700 border-amber-200",
  low: "bg-slate-50 text-slate-600 border-slate-200",
};

const CATEGORY_LABELS: Record<string, string> = {
  schema: "Structured Data",
  meta: "Meta Tags",
  robots: "robots.txt",
  llms_txt: "llms.txt",
  sitemap: "Sitemap",
  speed: "Speed",
  entity: "Content / Entity",
};

function scoreColor(score: number | null): string {
  if (score === null) return "text-slate-400";
  if (score >= 80) return "text-emerald-600";
  if (score >= 50) return "text-amber-600";
  return "text-rose-600";
}

export default function SiteAuditPage() {
  const [clientList, setClientList] = useState<Client[]>([]);
  const [clientId, setClientId] = useState<string | null>(null);
  const [history, setHistory] = useState<Audit[]>([]);
  const [detail, setDetail] = useState<AuditDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function refresh(id: string) {
    const list = await audits.list(id);
    setHistory(list);
    if (list.length > 0 && list[0].finished_at) {
      setDetail(await audits.get(id, list[0].id));
    } else {
      setDetail(null);
    }
  }

  async function switchClient(id: string) {
    setSelectedClientId(id);
    setClientId(id);
    setDetail(null);
    setError(null);
    try {
      await refresh(id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load audits");
    }
  }

  useEffect(() => {
    (async () => {
      try {
        const list = await clients.list();
        setClientList(list);
        const id = await getDefaultClientId();
        setClientId(getSelectedClientId() ?? id);
        await refresh(id);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load audits");
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  async function runAudit() {
    if (!clientId) return;
    setRunning(true);
    setError(null);
    try {
      const result = await audits.start(clientId);
      setDetail(result);
      await refresh(clientId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Audit failed");
    } finally {
      setRunning(false);
    }
  }

  async function openAudit(auditId: string) {
    if (!clientId) return;
    try {
      setDetail(await audits.get(clientId, auditId));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load audit");
    }
  }

  const severities = (detail?.summary.findings_by_severity ?? {}) as Record<string, number>;

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-end gap-4 flex-wrap">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight text-slate-900">Site Audit</h1>
          <p className="text-slate-600 mt-1">
            Crawl the live site and score it for answer-engine readiness: structured data, meta, robots, sitemap, llms.txt, content.
          </p>
        </div>
        <div className="flex items-center gap-3">
          {clientList.length > 1 && (
            <select
              value={clientId ?? ""}
              onChange={(e) => switchClient(e.target.value)}
              aria-label="Select website to audit"
              className="px-3 py-2 border border-slate-300 rounded-lg text-sm bg-white focus:outline-none focus:ring-2 focus:ring-slate-900"
            >
              {clientList.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name} ({c.primary_domain})
                </option>
              ))}
            </select>
          )}
          <button
            onClick={runAudit}
            disabled={running || !clientId}
            className="flex items-center px-4 py-2 bg-slate-900 text-white rounded-lg hover:bg-slate-800 transition font-medium text-sm shadow-sm disabled:opacity-60"
          >
            {running ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Play className="w-4 h-4 mr-2" />}
            {running ? "Auditing live site…" : "Run audit"}
          </button>
        </div>
      </div>

      {error && (
        <div className="text-sm text-rose-600 bg-rose-50 border border-rose-200 rounded-lg px-4 py-3">{error}</div>
      )}

      {loading && <div className="text-slate-400 text-sm">Loading audits…</div>}

      {!loading && !detail && !running && (
        <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-10 text-center text-slate-400">
          <Globe className="w-8 h-8 mx-auto mb-3 text-slate-300" />
          No audits yet — run the first one against this client&apos;s website.
        </div>
      )}

      {detail && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Score card */}
          <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-6">
            <div className="text-sm text-slate-500 mb-1">AEO readiness score</div>
            <div className={`text-5xl font-semibold ${scoreColor(detail.score)}`}>
              {detail.score !== null ? Math.round(detail.score) : "—"}
              <span className="text-xl text-slate-400 font-normal">/100</span>
            </div>
            <div className="mt-4 space-y-1.5 text-sm">
              {(["critical", "high", "medium", "low"] as const).map((sev) => (
                <div key={sev} className="flex justify-between">
                  <span className="capitalize text-slate-600">{sev}</span>
                  <span className="font-medium text-slate-900">{severities[sev] ?? 0}</span>
                </div>
              ))}
            </div>
            <div className="mt-4 pt-4 border-t border-slate-100 text-xs text-slate-500 space-y-1">
              <div>Host: {String(detail.summary.host ?? "—")}</div>
              <div>Pages crawled: {String(detail.summary.pages_crawled ?? 0)}</div>
              <div>Sitemap URLs: {String(detail.summary.sitemap_urls ?? 0)}</div>
              {detail.finished_at && <div>Finished: {new Date(detail.finished_at).toLocaleString()}</div>}
            </div>
          </div>

          {/* Findings */}
          <div className="lg:col-span-2 bg-white border border-slate-200 rounded-xl shadow-sm overflow-hidden">
            <div className="px-6 py-4 border-b border-slate-100 font-medium text-slate-900">
              Findings ({detail.findings.length})
            </div>
            {detail.findings.length === 0 ? (
              <div className="px-6 py-8 text-center text-emerald-600">No issues found — clean audit.</div>
            ) : (
              <div className="divide-y divide-slate-100 max-h-[32rem] overflow-auto">
                {detail.findings.map((f) => (
                  <div key={f.id} className="px-6 py-3 flex items-start gap-3">
                    <span
                      className={`px-2 py-0.5 rounded text-xs font-medium border uppercase shrink-0 ${SEVERITY_STYLES[f.severity] ?? SEVERITY_STYLES.low}`}
                    >
                      {f.severity}
                    </span>
                    <div className="min-w-0">
                      <div className="text-sm font-medium text-slate-800">
                        {CATEGORY_LABELS[f.category] ?? f.category} — {f.rule.replace(/_/g, " ")}
                      </div>
                      <div className="text-sm text-slate-600 break-words">{f.detail}</div>
                      {f.url && <div className="text-xs text-slate-400 truncate">{f.url}</div>}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {/* History + crawled pages */}
      {detail && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <div className="bg-white border border-slate-200 rounded-xl shadow-sm overflow-hidden">
            <div className="px-6 py-4 border-b border-slate-100 font-medium text-slate-900">Audit history</div>
            <div className="divide-y divide-slate-100">
              {history.length === 0 && <div className="px-6 py-4 text-sm text-slate-400">No history.</div>}
              {history.map((a) => (
                <button
                  key={a.id}
                  onClick={() => openAudit(a.id)}
                  className={`w-full px-6 py-3 flex justify-between items-center text-left hover:bg-slate-50 transition ${
                    a.id === detail.id ? "bg-slate-50" : ""
                  }`}
                >
                  <span className="text-sm text-slate-600">
                    {a.started_at ? new Date(a.started_at).toLocaleString() : "—"}
                  </span>
                  <span className={`text-sm font-semibold ${scoreColor(a.score)}`}>
                    {a.score !== null ? Math.round(a.score) : "running"}
                  </span>
                </button>
              ))}
            </div>
          </div>

          <div className="bg-white border border-slate-200 rounded-xl shadow-sm overflow-hidden">
            <div className="px-6 py-4 border-b border-slate-100 font-medium text-slate-900">
              Crawled pages ({detail.pages.length})
            </div>
            <div className="divide-y divide-slate-100 max-h-80 overflow-auto">
              {detail.pages.length === 0 && <div className="px-6 py-4 text-sm text-slate-400">No pages stored.</div>}
              {detail.pages.map((p) => (
                <div key={p.url} className="px-6 py-3">
                  <div className="flex justify-between gap-3">
                    <span className="text-sm font-medium text-slate-800 truncate">{p.title || p.url}</span>
                    <span className={`text-xs shrink-0 ${p.status_code === 200 ? "text-emerald-600" : "text-rose-600"}`}>
                      {p.status_code ?? "—"}
                    </span>
                  </div>
                  <div className="text-xs text-slate-400 truncate">{p.url}</div>
                  {p.word_count !== null && <div className="text-xs text-slate-500 mt-0.5">{p.word_count} words</div>}
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
