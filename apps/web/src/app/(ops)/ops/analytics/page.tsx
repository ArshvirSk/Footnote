"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  TrendingUp,
  FileCheck,
  Target,
  ArrowUpRight,
  DollarSign,
  Calendar,
  RefreshCw,
  ExternalLink,
  ShieldCheck,
  Sparkles,
  Award,
  AlertCircle,
  Cpu,
  Search,
  Share2,
  Compass,
  MousePointer,
  CheckCircle2,
  BarChart3,
  Info,
} from "lucide-react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  CLIENT_CHANGED_EVENT,
  getSelectedClientId,
  getDefaultClientId,
  analyticsApi,
  searchAnalyticsApi,
  websites,
  type KPIOverview,
  type TimeseriesPoint,
  type WonGap,
  type EngineShare,
  type ClientSummary,
  type SearchSummary,
  type SearchTimeseriesPoint,
  type AIReferrerBreakdown,
  type TopSearchQuery,
} from "@/lib/api";
import { formatDateTime } from "@/lib/ui";

const TIME_RANGES = [
  { label: "Last 7 Days", days: 7 },
  { label: "Last 14 Days", days: 14 },
  { label: "Last 30 Days", days: 30 },
  { label: "Last 90 Days", days: 90 },
  { label: "Year to Date", days: 365 },
];

