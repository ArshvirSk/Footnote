"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { ArrowRight, CheckCircle2, Info } from "lucide-react";
import {
  CLIENT_CHANGED_EVENT,
  getSelectedClientId,
  setSelectedClientId,
  websites,
  type ClientSummary,
  type WebsiteDashboard,
} from "../../../lib/api";
import DemoBadge from "../../../components/DemoBadge";
import MetricCard from "../../../components/MetricCard";
import SetupChecklist from "../../../components/SetupChecklist";
import { formatDateTime, severityDotClass, statusBadgeClass, statusLabel } from "../../../lib/ui";

export default function OpsDashboard() {
  const [list, setList] = useState<ClientSummary[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [dashboard, setDashboard] = useState<WebsiteDashboard | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadDashboard = useCallback(async (clientId: string) => {
    try {
      setDashboard(await websites.dashboard(clientId));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load dashboard");
    }
  }, []);

  const load = useCallback(async () => {
    try {
      const data = await websites.list(true);
      setList(data);
      const stored = getSelectedClientId();
      const current = data.find((c) => c.id === stored)?.id ?? data.find((c) => !c.is_demo)?.id ?? data[0]?.id ?? null;
      setSelected(current);
      if (current) {
        if (current !== stored) setSelectedClientId(current);
        await loadDashboard(current);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load websites");
    } finally {
      setLoading(false);
    }
  }, [loadDashboard]);

  useEffect(() => {
    // Async IIFE keeps setState out of the synchronous effect body.
    void (async () => {
      await load();
    })();
    const onChanged = () => {
      const stored = getSelectedClientId();
      if (stored) {
        setSelected(stored);
        void loadDashboard(stored);
      }
    };
    window.addEventListener(CLIENT_CHANGED_EVENT, onChanged);
    return () => window.removeEventListener(CLIENT_CHANGED_EVENT, onChanged);
  }, [load, loadDashboard]);

  if (loading) return <div className="text-slate-400 text-sm">Loading dashboard…</div>;

  if (list.length === 0) {
    return (
      <div className="space-y-6">
        <h1 className="text-3xl font-semibold tracking-tight text-slate-900">Dashboard</h1>
        <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-10 text-center">
          <p className="text-slate-600">No websites yet. Add your first website to start tracking AI visibility.</p>
          <Link
            href="/ops/websites"
            className="inline-flex items-center mt-4 px-4 py-2 bg-slate-900 text-white rounded-lg font-medium text-sm hover:bg-slate-800"
          >
            Add a website <ArrowRight className="w-4 h-4 ml-2" />
          </Link>
        </div>
      </div>
    );
  }

  const real = list.filter((c) => !c.is_demo);
  const demoCount = list.length - real.length;
  const portfolioIssues = real.reduce((sum, c) => sum + c.open_issues, 0);
  const portfolioApprovals = real.reduce((sum, c) => sum + c.pending_approvals, 0);
  const withVisibility = real.filter((c) => c.visibility_pct !== null);
  const avgVisibility =
    withVisibility.length > 0
      ? withVisibility.reduce((sum, c) => sum + (c.visibility_pct ?? 0), 0) / withVisibility.length
      : null;

  const client = list.find((c) => c.id === selected) ?? null;
  const kpis = dashboard?.kpis;

  return (
    <div className="space-y-6 max-w-6xl">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight text-slate-900">Dashboard</h1>
          <p className="text-slate-600 mt-1">
            Action queue for the selected website, plus a portfolio summary across your live websites.
          </p>
        </div>
        {client && (
          <div className="flex items-center gap-2">
            <span className="text-sm text-slate-500">Viewing</span>
            <Link href={`/ops/websites/${client.id}`} className="font-medium text-slate-900 hover:underline">
              {client.name}
            </Link>
            <span className={`px-2.5 py-1 rounded-full text-xs font-medium border ${statusBadgeClass(client.derived_status)}`}>
              {statusLabel(client.derived_status)}
            </span>
            {client.is_demo && <DemoBadge />}
          </div>
        )}
      </div>

      {error && (
        <div className="text-sm text-rose-600 bg-rose-50 border border-rose-200 rounded-lg px-4 py-3">{error}</div>
      )}

      {/* Portfolio summary — real websites only; demo rows never count here. */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="bg-white p-5 rounded-xl border border-slate-200 shadow-sm">
          <div className="text-sm text-slate-500">Live websites</div>
          <div className="text-2xl font-semibold text-slate-900 mt-1">{real.length}</div>
          {demoCount > 0 && (
            <div className="text-xs text-slate-400 mt-1">
              {demoCount} demo website{demoCount === 1 ? "" : "s"} hidden ·{" "}
              <Link href="/ops/websites" className="text-blue-600 hover:underline">
                view
              </Link>
            </div>
          )}
        </div>
        <div className="bg-white p-5 rounded-xl border border-slate-200 shadow-sm">
          <div className="text-sm text-slate-500">Open issues</div>
          <div className={`text-2xl font-semibold mt-1 ${portfolioIssues > 0 ? "text-amber-700" : "text-slate-900"}`}>
            {portfolioIssues}
          </div>
          <div className="text-xs text-slate-400 mt-1">across live websites</div>
        </div>
        <div className="bg-white p-5 rounded-xl border border-slate-200 shadow-sm">
          <div className="text-sm text-slate-500">Pending approvals</div>
          <div className="text-2xl font-semibold text-slate-900 mt-1">{portfolioApprovals}</div>
          <div className="text-xs text-slate-400 mt-1">human decisions waiting</div>
        </div>
        <div className="bg-white p-5 rounded-xl border border-slate-200 shadow-sm">
          <div className="text-sm text-slate-500">Avg visibility 7d</div>
          <div className="text-2xl font-semibold text-slate-900 mt-1">
            {avgVisibility !== null ? `${avgVisibility.toFixed(1)}%` : "—"}
          </div>
          <div className="text-xs text-slate-400 mt-1">
            {withVisibility.length > 0 ? `${withVisibility.length} website(s) with collected data` : "no collected data yet"}
          </div>
        </div>
      </div>

      {dashboard && kpis && (
        <>
          {/* Selected website KPIs */}
          <div>
            <div className="flex items-center gap-2 mb-3">
              <h2 className="font-medium text-slate-900">Key metrics — {dashboard.client_name}</h2>
              <span className="text-xs text-slate-400">
                last 7 days vs prior 7 · {kpis.runs_7d} succeeded run(s)
                {kpis.failed_7d > 0 ? `, ${kpis.failed_7d} failed (excluded from rates)` : ""}
              </span>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
              <MetricCard
                label="Visibility"
                metric={kpis.visibility}
                sample={`${kpis.visibility.current} of ${kpis.visibility.base} tracked prompt-engine pairs`}
              />
              <MetricCard
                label="Mention rate"
                metric={kpis.mention_rate}
                sample={`${kpis.mention_rate.current} of ${kpis.mention_rate.base} runs mentioned the brand`}
              />
              <MetricCard
                label="Citation share"
                metric={kpis.citation_share}
                sample={`${kpis.citation_share.current} of ${kpis.citation_share.base} citations on owned domains`}
              />
              <MetricCard
                label="Share of voice"
                metric={kpis.share_of_voice}
                sample={`${kpis.share_of_voice.current} brand vs ${Math.max(0, kpis.share_of_voice.base - kpis.share_of_voice.current)} competitor mentions`}
              />
            </div>
            <div className="flex items-start gap-2 mt-3 text-xs text-slate-500">
              <Info className="w-3.5 h-3.5 mt-0.5 shrink-0 text-slate-400" />
              <span>{dashboard.correlation_note}</span>
            </div>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            {/* Needs attention */}
            <div className="lg:col-span-2 bg-white border border-slate-200 rounded-xl shadow-sm overflow-hidden">
              <div className="px-6 py-4 border-b border-slate-100 flex items-center justify-between">
                <h2 className="font-medium text-slate-900">Needs attention</h2>
                <span className="text-xs text-slate-400">{dashboard.needs_attention.length} item(s)</span>
              </div>
              {dashboard.needs_attention.length === 0 ? (
                <div className="px-6 py-10 text-center text-emerald-600 text-sm">
                  <CheckCircle2 className="w-6 h-6 mx-auto mb-2" />
                  Nothing needs attention right now.
                </div>
              ) : (
                <ul className="divide-y divide-slate-100">
                  {dashboard.needs_attention.map((item) => (
                    <li key={`${item.kind}-${item.title}`}>
                      <Link href={item.href} className="px-6 py-4 flex items-start gap-3 hover:bg-slate-50 transition">
                        <span className={`w-2 h-2 rounded-full mt-2 shrink-0 ${severityDotClass(item.severity)}`} />
                        <div className="min-w-0 flex-1">
                          <div className="text-sm font-medium text-slate-900">{item.title}</div>
                          <div className="text-sm text-slate-500">{item.detail}</div>
                        </div>
                        <span className="text-xs text-slate-400 capitalize shrink-0 mt-0.5">{item.severity}</span>
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            {/* Recent wins */}
            <div className="bg-white border border-slate-200 rounded-xl shadow-sm overflow-hidden">
              <div className="px-6 py-4 border-b border-slate-100">
                <h2 className="font-medium text-slate-900">Recent wins</h2>
              </div>
              {dashboard.recent_wins.length === 0 ? (
                <div className="px-6 py-8 text-sm text-slate-400">
                  No wins recorded yet. Wins appear when a later collection proves a gap is closed or a prompt becomes
                  visible.
                </div>
              ) : (
                <ul className="divide-y divide-slate-100">
                  {dashboard.recent_wins.map((win) => (
                    <li key={`${win.kind}-${win.title}`} className="px-6 py-3">
                      <div className="text-sm font-medium text-slate-800">{win.title}</div>
                      <div className="text-xs text-slate-500 mt-0.5">{win.detail}</div>
                      {win.at && <div className="text-xs text-slate-400 mt-0.5">{formatDateTime(win.at)}</div>}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <SetupChecklist
              items={dashboard.setup.items}
              progress={dashboard.setup.progress}
              total={dashboard.setup.total}
            />
            <div className="space-y-6">
              <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-6">
                <h2 className="font-medium text-slate-900 mb-3">Data sources</h2>
                <div className="space-y-2 text-sm">
                  <div className="flex items-center justify-between gap-3">
                    <span className="text-slate-600">AI engine providers</span>
                    {kpis.engine_providers_configured.length > 0 ? (
                      <span className="text-xs text-emerald-700 bg-emerald-50 border border-emerald-200 rounded-full px-2 py-0.5 font-medium">
                        {kpis.engine_providers_configured.join(", ")}
                      </span>
                    ) : (
                      <span className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-full px-2 py-0.5 font-medium">
                        None configured
                      </span>
                    )}
                  </div>
                  {kpis.engine_providers_configured.length === 0 && (
                    <p className="text-xs text-slate-400">
                      Add a provider API key (e.g. OPENAI_API_KEY) to collect live answers. Until then no answers are
                      collected for any prompt.
                    </p>
                  )}
                  <div className="flex items-center justify-between">
                    <span className="text-slate-600">Last audit score</span>
                    <span className="text-slate-900 font-medium">
                      {kpis.last_audit_score !== null ? `${Math.round(kpis.last_audit_score)}/100` : "—"}
                    </span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-slate-600">Google Search Console / GA4</span>
                    <span className="text-xs text-slate-500 bg-slate-100 border border-slate-200 rounded-full px-2 py-0.5 font-medium">
                      Not connected. Planned.
                    </span>
                  </div>
                </div>
              </div>
              <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-6">
                <h2 className="font-medium text-slate-900 mb-3">Collection health</h2>
                <div className="text-sm text-slate-600 space-y-1">
                  <div>
                    Succeeded runs (7d): <span className="font-medium text-slate-900">{kpis.runs_7d}</span>
                  </div>
                  <div>
                    Failed / skipped (7d):{" "}
                    <span className={`font-medium ${kpis.failed_7d > 0 ? "text-rose-600" : "text-slate-900"}`}>
                      {kpis.failed_7d}
                    </span>
                  </div>
                  <div>
                    Health:{" "}
                    <span className="font-medium text-slate-900">
                      {kpis.collection_health !== null ? `${(kpis.collection_health * 100).toFixed(1)}%` : "—"}
                    </span>
                    <span className="text-xs text-slate-400 ml-1">(succeeded / scheduled, 7d)</span>
                  </div>
                  <div className="text-xs text-slate-400 pt-1">
                    Last collection: {formatDateTime(kpis.last_collection_at)}
                  </div>
                </div>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
