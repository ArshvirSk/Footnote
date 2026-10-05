"use client";

import { useEffect, useState } from "react";
import { Bot, Download, Globe, Loader2, Play, RefreshCw } from "lucide-react";
import {
  audits,
  clients,
  getDefaultClientId,
  getSelectedClientId,
  setSelectedClientId,
  type Audit,
  type AuditDetail,
  type AuditFinding,
  type AuditRerunResponse,
  type AuditSpeed,
  type Client,
  type RobotsBotRule,
} from "../../../../lib/api";

const SEVERITY_STYLES: Record<string, string> = {
  critical: "bg-rose-50 text-rose-700 border-rose-200",
  high: "bg-orange-50 text-orange-700 border-orange-200",
  medium: "bg-amber-50 text-amber-700 border-amber-200",
  low: "bg-slate-50 text-slate-600 border-slate-200",
};

const STATUS_STYLES: Record<string, string> = {
  open: "bg-slate-100 text-slate-600 border-slate-200",
  in_progress: "bg-sky-50 text-sky-700 border-sky-200",
  fixed: "bg-emerald-50 text-emerald-700 border-emerald-200",
  ignored: "bg-slate-50 text-slate-400 border-slate-200",
};

const STATUS_LABELS: Record<string, string> = {
  open: "open",
  in_progress: "in progress",
  fixed: "fixed",
  ignored: "ignored",
};

