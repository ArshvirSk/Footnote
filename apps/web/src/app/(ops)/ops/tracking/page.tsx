"use client";

import { useCallback, useEffect, useState } from "react";
import { AlertCircle, Check, Link2, TrendingUp } from "lucide-react";
import {
  getDefaultClientId,
  trackingApi,
  type CompetitorIntelligenceResponse,
  type CompetitorMatrixResponse,
  type DailyMetric,
  type DomainCitationsResponse,
} from "../../../../lib/api";
import { formatDate, pct } from "../../../../lib/ui";

const DAY_OPTIONS = [7, 14, 30];

const TAXONOMY_CLASS: Record<string, string> = {
  owned: "bg-emerald-50 text-emerald-700 border-emerald-200",
  competitor: "bg-rose-50 text-rose-700 border-rose-200",
  review_site: "bg-violet-50 text-violet-700 border-violet-200",
  forum: "bg-sky-50 text-sky-700 border-sky-200",
  news: "bg-amber-50 text-amber-700 border-amber-200",
  wiki: "bg-slate-100 text-slate-600 border-slate-200",
  publisher: "bg-indigo-50 text-indigo-700 border-indigo-200",
  marketplace: "bg-orange-50 text-orange-700 border-orange-200",
  gov_edu: "bg-teal-50 text-teal-700 border-teal-200",
};

function taxonomyClass(type: string): string {
  return TAXONOMY_CLASS[type] ?? "bg-slate-100 text-slate-600 border-slate-200";
}

interface DayAggregate {
  day: string;
  tracked: number;
  visible: number;
  brandCitations: number;
  totalCitations: number;
  sovWeighted: number;
  sovWeight: number;
}

function aggregateByDay(metrics: DailyMetric[]): DayAggregate[] {
  const byDay = new Map<string, DayAggregate>();
  for (const m of metrics) {
    const agg = byDay.get(m.day) ?? {
      day: m.day,
      tracked: 0,
      visible: 0,
      brandCitations: 0,
      totalCitations: 0,
      sovWeighted: 0,
      sovWeight: 0,
    };
    agg.tracked += m.prompts_tracked;
    agg.visible += m.prompts_visible;
    agg.brandCitations += m.brand_citations;
    agg.totalCitations += m.total_citations;
    agg.sovWeighted += m.share_of_voice * m.total_citations;
    agg.sovWeight += m.total_citations;
    byDay.set(m.day, agg);
  }
  return [...byDay.values()].sort((a, b) => a.day.localeCompare(b.day));
}

function TrendBars({ days }: { days: DayAggregate[] }) {
  if (days.length === 0) {
    return <div className="text-sm text-slate-400">No daily metrics yet — run a collection first.</div>;
  }
  return (
    <div className="flex items-end gap-1.5 h-32">
      {days.map((d) => {
        const rate = d.tracked > 0 ? d.visible / d.tracked : 0;
        return (
          <div key={d.day} className="flex-1 flex flex-col items-center justify-end h-full group relative">
            <div className="absolute bottom-full mb-1 hidden group-hover:block bg-slate-900 text-white text-xs rounded px-2 py-1 whitespace-nowrap z-10">
              {formatDate(d.day)} · {pct(rate)} visible ({d.visible}/{d.tracked})
            </div>
            <div
              className="w-full max-w-8 bg-emerald-500/80 group-hover:bg-emerald-600 rounded-t transition-all"
              style={{ height: `${Math.max(rate * 100, rate > 0 ? 4 : 1)}%` }}
            />
          </div>
        );
      })}
    </div>
  );
}

