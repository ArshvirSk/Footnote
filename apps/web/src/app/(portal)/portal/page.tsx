"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ArrowRight, CheckCircle2, Clock, Eye, FileDown, FileText, Loader2, MessageSquare, Quote, Search, ShieldAlert, Sparkles } from "lucide-react";
import { PortalDashboard, portalApi, reportsApi, searchAnalyticsApi, getSelectedClientId, type SearchSummary } from "@/lib/api";

export default function PortalOverview() {
  const [dashboard, setDashboard] = useState<PortalDashboard | null>(null);
  const [searchSummary, setSearchSummary] = useState<SearchSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);

  useEffect(() => {
    const cid = getSelectedClientId() || undefined;
    Promise.all([
      portalApi.getDashboard(cid),
      cid ? searchAnalyticsApi.getSummary(cid, 30).catch(() => null) : Promise.resolve(null),
    ])
      .then(([data, search]) => {
        setDashboard(data);
        setSearchSummary(search);
      })
      .catch((err) => setError(err.message || "Failed to load dashboard"))
      .finally(() => setLoading(false));
  }, []);

  const handleExportReport = async () => {
    if (!dashboard) return;
    try {
      setExporting(true);
      const rep = await reportsApi.generate(dashboard.client_id, {
        title: `Executive Visibility Dossier — ${dashboard.client_name}`,
        report_type: "visibility_audit",
      });
      window.open(reportsApi.exportUrl(rep.id, "html"), "_blank");
    } catch (err: any) {
      alert(err?.message || "Failed to generate executive report");
    } finally {
      setExporting(false);
    }
  };

  if (loading) {
    return (
      <div className="h-96 flex flex-col items-center justify-center text-slate-400 gap-3">
        <Loader2 className="w-8 h-8 animate-spin text-slate-700" />
        <span className="text-sm font-medium">Loading live client dashboard...</span>
      </div>
    );
  }

  if (error || !dashboard) {
    return (
      <div className="bg-rose-50 border border-rose-200 text-rose-800 p-6 rounded-2xl text-sm max-w-xl mx-auto my-12">
        <div className="flex items-center gap-2 font-bold mb-1">
          <ShieldAlert className="w-5 h-5 text-rose-600" />
          <span>Dashboard Access Error</span>
        </div>
        <p>{error || "Unable to retrieve dashboard for this brand"}</p>
      </div>
    );
  }

  return (
    <div className="space-y-8 animate-in fade-in duration-500">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <span className="text-xs font-bold uppercase tracking-wider text-slate-400">
              {dashboard.primary_domain}
            </span>
            <span className="w-1 h-1 bg-slate-300 rounded-full" />
            <span className="text-xs text-emerald-600 font-semibold flex items-center gap-1">
              <CheckCircle2 className="w-3 h-3" /> Live Telemetry
            </span>
          </div>
          <h1 className="text-3xl font-bold tracking-tight text-slate-900">
            {dashboard.client_name} Overview
          </h1>
          <p className="text-sm text-slate-500 mt-1">
            Verified presence, brand citations, and live quotes across frontier AI answer engines.
          </p>
        </div>

        <button
          onClick={handleExportReport}
          disabled={exporting}
          className="inline-flex items-center px-4 py-2 bg-slate-900 hover:bg-slate-800 text-white rounded-xl text-xs font-semibold shadow-2xs transition disabled:opacity-50 self-start sm:self-auto"
        >
          {exporting ? (
            <Loader2 className="w-3.5 h-3.5 animate-spin mr-1.5" />
          ) : (
            <FileDown className="w-3.5 h-3.5 mr-1.5" />
          )}
          Export Executive Dossier
        </button>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5">
        <div className="bg-white p-6 rounded-2xl border border-slate-200 shadow-2xs flex flex-col justify-between">
          <div className="flex items-center justify-between text-xs font-semibold text-slate-500 mb-3">
            <span>Total Visibility</span>
            <Eye className="w-4 h-4 text-slate-400" />
          </div>
          <div className="text-4xl font-extrabold text-slate-900 tracking-tight">
            {dashboard.visibility_pct}%
          </div>
          <div className="text-xs text-slate-500 font-medium mt-3">
            30-day average mention rate
          </div>
        </div>

        <div className="bg-white p-6 rounded-2xl border border-slate-200 shadow-2xs flex flex-col justify-between">
          <div className="flex items-center justify-between text-xs font-semibold text-slate-500 mb-3">
            <span>Citation Share</span>
            <Sparkles className="w-4 h-4 text-slate-400" />
          </div>
          <div className="text-4xl font-extrabold text-slate-900 tracking-tight">
            {dashboard.citation_share_pct}%
          </div>
          <div className="text-xs text-slate-500 font-medium mt-3">
            Answer citation share vs competitors
          </div>
        </div>

        <div className="bg-white p-6 rounded-2xl border border-slate-200 shadow-2xs flex flex-col justify-between">
          <div className="flex items-center justify-between text-xs font-semibold text-slate-500 mb-3">
            <span>Content Shipped</span>
            <FileText className="w-4 h-4 text-slate-400" />
          </div>
          <div className="text-4xl font-extrabold text-slate-900 tracking-tight">
            {dashboard.content_shipped}
          </div>
          <div className="text-xs text-slate-500 font-medium mt-3">
            Approved articles &amp; landing pages
          </div>
        </div>

        <div className={`p-6 rounded-2xl border shadow-2xs flex flex-col justify-between ${
          dashboard.pending_actions > 0
            ? "bg-amber-50/70 border-amber-200"
            : "bg-white border-slate-200"
        }`}>
          <div className="flex items-center justify-between text-xs font-semibold mb-3">
            <span className={dashboard.pending_actions > 0 ? "text-amber-900" : "text-slate-500"}>
              Action Required
            </span>
            <MessageSquare className={`w-4 h-4 ${dashboard.pending_actions > 0 ? "text-amber-600" : "text-slate-400"}`} />
          </div>
          <div className={`text-4xl font-extrabold tracking-tight ${
            dashboard.pending_actions > 0 ? "text-amber-900" : "text-slate-900"
          }`}>
            {dashboard.pending_actions}
          </div>
          <Link
            href="/portal/approvals"
            className={`text-xs font-semibold mt-3 flex items-center gap-1 hover:underline ${
              dashboard.pending_actions > 0 ? "text-amber-800" : "text-slate-500"
            }`}
          >
            {dashboard.pending_actions > 0 ? "Review pending drafts" : "View approvals queue"} <ArrowRight className="w-3.5 h-3.5" />
          </Link>
        </div>
      </div>

      {/* Search & Generative AI Impact */}
      {searchSummary && (
        <div className="bg-white rounded-2xl border border-slate-200/80 shadow-2xs p-6 md:p-8">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-6">
            <div>
              <h3 className="text-lg font-bold text-slate-900 flex items-center gap-2">
                <Search className="w-5 h-5 text-blue-600" />
                Organic Search Performance &amp; AI Referral Traffic
              </h3>
              <p className="text-xs text-slate-500 mt-0.5">
                Google Search Console organic performance and verified visitors arriving from generative AI engines.
              </p>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-xs font-semibold px-2.5 py-1 rounded-full bg-blue-50 text-blue-700 border border-blue-200">
                Last 30 Days
              </span>
            </div>
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
            <div className="p-4 rounded-xl bg-slate-50/70 border border-slate-200/60">
              <span className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider">Organic Clicks</span>
              <div className="text-2xl font-black text-slate-900 mt-1">
                {searchSummary.total_clicks.toLocaleString()}
              </div>
              <span className="text-[11px] text-slate-400">Google Search</span>
            </div>
            <div className="p-4 rounded-xl bg-slate-50/70 border border-slate-200/60">
              <span className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider">Search Impressions</span>
              <div className="text-2xl font-black text-slate-900 mt-1">
                {searchSummary.total_impressions.toLocaleString()}
              </div>
              <span className="text-[11px] text-slate-400">Avg Pos #{searchSummary.average_position}</span>
            </div>
            <div className="p-4 rounded-xl bg-purple-50/60 border border-purple-200/60">
              <span className="text-[11px] font-semibold text-purple-700 uppercase tracking-wider">AI Referrals</span>
              <div className="text-2xl font-black text-purple-900 mt-1">
                {searchSummary.total_ai_sessions.toLocaleString()}
              </div>
              <span className="text-[11px] text-purple-600 font-medium">{searchSummary.ai_session_share_pct}% of total traffic</span>
            </div>
            <div className="p-4 rounded-xl bg-emerald-50/60 border border-emerald-200/60">
              <span className="text-[11px] font-semibold text-emerald-700 uppercase tracking-wider">Attributed Value</span>
              <div className="text-2xl font-black text-emerald-900 mt-1">
                ${searchSummary.estimated_referral_value_usd.toLocaleString()}
              </div>
              <span className="text-[11px] text-emerald-600 font-medium">Estimated Pipeline</span>
            </div>
          </div>
          <p className="text-[11px] text-slate-400 italic mt-3">
            * Note: Conversational AI referrers typically undercount due to private in-app webviews and cross-origin header stripping.
          </p>
        </div>
      )}

      {/* Recent Engine Mentions */}
      <div className="bg-white rounded-2xl border border-slate-200 shadow-2xs p-6 md:p-8">
        <div className="flex items-center justify-between mb-6">
          <div>
            <h3 className="text-lg font-bold text-slate-900 flex items-center gap-2">
              <Quote className="w-5 h-5 text-slate-400" />
              Recent AI Engine Mentions &amp; Quotes
            </h3>
            <p className="text-xs text-slate-500 mt-0.5">
              Real responses observed when users ask LLMs industry-related prompts.
            </p>
          </div>
        </div>

        {dashboard.recent_mentions.length === 0 ? (
          <div className="p-10 text-center border border-dashed border-slate-200 rounded-xl">
            <Sparkles className="w-8 h-8 text-slate-300 mx-auto mb-2" />
            <h4 className="text-sm font-semibold text-slate-700">No Mentions Recorded Yet</h4>
            <p className="text-xs text-slate-400 max-w-sm mx-auto mt-1">
              As regular collection batches run for {dashboard.client_name}, engine citations and quotes will automatically appear here.
            </p>
          </div>
        ) : (
          <div className="space-y-4">
            {dashboard.recent_mentions.map((mention, idx) => (
              <div
                key={idx}
                className="p-5 border border-slate-200 rounded-xl bg-slate-50/60 hover:bg-slate-50 transition"
              >
                <div className="flex items-center justify-between gap-4 mb-2">
                  <span className="font-semibold text-xs text-slate-900">
                    &ldquo;{mention.query_text}&rdquo;
                  </span>
                  <div className="flex items-center gap-2 flex-shrink-0">
                    <span className="text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded bg-white border border-slate-200 text-slate-700">
                      {mention.engine}
                    </span>
                    {mention.collected_at && (
                      <span className="text-[11px] text-slate-400 flex items-center">
                        <Clock className="w-3 h-3 mr-1" />
                        {new Date(mention.collected_at).toLocaleDateString()}
                      </span>
                    )}
                  </div>
                </div>
                <p className="text-slate-600 text-xs leading-relaxed italic bg-white p-3.5 rounded-lg border border-slate-200/60">
                  &ldquo;{mention.snippet}&rdquo;
                </p>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