export default function AnalyticsPage() {
  const [clientId, setClientId] = useState<string | null>(null);
  const [client, setClient] = useState<ClientSummary | null>(null);
  const [days, setDays] = useState<number>(30);
  const [overview, setOverview] = useState<KPIOverview | null>(null);
  const [timeseries, setTimeseries] = useState<TimeseriesPoint[]>([]);
  const [wonGaps, setWonGaps] = useState<WonGap[]>([]);
  const [engineShare, setEngineShare] = useState<EngineShare[]>([]);
  const [searchSummary, setSearchSummary] = useState<SearchSummary | null>(null);
  const [searchTimeseries, setSearchTimeseries] = useState<SearchTimeseriesPoint[]>([]);
  const [aiReferrals, setAiReferrals] = useState<AIReferrerBreakdown[]>([]);
  const [searchQueries, setSearchQueries] = useState<TopSearchQuery[]>([]);
  const [syncingSearch, setSyncingSearch] = useState<boolean>(false);
  const [syncSuccessMsg, setSyncSuccessMsg] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [refreshing, setRefreshing] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [mounted, setMounted] = useState<boolean>(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  const loadData = useCallback(
    async (cid: string, selectedDays: number) => {
      try {
        setRefreshing(true);
        setError(null);
        const [kpis, ts, gaps, engines, searchSum, searchTs, aiRefs, topQ] = await Promise.all([
          analyticsApi.getOverview(cid, selectedDays),
          analyticsApi.getTimeseries(cid, selectedDays),
          analyticsApi.getWonGaps(cid, selectedDays),
          analyticsApi.getEngineShare(cid, selectedDays),
          searchAnalyticsApi.getSummary(cid, selectedDays).catch(() => null),
          searchAnalyticsApi.getTimeseries(cid, selectedDays).catch(() => []),
          searchAnalyticsApi.getAIReferrals(cid, selectedDays).catch(() => []),
          searchAnalyticsApi.getQueries(cid, selectedDays, 15).catch(() => []),
        ]);
        setOverview(kpis);
        setTimeseries(ts);
        setWonGaps(gaps);
        setEngineShare(engines);
        setSearchSummary(searchSum);
        setSearchTimeseries(searchTs);
        setAiReferrals(aiRefs);
        setSearchQueries(topQ);
      } catch (err: any) {
        setError(err?.message || "Failed to load live analytics data");
      } finally {
        setLoading(false);
        setRefreshing(false);
      }
    },
    []
  );

  const handleSyncSearch = async () => {
    if (!clientId) return;
    try {
      setSyncingSearch(true);
      setSyncSuccessMsg(null);
      await searchAnalyticsApi.syncNow(clientId, 14);
      setSyncSuccessMsg("GSC & GA4 analytics synchronized successfully.");
      await loadData(clientId, days);
    } catch (err: any) {
      setError(err?.message || "Failed to synchronize search data");
    } finally {
      setSyncingSearch(false);
    }
  };

  const initClient = useCallback(async () => {
    try {
      setLoading(true);
      const list = await websites.list(true);
      const stored = getSelectedClientId();
      const resolvedId =
        stored && list.some((c) => c.id === stored)
          ? stored
          : list[0]?.id;

      if (!resolvedId) {
        setError("No websites registered yet. Add a website to view analytics.");
        setLoading(false);
        return;
      }

      setClientId(resolvedId);
      const found = list.find((c) => c.id === resolvedId) || null;
      setClient(found);
      await loadData(resolvedId, days);
    } catch (err: any) {
      setError(err?.message || "Failed to initialize active website");
      setLoading(false);
    }
  }, [days, loadData]);

  useEffect(() => {
    void initClient();

    const handleClientChange = () => {
      const stored = getSelectedClientId();
      if (stored && stored !== clientId) {
        setClientId(stored);
        void loadData(stored, days);
      }
    };

    window.addEventListener(CLIENT_CHANGED_EVENT, handleClientChange);
    return () => window.removeEventListener(CLIENT_CHANGED_EVENT, handleClientChange);
  }, [initClient, clientId, days, loadData]);

  const handleTimeRangeChange = (newDays: number) => {
    setDays(newDays);
    if (clientId) {
      void loadData(clientId, newDays);
    }
  };

  const handleManualRefresh = () => {
    if (clientId) {
      void loadData(clientId, days);
    }
  };

  if (loading && !overview) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[400px] text-slate-500 space-y-3">
        <RefreshCw className="w-6 h-6 animate-spin text-blue-600" />
        <p className="text-sm font-medium">Aggregating live telemetry from Neon database…</p>
      </div>
    );
  }

  return (
    <div className="space-y-8">
      {/* Top Header */}
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-3xl font-semibold tracking-tight text-slate-900">
              Analytics & Attribution
            </h1>
            {client && (
              <span className="px-2.5 py-0.5 rounded-full text-xs font-medium bg-blue-50 text-blue-700 border border-blue-200">
                {client.name}
              </span>
            )}
          </div>
          <p className="text-slate-600 mt-1 text-sm">
            Live generative engine performance, competitor citation capture, and won gap proof records.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <button
            onClick={handleManualRefresh}
            disabled={refreshing}
            className="p-2 text-slate-500 hover:text-slate-700 bg-white border border-slate-200 rounded-lg hover:bg-slate-50 transition disabled:opacity-50"
            title="Refresh analytics data"
          >
            <RefreshCw className={`w-4 h-4 ${refreshing ? "animate-spin text-blue-600" : ""}`} />
          </button>

          <div className="flex items-center bg-white border border-slate-200 rounded-lg p-0.5 shadow-sm">
            <Calendar className="w-4 h-4 text-slate-400 ml-2.5 mr-1" />
            <select
              value={days}
              onChange={(e) => handleTimeRangeChange(Number(e.target.value))}
              className="px-2 py-1.5 bg-transparent text-slate-700 text-sm font-medium outline-none cursor-pointer"
            >
              {TIME_RANGES.map((r) => (
                <option key={r.days} value={r.days}>
                  {r.label}
                </option>
              ))}
            </select>
          </div>
        </div>
      </div>

      {error && (
        <div className="flex items-center gap-3 p-4 bg-rose-50 border border-rose-200 rounded-xl text-rose-700 text-sm">
          <AlertCircle className="w-5 h-5 flex-shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* 5 Real KPI Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4">
        {/* Card 1: Content Published */}
        <div className="bg-white p-5 rounded-xl border border-slate-200 shadow-sm flex flex-col justify-between">
          <div>
            <div className="flex items-center text-xs font-semibold uppercase tracking-wider text-slate-400 mb-2">
              <FileCheck className="w-4 h-4 mr-1.5 text-blue-600" /> Content Published
            </div>
            <div className="text-3xl font-bold text-slate-900">
              {overview?.published_content ?? 0}
            </div>
          </div>
          <div className="text-xs text-slate-500 mt-3 pt-2 border-t border-slate-100 flex items-center justify-between">
            <span>Live on web/targets</span>
            <Link href="/ops/pipeline" className="text-blue-600 hover:underline inline-flex items-center">
              View items <ArrowUpRight className="w-3 h-3 ml-0.5" />
            </Link>
          </div>
        </div>

        {/* Card 2: Won Gaps */}
        <div className="bg-white p-5 rounded-xl border border-slate-200 shadow-sm flex flex-col justify-between">
          <div>
            <div className="flex items-center text-xs font-semibold uppercase tracking-wider text-slate-400 mb-2">
              <Target className="w-4 h-4 mr-1.5 text-emerald-600" /> Won Gaps Closed
            </div>
            <div className="text-3xl font-bold text-slate-900">
              {overview?.won_gaps ?? 0}
            </div>
          </div>
          <div className="text-xs text-emerald-600 font-medium mt-3 pt-2 border-t border-slate-100 flex items-center">
            <Award className="w-3.5 h-3.5 mr-1" />
            <span>Proven AI mentions</span>
          </div>
        </div>

        {/* Card 3: AI Mentions Gained */}
        <div className="bg-white p-5 rounded-xl border border-slate-200 shadow-sm flex flex-col justify-between">
          <div>
            <div className="flex items-center text-xs font-semibold uppercase tracking-wider text-slate-400 mb-2">
              <ArrowUpRight className="w-4 h-4 mr-1.5 text-indigo-600" /> AI Mentions Gained
            </div>
            <div className="text-3xl font-bold text-slate-900">
              {overview?.ai_mentions ?? 0}
            </div>
          </div>
          <div className="text-xs text-slate-500 mt-3 pt-2 border-t border-slate-100 flex items-center justify-between">
            <span>Last {days} days total</span>
            <span className="text-indigo-600 font-medium">All engines</span>
          </div>
        </div>

        {/* Card 4: Citation Share */}
        <div className="bg-white p-5 rounded-xl border border-slate-200 shadow-sm flex flex-col justify-between">
          <div>
            <div className="flex items-center text-xs font-semibold uppercase tracking-wider text-slate-400 mb-2">
              <ShieldCheck className="w-4 h-4 mr-1.5 text-purple-600" /> Citation Share
            </div>
            <div className="text-3xl font-bold text-slate-900">
              {(overview?.citation_share_pct ?? 0).toFixed(1)}%
            </div>
          </div>
          <div className="text-xs text-slate-500 mt-3 pt-2 border-t border-slate-100">
            <span>vs Tracked Competitors</span>
          </div>
        </div>

        {/* Card 5: Estimated Referral Value */}
        <div className="bg-emerald-50/70 p-5 rounded-xl border border-emerald-200/80 shadow-sm flex flex-col justify-between">
          <div>
            <div className="flex items-center text-xs font-semibold uppercase tracking-wider text-emerald-700 mb-2">
              <DollarSign className="w-4 h-4 mr-1 text-emerald-700" /> Est. Organic Value
            </div>
            <div className="text-3xl font-bold text-emerald-950">
              ${(overview?.estimated_referral_value ?? 0).toLocaleString("en-US", { minimumFractionDigits: 0, maximumFractionDigits: 0 })}
            </div>
          </div>
          <div className="text-xs text-emerald-700 font-medium mt-3 pt-2 border-t border-emerald-200/60 flex items-center">
            <TrendingUp className="w-3.5 h-3.5 mr-1" />
            <span>AI Citation Referral Est.</span>
          </div>
        </div>
      </div>

      {/* Main Charts Section */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Mentions Time-Series Area Chart (2 cols) */}
        <div className="lg:col-span-2 bg-white border border-slate-200 rounded-xl shadow-sm p-6">
          <div className="flex items-center justify-between mb-6">
            <div>
              <h2 className="text-base font-semibold text-slate-900">Brand vs Competitor AI Mentions</h2>
              <p className="text-xs text-slate-500 mt-0.5">
                Daily frequency of brand mentions vs aggregate competitor citations
              </p>
            </div>
            <div className="flex items-center gap-3 text-xs">
              <span className="flex items-center gap-1.5">
                <span className="w-3 h-3 rounded-sm bg-blue-600 inline-block" /> Brand Mentions
              </span>
              <span className="flex items-center gap-1.5">
                <span className="w-3 h-3 rounded-sm bg-slate-300 inline-block" /> Competitors
              </span>
            </div>
          </div>

          <div className="h-72 w-full">
            {mounted && timeseries.length > 0 ? (
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={timeseries} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                  <defs>
                    <linearGradient id="colorBrand" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#2563eb" stopOpacity={0.25} />
                      <stop offset="95%" stopColor="#2563eb" stopOpacity={0} />
                    </linearGradient>
                    <linearGradient id="colorCompetitor" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#94a3b8" stopOpacity={0.2} />
                      <stop offset="95%" stopColor="#94a3b8" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#f1f5f9" />
                  <XAxis
                    dataKey="day"
                    tick={{ fontSize: 11, fill: "#94a3b8" }}
                    tickFormatter={(val) => val.slice(5)}
                  />
                  <YAxis tick={{ fontSize: 11, fill: "#94a3b8" }} allowDecimals={false} />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: "#0f172a",
                      borderColor: "#1e293b",
                      borderRadius: "8px",
                      color: "#fff",
                      fontSize: "12px",
                    }}
                    labelStyle={{ color: "#94a3b8", marginBottom: "4px" }}
                  />
                  <Area
                    type="monotone"
                    dataKey="brand_mentions"
                    name="Brand Mentions"
                    stroke="#2563eb"
                    strokeWidth={2}
                    fillOpacity={1}
                    fill="url(#colorBrand)"
                  />
                  <Area
                    type="monotone"
                    dataKey="competitor_mentions"
                    name="Competitor Mentions"
                    stroke="#94a3b8"
                    strokeWidth={1.5}
                    strokeDasharray="4 2"
                    fillOpacity={1}
                    fill="url(#colorCompetitor)"
                  />
                </AreaChart>
              </ResponsiveContainer>
            ) : (
              <div className="h-full flex flex-col items-center justify-center text-slate-400 text-sm">
                <Sparkles className="w-8 h-8 text-slate-300 mb-2" />
                <p>Telemetry collection active. Daily trends will populate here.</p>
              </div>
            )}
          </div>
        </div>

        {/* Citation Share Trend Line Chart (1 col) */}
        <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-6">
          <div className="mb-6">
            <h2 className="text-base font-semibold text-slate-900">Citation Share Trend</h2>
            <p className="text-xs text-slate-500 mt-0.5">
              Proportion of total citations won by brand
            </p>
          </div>

          <div className="h-72 w-full">
            {mounted && timeseries.length > 0 ? (
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={timeseries} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#f1f5f9" />
                  <XAxis
                    dataKey="day"
                    tick={{ fontSize: 11, fill: "#94a3b8" }}
                    tickFormatter={(val) => val.slice(5)}
                  />
                  <YAxis
                    tick={{ fontSize: 11, fill: "#94a3b8" }}
                    unit="%"
                    domain={[0, 100]}
                  />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: "#0f172a",
                      borderColor: "#1e293b",
                      borderRadius: "8px",
                      color: "#fff",
                      fontSize: "12px",
                    }}
                    formatter={(val: any) => [`${Number(val).toFixed(1)}%`, "Citation Share"]}
                    labelStyle={{ color: "#94a3b8" }}
                  />
                  <Line
                    type="monotone"
                    dataKey="citation_share"
                    name="Citation Share"
                    stroke="#10b981"
                    strokeWidth={2.5}
                    dot={{ r: 2.5, fill: "#10b981" }}
                    activeDot={{ r: 5 }}
                  />
                </LineChart>
              </ResponsiveContainer>
            ) : (
              <div className="h-full flex flex-col items-center justify-center text-slate-400 text-sm">
                <Award className="w-8 h-8 text-slate-300 mb-2" />
                <p>Citation share trends will appear here.</p>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Engine Share Breakdown Cards */}
      <div className="space-y-4">
        <div>
          <h2 className="text-lg font-semibold text-slate-900">Generative Engine Breakdown</h2>
          <p className="text-xs text-slate-500">
            Attribution across monitored frontier engines over the last {days} days
          </p>
        </div>

        {engineShare.length === 0 ? (
          <div className="p-8 bg-white border border-slate-200 rounded-xl text-center text-slate-400 text-sm">
            No engine telemetry logged for the selected period.
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
            {engineShare.map((e) => (
              <div key={e.engine} className="bg-white border border-slate-200 rounded-xl p-5 shadow-sm space-y-4">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Cpu className="w-4 h-4 text-blue-600" />
                    <span className="font-semibold text-sm text-slate-900 capitalize">
                      {e.engine.replace("_", " ")}
                    </span>
                  </div>
                  <span className="text-xs px-2 py-0.5 rounded-full bg-slate-100 text-slate-600 font-medium">
                    {e.prompts_visible} / {e.prompts_tracked} prompts
                  </span>
                </div>

                <div className="space-y-2">
                  <div>
                    <div className="flex justify-between text-xs text-slate-600 mb-1">
                      <span>Mention Rate</span>
                      <span className="font-semibold text-slate-900">{e.mention_rate.toFixed(1)}%</span>
                    </div>
                    <div className="w-full bg-slate-100 rounded-full h-1.5 overflow-hidden">
                      <div
                        className="bg-blue-600 h-1.5 rounded-full"
                        style={{ width: `${Math.min(100, Math.max(0, e.mention_rate))}%` }}
                      />
                    </div>
                  </div>

                  <div>
                    <div className="flex justify-between text-xs text-slate-600 mb-1">
                      <span>Citation Share</span>
                      <span className="font-semibold text-slate-900">{e.citation_share.toFixed(1)}%</span>
                    </div>
                    <div className="w-full bg-slate-100 rounded-full h-1.5 overflow-hidden">
                      <div
                        className="bg-emerald-500 h-1.5 rounded-full"
                        style={{ width: `${Math.min(100, Math.max(0, e.citation_share))}%` }}
                      />
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Won Gaps Proof Table */}
      <div className="bg-white border border-slate-200 rounded-xl shadow-sm overflow-hidden">
        <div className="px-6 py-4 border-b border-slate-200 bg-slate-50 flex items-center justify-between">
          <div>
            <h3 className="font-semibold text-slate-900">Verified Closed Gaps & AI Citations Won</h3>
            <p className="text-xs text-slate-500 mt-0.5">
              Gaps transitioned to won status after verifying live citations in AI engine responses.
            </p>
          </div>
          <span className="text-xs font-semibold px-2.5 py-1 rounded-full bg-emerald-100 text-emerald-800">
            {wonGaps.length} Won Gaps
          </span>
        </div>

        {wonGaps.length === 0 ? (
          <div className="p-12 text-center text-slate-400">
            <Target className="w-8 h-8 text-slate-300 mx-auto mb-2" />
            <p className="text-sm font-medium text-slate-600">No won gaps found in this period</p>
            <p className="text-xs text-slate-400 mt-1 max-w-sm mx-auto">
              When content published through the pipeline is cited by AI models, gaps transition to closed/won status and show here with full proof citations.
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="bg-slate-50/50 border-b border-slate-100 text-slate-500 text-xs uppercase tracking-wider">
                <tr>
                  <th className="px-6 py-3 font-medium">Prompt</th>
                  <th className="px-6 py-3 font-medium">Gap Type</th>
                  <th className="px-6 py-3 font-medium">Closed At</th>
                  <th className="px-6 py-3 font-medium">Published Target</th>
                  <th className="px-6 py-3 font-medium">Proof Evidence</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {wonGaps.map((gap) => (
                  <tr key={gap.id} className="hover:bg-slate-50/60 transition-colors">
                    <td className="px-6 py-4 font-medium text-slate-900 max-w-xs truncate">
                      {gap.prompt_text || "Prompt"}
                    </td>
                    <td className="px-6 py-4">
                      <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-slate-100 text-slate-700">
                        {gap.gap_type.replace("_", " ")}
                      </span>
                    </td>
                    <td className="px-6 py-4 text-slate-500 text-xs">
                      {gap.closed_at ? formatDateTime(gap.closed_at) : "Recent"}
                    </td>
                    <td className="px-6 py-4 text-xs">
                      {gap.published_url ? (
                        <a
                          href={gap.published_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-blue-600 hover:underline inline-flex items-center gap-1 font-mono"
                        >
                          {gap.published_url.length > 30
                            ? gap.published_url.slice(0, 30) + "…"
                            : gap.published_url}
                          <ExternalLink className="w-3 h-3" />
                        </a>
                      ) : (
                        <span className="text-slate-400">Content Pipeline</span>
                      )}
                    </td>
                    <td className="px-6 py-4">
                      {gap.proof_citations && gap.proof_citations.length > 0 ? (
                        <div className="flex flex-wrap gap-1.5">
                          {gap.proof_citations.slice(0, 3).map((proof: any, idx: number) => (
                            <span
                              key={idx}
                              className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-emerald-50 text-emerald-700 border border-emerald-200"
                            >
                              <ShieldCheck className="w-3 h-3 text-emerald-600" />
                              {proof.engine || "AI"} {proof.rank ? `#${proof.rank}` : "Cited"}
                            </span>
                          ))}
                        </div>
                      ) : (
                        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-emerald-50 text-emerald-700 border border-emerald-200">
                          <ShieldCheck className="w-3 h-3 text-emerald-600" /> Won Mention
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Google Search Console & Generative AI Referrals Engine */}
      <div className="bg-white rounded-2xl border border-slate-200/80 shadow-xs p-6 md:p-8 space-y-6">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-slate-100 pb-5">
          <div>
            <div className="flex items-center gap-2">
              <div className="w-8 h-8 rounded-lg bg-blue-50 border border-blue-200 flex items-center justify-center text-blue-600">
                <Search className="w-4 h-4" />
              </div>
              <h3 className="font-bold text-slate-900 text-lg">
                Google Search &amp; Generative AI Referrals
              </h3>
            </div>
            <p className="text-xs text-slate-500 mt-1 max-w-2xl">
              Live measurement of organic Google search visibility, AI Overviews impressions, and visitors attributed to conversational AI engines.
            </p>
          </div>
          <div className="flex items-center gap-3">
            <button
              onClick={handleSyncSearch}
              disabled={syncingSearch}
              className="inline-flex items-center gap-2 px-3.5 py-1.5 text-xs font-semibold text-white bg-slate-900 hover:bg-slate-800 disabled:opacity-50 rounded-lg shadow-xs transition-colors"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${syncingSearch ? "animate-spin" : ""}`} />
              {syncingSearch ? "Syncing..." : "Sync Search Data"}
            </button>
          </div>
        </div>

        {syncSuccessMsg && (
          <div className="p-3 bg-emerald-50 border border-emerald-200 rounded-xl text-xs text-emerald-800 flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4 text-emerald-600 shrink-0" />
            <span>{syncSuccessMsg}</span>
          </div>
        )}

        {/* Search Performance KPI Grid */}
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
          <div className="p-4 rounded-xl bg-slate-50/70 border border-slate-200/60">
            <span className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider">Organic Clicks</span>
            <div className="text-2xl font-black text-slate-900 mt-1">
              {searchSummary ? searchSummary.total_clicks.toLocaleString() : "—"}
            </div>
            <span className="text-[11px] text-slate-400">Google Search Console</span>
          </div>

          <div className="p-4 rounded-xl bg-slate-50/70 border border-slate-200/60">
            <span className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider">Impressions</span>
            <div className="text-2xl font-black text-slate-900 mt-1">
              {searchSummary ? searchSummary.total_impressions.toLocaleString() : "—"}
            </div>
            <span className="text-[11px] text-slate-400">Avg Pos {searchSummary ? searchSummary.average_position : "—"}</span>
          </div>

          <div className="p-4 rounded-xl bg-blue-50/50 border border-blue-200/60">
            <span className="text-[11px] font-semibold text-blue-700 uppercase tracking-wider">AI Overviews</span>
            <div className="text-2xl font-black text-blue-900 mt-1">
              {searchSummary ? searchSummary.total_aio_impressions.toLocaleString() : "—"}
            </div>
            <span className="text-[11px] text-blue-600 font-medium">AIO Search Queries</span>
          </div>

          <div className="p-4 rounded-xl bg-purple-50/50 border border-purple-200/60">
            <span className="text-[11px] font-semibold text-purple-700 uppercase tracking-wider">AI Referrals</span>
            <div className="text-2xl font-black text-purple-900 mt-1">
              {searchSummary ? searchSummary.total_ai_sessions.toLocaleString() : "—"}
            </div>
            <span className="text-[11px] text-purple-600 font-medium">{searchSummary ? `${searchSummary.ai_session_share_pct}%` : "—"} of total traffic</span>
          </div>

          <div className="p-4 rounded-xl bg-slate-50/70 border border-slate-200/60">
            <span className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider">Engaged AI Sessions</span>
            <div className="text-2xl font-black text-slate-900 mt-1">
              {searchSummary ? searchSummary.ai_engaged_sessions.toLocaleString() : "—"}
            </div>
            <span className="text-[11px] text-slate-400">{searchSummary ? `${searchSummary.ai_conversions} conversions` : "—"}</span>
          </div>

          <div className="p-4 rounded-xl bg-emerald-50/50 border border-emerald-200/60">
            <span className="text-[11px] font-semibold text-emerald-700 uppercase tracking-wider">Estimated Value</span>
            <div className="text-2xl font-black text-emerald-900 mt-1">
              ${searchSummary ? searchSummary.estimated_referral_value_usd.toLocaleString() : "0"}
            </div>
            <span className="text-[11px] text-emerald-600 font-medium">Attributed Pipeline</span>
          </div>
        </div>

        {/* Disclaimer Caveat Banner */}
        <div className="flex items-start gap-2.5 p-3.5 bg-amber-50/80 border border-amber-200/70 rounded-xl text-xs text-amber-900">
          <Info className="w-4 h-4 text-amber-700 shrink-0 mt-0.5" />
          <p className="leading-relaxed">
            <strong className="font-semibold">Attribution Undercount Caveat:</strong> {searchSummary?.attribution_disclaimer || "AI referrals typically undercount due to in-app webviews and referrer stripping."}
          </p>
        </div>

        {/* Timeseries Dual Chart */}
        <div className="bg-slate-50/60 border border-slate-200/70 rounded-xl p-5">
          <h4 className="text-sm font-bold text-slate-900 mb-4">
            Organic Search Clicks vs. AI Referral Visits
          </h4>
          <div className="h-64 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={searchTimeseries} margin={{ top: 10, right: 30, left: 0, bottom: 0 }}>
                <defs>
                  <linearGradient id="clicksGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.4} />
                    <stop offset="95%" stopColor="#3b82f6" stopOpacity={0} />
                  </linearGradient>
                  <linearGradient id="aiGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#8b5cf6" stopOpacity={0.4} />
                    <stop offset="95%" stopColor="#8b5cf6" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis dataKey="day" stroke="#94a3b8" fontSize={11} tickFormatter={(val) => val.slice(5)} />
                <YAxis stroke="#94a3b8" fontSize={11} />
                <Tooltip
                  contentStyle={{ backgroundColor: "#0f172a", borderRadius: "8px", border: "none", color: "#fff", fontSize: "12px" }}
                />
                <Legend />
                <Area type="monotone" dataKey="clicks" name="GSC Organic Clicks" stroke="#3b82f6" fillOpacity={1} fill="url(#clicksGrad)" />
                <Area type="monotone" dataKey="ai_sessions" name="GA4 AI Referral Visits" stroke="#8b5cf6" fillOpacity={1} fill="url(#aiGrad)" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Bottom Split: AI Referral Engines & Top Organic Queries */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* AI Engines Split */}
          <div className="border border-slate-200/70 rounded-xl p-5">
            <h4 className="text-sm font-bold text-slate-900 mb-3 flex items-center gap-2">
              <Share2 className="w-4 h-4 text-purple-600" />
              Generative AI Referral Breakdown
            </h4>
            {aiReferrals.length === 0 ? (
              <p className="text-xs text-slate-400 py-6 text-center">No AI referrers logged in this period.</p>
            ) : (
              <div className="space-y-3">
                {aiReferrals.map((ref, idx) => (
                  <div key={idx} className="flex items-center justify-between p-3 rounded-lg bg-slate-50/70 border border-slate-200/40 text-xs">
                    <div>
                      <span className="font-semibold text-slate-900 capitalize">{ref.engine}</span>
                      <span className="text-slate-400 ml-1.5 font-mono">({ref.source})</span>
                    </div>
                    <div className="flex items-center gap-4">
                      <span className="text-slate-600 font-medium">{ref.sessions} sessions</span>
                      <span className="px-2 py-0.5 rounded-full font-bold bg-purple-100 text-purple-800">
                        {ref.share_of_ai_pct}%
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Top Organic Queries */}
          <div className="border border-slate-200/70 rounded-xl p-5">
            <h4 className="text-sm font-bold text-slate-900 mb-3 flex items-center gap-2">
              <Compass className="w-4 h-4 text-blue-600" />
              Search Queries &amp; AI Prompt Alignment
            </h4>
            {searchQueries.length === 0 ? (
              <p className="text-xs text-slate-400 py-6 text-center">No search queries synchronized yet.</p>
            ) : (
              <div className="space-y-2 max-h-72 overflow-y-auto pr-1">
                {searchQueries.map((q, idx) => (
                  <div key={idx} className="flex items-center justify-between p-2.5 rounded-lg bg-slate-50/70 border border-slate-200/40 text-xs">
                    <div className="flex items-center gap-2 max-w-xs truncate">
                      <span className="font-medium text-slate-900 truncate">{q.query}</span>
                      {q.is_tracked_prompt && (
                        <span className="px-1.5 py-0.5 bg-emerald-100 text-emerald-800 font-semibold rounded text-[10px] shrink-0">
                          Tracked Prompt
                        </span>
                      )}
                    </div>
                    <div className="flex items-center gap-3 shrink-0 text-slate-500 font-mono">
                      <span>{q.clicks} clicks</span>
                      <span>Pos #{q.position}</span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