function DomainList({ data }: { data: DomainCitationsResponse }) {
  if (data.domains.length === 0) {
    return <div className="text-sm text-slate-400">No citations collected in this window.</div>;
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead className="text-xs text-slate-500 border-b border-slate-100">
          <tr>
            <th className="py-2 pr-4 font-medium">Domain</th>
            <th className="py-2 pr-4 font-medium">Type</th>
            <th className="py-2 pr-4 font-medium text-right">Citations</th>
            <th className="py-2 pr-4 font-medium text-right">Answers</th>
            <th className="py-2 font-medium w-1/3">Share</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-50">
          {data.domains.map((d) => (
            <tr key={d.domain} className="hover:bg-slate-50/50">
              <td className="py-2 pr-4">
                <span className="inline-flex items-center gap-1.5 text-slate-800">
                  {d.is_brand && <Check className="w-3.5 h-3.5 text-emerald-500" />}
                  {d.is_competitor && <AlertCircle className="w-3.5 h-3.5 text-rose-500" />}
                  {d.domain}
                </span>
              </td>
              <td className="py-2 pr-4">
                <span className={`px-2 py-0.5 rounded-full text-xs border ${taxonomyClass(d.domain_type)}`}>
                  {d.domain_type.replace("_", " ")}
                </span>
              </td>
              <td className="py-2 pr-4 text-right text-slate-700">{d.citations}</td>
              <td className="py-2 pr-4 text-right text-slate-500">{d.answers}</td>
              <td className="py-2">
                <div className="flex items-center gap-2">
                  <div className="flex-1 h-1.5 bg-slate-100 rounded-full overflow-hidden">
                    <div className="h-full bg-slate-700 rounded-full" style={{ width: `${Math.min(d.share * 100, 100)}%` }} />
                  </div>
                  <span className="text-xs text-slate-500 w-12 text-right">{pct(d.share)}</span>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function CompetitorMatrix({ matrix }: { matrix: CompetitorMatrixResponse }) {
  const rows = matrix.rows.filter((r) => r.runs > 0);
  if (rows.length === 0) {
    return <div className="text-sm text-slate-400">No runs in this window — accept prompts and collect to build the matrix.</div>;
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead className="text-xs text-slate-500 border-b border-slate-100">
          <tr>
            <th className="py-2 pr-4 font-medium">Prompt</th>
            <th className="py-2 pr-4 font-medium">Runs</th>
            <th className="py-2 pr-4 font-medium">Brand</th>
            <th className="py-2 font-medium">Competitors seen</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-50">
          {rows.map((r) => (
            <tr key={r.prompt_id} className="hover:bg-slate-50/50 align-top">
              <td className="py-2 pr-4 text-slate-800 max-w-md">
                {r.prompt_text}
                {r.funnel_stage && (
                  <span className="ml-2 px-1.5 py-0.5 rounded text-[10px] uppercase tracking-wide bg-slate-100 text-slate-500 border border-slate-200">
                    {r.funnel_stage}
                  </span>
                )}
              </td>
              <td className="py-2 pr-4 text-slate-500">{r.runs}</td>
              <td className="py-2 pr-4">
                <span
                  className={`px-2 py-0.5 rounded-full text-xs border ${
                    r.brand_visible
                      ? "bg-emerald-50 text-emerald-700 border-emerald-200"
                      : "bg-slate-50 text-slate-500 border-slate-200"
                  }`}
                >
                  {r.brand_visible ? "Visible" : "Absent"} {r.brand_runs}/{r.runs}
                </span>
              </td>
              <td className="py-2">
                {r.competitors.length === 0 ? (
                  <span className="text-xs text-slate-400">none</span>
                ) : (
                  <div className="flex flex-wrap gap-1.5">
                    {r.competitors.map((c) => (
                      <span
                        key={c.competitor_id}
                        className="px-2 py-0.5 rounded text-xs bg-rose-50 text-rose-700 border border-rose-200"
                      >
                        {c.name} · {c.runs_with_mention}
                      </span>
                    ))}
                  </div>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function CompetitorIntelligence({ data }: { data: CompetitorIntelligenceResponse }) {
  const [open, setOpen] = useState<string | null>(null);
  if (data.competitors.length === 0) {
    return <div className="text-sm text-slate-400">No competitors tracked — add them on the website page first.</div>;
  }
  return (
    <div className="divide-y divide-slate-100">
      {data.competitors.map((c) => (
        <div key={c.competitor_id} className="py-3">
          <button
            onClick={() => setOpen(open === c.competitor_id ? null : c.competitor_id)}
            className="w-full flex items-center justify-between gap-4 text-left"
          >
            <div className="min-w-0">
              <div className="text-sm font-medium text-slate-800">
                {c.name}
                {c.domain && <span className="ml-2 text-xs font-normal text-slate-400">{c.domain}</span>}
              </div>
              <div className="text-xs text-slate-500 mt-0.5">
                {c.mentions} mentions · {c.citations} citations · appears in {c.prompts_present} prompts
              </div>
            </div>
            <div className="flex items-center gap-2 shrink-0 w-44">
              <div className="flex-1 h-1.5 bg-slate-100 rounded-full overflow-hidden">
                <div
                  className="h-full bg-rose-500 rounded-full"
                  style={{ width: `${Math.min((c.share_of_voice ?? 0) * 100, 100)}%` }}
                />
              </div>
              <span className="text-xs text-slate-500 w-20 text-right">SOV {pct(c.share_of_voice)}</span>
            </div>
          </button>
          {open === c.competitor_id && (
            <div className="mt-3 grid grid-cols-1 md:grid-cols-2 gap-4 text-xs">
              <div>
                <div className="font-medium text-slate-600 mb-1">Most-cited pages</div>
                {c.top_pages.length === 0 ? (
                  <div className="text-slate-400">No citations in this window.</div>
                ) : (
                  <ul className="space-y-1">
                    {c.top_pages.map((p) => (
                      <li key={p.url} className="text-slate-700 break-all">
                        {p.title || p.url} <span className="text-slate-400">· {p.citations} citations</span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
              <div>
                <div className="font-medium text-slate-600 mb-1">Prompts where they show and we don&apos;t</div>
                {c.gap_prompts.length === 0 ? (
                  <div className="text-slate-400">No open prompts — brand present wherever they appear.</div>
                ) : (
                  <ul className="space-y-1">
                    {c.gap_prompts.map((p) => (
                      <li key={p.prompt_id} className="text-slate-700">
                        “{p.prompt_text}” <span className="text-slate-400">· {p.hits}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

export default function TrackingPage() {
  const [clientId, setClientId] = useState<string | null>(null);
  const [metrics, setMetrics] = useState<DailyMetric[]>([]);
  const [domains, setDomains] = useState<DomainCitationsResponse | null>(null);
  const [matrix, setMatrix] = useState<CompetitorMatrixResponse | null>(null);
  const [intel, setIntel] = useState<CompetitorIntelligenceResponse | null>(null);
  const [days, setDays] = useState(14);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (windowDays: number, cid?: string) => {
    try {
      const client = cid ?? (await getDefaultClientId());
      if (!cid) setClientId(client);
      const [m, d, mx, ci] = await Promise.all([
        trackingApi.dailyMetrics(client, windowDays),
        trackingApi.domains(client, windowDays),
        trackingApi.matrix(client, windowDays),
        trackingApi.competitorIntelligence(client, windowDays),
      ]);
      setMetrics(m);
      setDomains(d);
      setMatrix(mx);
      setIntel(ci);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load tracking data");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void (async () => load(14))();
  }, [load]);

  async function changeDays(next: number) {
    setDays(next);
    await load(next, clientId ?? undefined);
  }

  const byDay = aggregateByDay(metrics);
  const tracked = byDay.reduce((s, d) => s + d.tracked, 0);
  const visible = byDay.reduce((s, d) => s + d.visible, 0);
  const mentionRate = tracked > 0 ? visible / tracked : null;
  const sovWeighted = byDay.reduce((s, d) => s + d.sovWeighted, 0);
  const sovWeight = byDay.reduce((s, d) => s + d.sovWeight, 0);

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-end flex-wrap gap-3">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight text-slate-900">Tracking</h1>
          <p className="text-slate-600 mt-1">Daily visibility, citation sources and competitor presence — from collected answers only.</p>
        </div>
        <div className="flex gap-2">
          {DAY_OPTIONS.map((d) => (
            <button
              key={d}
              onClick={() => void changeDays(d)}
              className={`px-3 py-1.5 rounded-lg text-sm border transition ${
                days === d ? "bg-slate-900 text-white border-slate-900" : "bg-white text-slate-600 border-slate-200 hover:bg-slate-50"
              }`}
            >
              {d}d
            </button>
          ))}
        </div>
      </div>

      {error && <div className="text-sm text-rose-600 bg-rose-50 border border-rose-200 rounded-lg px-4 py-3">{error}</div>}

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-4">
          <div className="text-xs text-slate-500 flex items-center gap-1">
            <TrendingUp className="w-3.5 h-3.5" /> Visibility
          </div>
          <div className="text-xl font-semibold text-slate-900 mt-1">{pct(mentionRate)}</div>
          <div className="text-xs text-slate-400 mt-0.5">
            {visible} of {tracked} prompt-days
          </div>
        </div>
        <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-4">
          <div className="text-xs text-slate-500 flex items-center gap-1">
            <Link2 className="w-3.5 h-3.5" /> Citation share
          </div>
          <div className="text-xl font-semibold text-slate-900 mt-1">{pct(domains?.brand_share ?? null)}</div>
          <div className="text-xs text-slate-400 mt-0.5">
            {domains?.brand_citations ?? 0} of {domains?.total_citations ?? 0} citations own the brand
          </div>
        </div>
        <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-4">
          <div className="text-xs text-slate-500">Share of voice</div>
          <div className="text-xl font-semibold text-slate-900 mt-1">{sovWeight > 0 ? pct(sovWeighted / sovWeight) : "—"}</div>
          <div className="text-xs text-slate-400 mt-0.5">vs tracked competitors</div>
        </div>
        <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-4">
          <div className="text-xs text-slate-500">Domains cited</div>
          <div className="text-xl font-semibold text-slate-900 mt-1">{domains?.domains.length ?? 0}</div>
          <div className="text-xs text-slate-400 mt-0.5">{days}-day window</div>
        </div>
      </div>

      <section className="bg-white border border-slate-200 rounded-xl shadow-sm p-5">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-medium text-slate-900">Daily visibility</h2>
          <span className="text-xs text-slate-400">share of tracked prompts mentioning the brand</span>
        </div>
        {loading ? <div className="text-sm text-slate-400">Loading…</div> : <TrendBars days={byDay} />}
        {byDay.length > 0 && (
          <div className="flex justify-between text-xs text-slate-400 mt-2">
            <span>{formatDate(byDay[0].day)}</span>
            <span>{formatDate(byDay[byDay.length - 1].day)}</span>
          </div>
        )}
      </section>

      <section className="bg-white border border-slate-200 rounded-xl shadow-sm p-5">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-medium text-slate-900">Citations by domain</h2>
          <span className="text-xs text-slate-400">taxonomy + share of all citations</span>
        </div>
        {domains ? <DomainList data={domains} /> : <div className="text-sm text-slate-400">Loading…</div>}
      </section>

      <section className="bg-white border border-slate-200 rounded-xl shadow-sm p-5">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-medium text-slate-900">Competitor matrix</h2>
          <span className="text-xs text-slate-400">brand visible? which competitors appeared?</span>
        </div>
        {matrix ? <CompetitorMatrix matrix={matrix} /> : <div className="text-sm text-slate-400">Loading…</div>}
      </section>

      <section className="bg-white border border-slate-200 rounded-xl shadow-sm p-5">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-medium text-slate-900">Competitor intelligence</h2>
          <span className="text-xs text-slate-400">their cited pages, share of voice, and prompts they own</span>
        </div>
        {intel ? <CompetitorIntelligence data={intel} /> : <div className="text-sm text-slate-400">Loading…</div>}
      </section>
    </div>
  );
}