const CATEGORY_LABELS: Record<string, string> = {
  schema: "Structured Data",
  meta: "Meta Tags",
  robots: "robots.txt / AI crawlers",
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

function RobotsTable({ rules }: { rules: RobotsBotRule[] | undefined }) {
  if (rules === undefined) {
    return <div className="text-sm text-slate-400">This audit predates AI-crawler checks — re-run to populate.</div>;
  }
  if (rules.length === 0) {
    return <div className="text-sm text-slate-400">No robots.txt groups parsed — file missing or unreachable.</div>;
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead className="text-xs text-slate-500 border-b border-slate-100">
          <tr>
            <th className="py-2 pr-4 font-medium">AI crawler</th>
            <th className="py-2 pr-4 font-medium">Matched group</th>
            <th className="py-2 pr-4 font-medium">Access</th>
            <th className="py-2 font-medium">Rule</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-50">
          {rules.map((r) => (
            <tr key={r.bot}>
              <td className="py-1.5 pr-4 text-slate-800 font-medium">{r.bot}</td>
              <td className="py-1.5 pr-4 text-xs text-slate-500">{r.group === "none" ? "—" : r.group}</td>
              <td className="py-1.5 pr-4">
                <span
                  className={`px-2 py-0.5 rounded-full text-xs border ${
                    r.allowed
                      ? "bg-emerald-50 text-emerald-700 border-emerald-200"
                      : "bg-rose-50 text-rose-700 border-rose-200"
                  }`}
                >
                  {r.allowed ? "Allowed" : "Blocked"}
                </span>
              </td>
              <td className="py-1.5 text-xs text-slate-500">{r.rule ?? "no matching rule"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function PageSpeedCard({ speed }: { speed: AuditSpeed | undefined }) {
  if (!speed) {
    return <div className="text-sm text-slate-400">This audit predates PageSpeed checks — re-run to populate.</div>;
  }
  if (speed.status === "not_configured") {
    return (
      <div className="text-sm text-slate-500">
        Not configured — set <code className="text-xs bg-slate-100 px-1 rounded">PAGESPEED_API_KEY</code> to include
        mobile Lighthouse metrics in audits.
      </div>
    );
  }
  if (speed.status === "error") {
    return <div className="text-sm text-rose-600">Unavailable: {speed.reason ?? "unknown error"}</div>;
  }
  const metrics: [string, string][] = [
    ["Performance", speed.performance_score != null ? `${speed.performance_score}/100` : "—"],
    ["LCP", speed.lcp_ms != null ? `${(speed.lcp_ms / 1000).toFixed(1)}s` : "—"],
    ["CLS", speed.cls != null ? String(speed.cls) : "—"],
    ["TBT", speed.tbt_ms != null ? `${speed.tbt_ms}ms` : "—"],
    ["FCP", speed.fcp_ms != null ? `${(speed.fcp_ms / 1000).toFixed(1)}s` : "—"],
    ["Speed Index", speed.si_ms != null ? `${(speed.si_ms / 1000).toFixed(1)}s` : "—"],
  ];
  return (
    <div className="grid grid-cols-3 gap-3">
      {metrics.map(([label, value]) => (
        <div key={label} className="bg-slate-50 rounded-lg px-3 py-2">
          <div className="text-xs text-slate-500">{label}</div>
          <div className="text-sm font-semibold text-slate-800 mt-0.5">{value}</div>
        </div>
      ))}
      <div className="col-span-3 text-xs text-slate-400">Mobile Lighthouse · fetched {speed.fetched_at ? new Date(speed.fetched_at).toLocaleString() : "—"}</div>
    </div>
  );
}

function RerunDiff({ diff }: { diff: AuditRerunResponse }) {
  const groups: [string, AuditFinding[], string][] = [
    ["verified fixed", diff.fixed, "text-emerald-700 bg-emerald-50 border-emerald-200"],
    ["still present", diff.still_present, "text-amber-700 bg-amber-50 border-amber-200"],
    ["regressed", diff.regressed, "text-rose-700 bg-rose-50 border-rose-200"],
    ["new", diff.new, "text-sky-700 bg-sky-50 border-sky-200"],
  ];
  return (
    <div className="bg-white border border-slate-200 rounded-xl shadow-sm px-5 py-4">
      <div className="font-medium text-slate-900 mb-2">Fix verification — re-run compared by rule</div>
      <div className="flex flex-wrap gap-2">
        {groups.map(([label, items, cls]) => (
          <span key={label} className={`px-3 py-1 rounded-full text-xs border ${cls}`}>
            {items.length} {label}
          </span>
        ))}
      </div>
      {(diff.fixed.length > 0 || diff.regressed.length > 0) && (
        <div className="mt-3 space-y-1 text-xs">
          {diff.fixed.map((f) => (
            <div key={f.id} className="text-emerald-700">
              ✅ {f.rule} — verified fixed
            </div>
          ))}
          {diff.regressed.map((f) => (
            <div key={f.id} className="text-rose-700">
              ⚠️ {f.rule} — regressed (was fixed, now present again)
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default function SiteAuditPage() {
  const [clientList, setClientList] = useState<Client[]>([]);
  const [clientId, setClientId] = useState<string | null>(null);
  const [history, setHistory] = useState<Audit[]>([]);
  const [detail, setDetail] = useState<AuditDetail | null>(null);
  const [rerunDiff, setRerunDiff] = useState<AuditRerunResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [rerunning, setRerunning] = useState(false);
  const [briefBusy, setBriefBusy] = useState(false);
  const [busyFindingId, setBusyFindingId] = useState<string | null>(null);
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

  async function reloadHistory(id: string) {
    setHistory(await audits.list(id));
  }

  async function switchClient(id: string) {
    setSelectedClientId(id);
    setClientId(id);
    setDetail(null);
    setRerunDiff(null);
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
    setRerunDiff(null);
    try {
      const result = await audits.start(clientId);
      setDetail(result);
      await reloadHistory(clientId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Audit failed");
    } finally {
      setRunning(false);
    }
  }

  async function verifyFixes() {
    if (!clientId || !detail) return;
    setRerunning(true);
    setError(null);
    try {
      const result = await audits.rerun(clientId, detail.id);
      setDetail(result.audit);
      setRerunDiff(result);
      await reloadHistory(clientId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Re-run failed");
    } finally {
      setRerunning(false);
    }
  }

  async function triage(finding: AuditFinding, status: string) {
    if (!clientId || !detail) return;
    setBusyFindingId(finding.id);
    try {
      const updated = await audits.updateFinding(clientId, detail.id, finding.id, status);
      setDetail({
        ...detail,
        findings: detail.findings.map((f) => (f.id === updated.id ? updated : f)),
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update finding");
    } finally {
      setBusyFindingId(null);
    }
  }

  async function downloadBrief() {
    if (!clientId || !detail) return;
    setBriefBusy(true);
    try {
      const brief = await audits.brief(clientId, detail.id);
      const blob = new Blob([brief.markdown], { type: "text/markdown" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = brief.filename;
      link.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to build dev brief");
    } finally {
      setBriefBusy(false);
    }
  }

  async function openAudit(auditId: string) {
    if (!clientId) return;
    try {
      setRerunDiff(null);
      setDetail(await audits.get(clientId, auditId));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load audit");
    }
  }

  const severities = (detail?.summary.findings_by_severity ?? {}) as Record<string, number>;
  const robotsRules = detail?.summary.robots_rules as RobotsBotRule[] | undefined;
  const speed = detail?.summary.speed as AuditSpeed | undefined;

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-end gap-4 flex-wrap">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight text-slate-900">Site Audit</h1>
          <p className="text-slate-600 mt-1">
            Crawl the live site and score it for answer-engine readiness: AI-crawler access, structured data, meta,
            robots, sitemap, llms.txt, content and speed.
          </p>
        </div>
        <div className="flex items-center gap-3 flex-wrap">
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
          {detail && (
            <button
              onClick={downloadBrief}
              disabled={briefBusy}
              className="flex items-center px-4 py-2 bg-white border border-slate-300 text-slate-700 rounded-lg hover:bg-slate-50 transition font-medium text-sm shadow-sm disabled:opacity-60"
            >
              {briefBusy ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Download className="w-4 h-4 mr-2" />}
              Dev brief
            </button>
          )}
          {detail && (
            <button
              onClick={verifyFixes}
              disabled={rerunning || running}
              className="flex items-center px-4 py-2 bg-white border border-slate-300 text-slate-700 rounded-lg hover:bg-slate-50 transition font-medium text-sm shadow-sm disabled:opacity-60"
            >
              {rerunning ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <RefreshCw className="w-4 h-4 mr-2" />}
              {rerunning ? "Verifying…" : "Verify fixes (re-run)"}
            </button>
          )}
          <button
            onClick={runAudit}
            disabled={running || rerunning || !clientId}
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

      {rerunDiff && <RerunDiff diff={rerunDiff} />}

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
            <div className="px-6 py-4 border-b border-slate-100 font-medium text-slate-900 flex justify-between items-center">
              <span>Findings ({detail.findings.length})</span>
              <span className="text-xs text-slate-400">click to triage · re-run to verify</span>
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
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-sm font-medium text-slate-800">
                          {CATEGORY_LABELS[f.category] ?? f.category} — {f.rule.replace(/_/g, " ")}
                        </span>
                        <span className={`px-2 py-0.5 rounded-full text-[10px] uppercase tracking-wide border ${STATUS_STYLES[f.status] ?? STATUS_STYLES.open}`}>
                          {STATUS_LABELS[f.status] ?? f.status}
                        </span>
                        {f.fix_owner === "client_dev" && (
                          <span className="px-2 py-0.5 rounded-full text-[10px] uppercase tracking-wide bg-violet-50 text-violet-700 border-violet-200">
                            client dev
                          </span>
                        )}
                      </div>
                      <div className="text-sm text-slate-600 break-words">{f.detail}</div>
                      {f.url && <div className="text-xs text-slate-400 truncate">{f.url}</div>}
                      {f.suggested_fix && (
                        <div className="text-xs text-slate-500 mt-1">
                          <span className="font-medium text-slate-600">Fix:</span> {f.suggested_fix}
                        </div>
                      )}
                      <div className="mt-1.5 flex items-center gap-3 text-xs">
                        {f.status !== "fixed" && f.status !== "in_progress" && (
                          <button
                            onClick={() => triage(f, "in_progress")}
                            disabled={busyFindingId === f.id}
                            className="text-sky-700 hover:underline disabled:opacity-50"
                          >
                            Start
                          </button>
                        )}
                        {f.status !== "ignored" && (
                          <button
                            onClick={() => triage(f, "ignored")}
                            disabled={busyFindingId === f.id}
                            className="text-slate-500 hover:underline disabled:opacity-50"
                          >
                            Ignore
                          </button>
                        )}
                        {f.status !== "open" && (
                          <button
                            onClick={() => triage(f, "open")}
                            disabled={busyFindingId === f.id}
                            className="text-slate-500 hover:underline disabled:opacity-50"
                          >
                            Reopen
                          </button>
                        )}
                        {f.status === "fixed" && f.verified_at && (
                          <span className="text-emerald-600">verified {new Date(f.verified_at).toLocaleString()}</span>
                        )}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {/* AI crawler access + PageSpeed */}
      {detail && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-5">
            <div className="flex items-center gap-2 mb-4">
              <Bot className="w-4 h-4 text-slate-500" />
              <h2 className="font-medium text-slate-900">AI crawler access (robots.txt)</h2>
            </div>
            <RobotsTable rules={robotsRules} />
          </div>
          <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-5">
            <div className="flex items-center justify-between mb-4">
              <h2 className="font-medium text-slate-900">PageSpeed (mobile)</h2>
              <span className="text-xs text-slate-400">Lighthouse via PageSpeed Insights</span>
            </div>
            <PageSpeedCard speed={speed} />
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
                    {a.rerun_of ? <span className="ml-2 text-xs text-slate-400">re-run</span> : null}
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
