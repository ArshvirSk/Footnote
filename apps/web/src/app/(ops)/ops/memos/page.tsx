"use client";

import { useCallback, useEffect, useState } from "react";
import {
  FileText,
  Sparkles,
  CheckCircle2,
  AlertCircle,
  Calendar,
  Send,
  Download,
  Copy,
  Check,
  RefreshCw,
  Eye,
  ExternalLink,
  ChevronRight,
  TrendingUp,
  Target,
  Award,
  X,
  Clock,
  ThumbsUp,
  RotateCcw,
} from "lucide-react";
import {
  CLIENT_CHANGED_EVENT,
  getSelectedClientId,
  memosApi,
  websites,
  type MemoRecord,
  type ClientSummary,
} from "@/lib/api";
import { formatDateTime } from "@/lib/ui";

export default function MemosPage() {
  const [clientId, setClientId] = useState<string | null>(null);
  const [client, setClient] = useState<ClientSummary | null>(null);
  const [memos, setMemos] = useState<MemoRecord[]>([]);
  const [selectedMemo, setSelectedMemo] = useState<MemoRecord | null>(null);
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  // Review feedback modal state
  const [showFeedbackModal, setShowFeedbackModal] = useState(false);
  const [feedbackDecision, setFeedbackDecision] = useState<"revise" | "rejected">("revise");
  const [feedbackText, setFeedbackText] = useState("");

  const loadMemos = useCallback(
    async (cid: string) => {
      try {
        setLoading(true);
        setError(null);
        const data = await memosApi.listMemos(cid, statusFilter || undefined);
        setMemos(data);
        if (data.length > 0) {
          // Keep current selection or default to first
          const current = selectedMemo ? data.find((m) => m.id === selectedMemo.id) : null;
          setSelectedMemo(current || data[0]);
        } else {
          setSelectedMemo(null);
        }
      } catch (err: any) {
        setError(err?.message || "Failed to load executive memos");
      } finally {
        setLoading(false);
      }
    },
    [statusFilter, selectedMemo]
  );

  const initClient = useCallback(async () => {
    try {
      const list = await websites.list(true);
      const stored = getSelectedClientId();
      const resolvedId =
        stored && list.some((c) => c.id === stored)
          ? stored
          : list[0]?.id;

      if (!resolvedId) {
        setError("Please register a website first.");
        setLoading(false);
        return;
      }

      setClientId(resolvedId);
      setClient(list.find((c) => c.id === resolvedId) || null);
      await loadMemos(resolvedId);
    } catch (err: any) {
      setError(err?.message || "Failed to resolve website");
      setLoading(false);
    }
  }, [loadMemos]);

  useEffect(() => {
    void initClient();

    const handleClientChange = () => {
      const stored = getSelectedClientId();
      if (stored && stored !== clientId) {
        setClientId(stored);
        setSelectedMemo(null);
        void loadMemos(stored);
      }
    };

    window.addEventListener(CLIENT_CHANGED_EVENT, handleClientChange);
    return () => window.removeEventListener(CLIENT_CHANGED_EVENT, handleClientChange);
  }, [initClient, clientId, loadMemos]);

  const handleGenerateMemo = async () => {
    if (!clientId) return;
    try {
      setGenerating(true);
      setError(null);
      const res = await memosApi.generateMemo(clientId, 30);
      setNotice(`Executive 30-Day Memo generated successfully! ("${res.title}")`);
      const updated = await memosApi.listMemos(clientId);
      setMemos(updated);
      const newlyCreated = updated.find((m) => m.id === res.memo_id);
      if (newlyCreated) setSelectedMemo(newlyCreated);
    } catch (err: any) {
      setError(err?.message || "Failed to generate memo");
    } finally {
      setGenerating(false);
    }
  };

  const handleApproveMemo = async (memoId: string) => {
    if (!clientId) return;
    try {
      setActionLoading("approve");
      setError(null);
      await memosApi.decideMemo(clientId, memoId, "approved");
      setNotice("Executive memo approved!");
      const refreshed = await memosApi.getMemo(clientId, memoId);
      setSelectedMemo(refreshed);
      await loadMemos(clientId);
    } catch (err: any) {
      setError(err?.message || "Approval failed");
    } finally {
      setActionLoading(null);
    }
  };

  const handleSubmitFeedback = async () => {
    if (!clientId || !selectedMemo) return;
    try {
      setActionLoading("feedback");
      setError(null);
      await memosApi.decideMemo(clientId, selectedMemo.id, feedbackDecision, feedbackText);
      setNotice(
        feedbackDecision === "revise"
          ? "Revision requested on memo."
          : "Memo rejected."
      );
      setShowFeedbackModal(false);
      setFeedbackText("");
      const refreshed = await memosApi.getMemo(clientId, selectedMemo.id);
      setSelectedMemo(refreshed);
      await loadMemos(clientId);
    } catch (err: any) {
      setError(err?.message || "Action failed");
    } finally {
      setActionLoading(null);
    }
  };

  const handlePublishMemo = async (memoId: string) => {
    if (!clientId) return;
    try {
      setActionLoading("publish");
      setError(null);
      const res = await memosApi.publishMemo(clientId, memoId);
      setNotice(`Memo published to client portal! (${res.published_url})`);
      const refreshed = await memosApi.getMemo(clientId, memoId);
      setSelectedMemo(refreshed);
      await loadMemos(clientId);
    } catch (err: any) {
      setError(err?.message || "Publish failed");
    } finally {
      setActionLoading(null);
    }
  };

  const handleExportMarkdown = async (memoId: string) => {
    if (!clientId) return;
    try {
      const exported = await memosApi.exportMemo(clientId, memoId);
      const blob = new Blob([exported.markdown], { type: "text/markdown;charset=utf-8;" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.setAttribute("download", `${exported.title.replace(/\s+/g, "_")}.md`);
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
    } catch (err: any) {
      setError(err?.message || "Export failed");
    }
  };

  const handleCopyMarkdown = (body: string) => {
    navigator.clipboard.writeText(body);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const metrics = selectedMemo?.metrics_summary_json;

  return (
    <div className="space-y-6">
      {/* Top Title & Generator */}
      <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-3xl font-semibold tracking-tight text-slate-900">
              Executive Monthly Memos
            </h1>
            {client && (
              <span className="px-2.5 py-0.5 rounded-full text-xs font-medium bg-blue-50 text-blue-700 border border-blue-200">
                {client.name}
              </span>
            )}
          </div>
          <p className="text-slate-600 mt-1 text-sm">
            Automated 30-day KPI rollups, strategic executive summaries, and gated client portal reports.
          </p>
        </div>

        <button
          onClick={handleGenerateMemo}
          disabled={generating}
          className="flex items-center justify-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-sm font-medium transition shadow-sm disabled:opacity-50"
        >
          <Sparkles className="w-4 h-4" />
          <span>{generating ? "Synthesizing 30-Day Memo…" : "Generate New 30-Day Memo"}</span>
        </button>
      </div>

      {notice && (
        <div className="flex items-center justify-between p-4 bg-emerald-50 border border-emerald-200 rounded-xl text-emerald-800 text-sm">
          <div className="flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4 text-emerald-600 flex-shrink-0" />
            <span>{notice}</span>
          </div>
          <button onClick={() => setNotice(null)} className="text-emerald-600 hover:text-emerald-800">
            <X className="w-4 h-4" />
          </button>
        </div>
      )}

      {error && (
        <div className="flex items-center justify-between p-4 bg-rose-50 border border-rose-200 rounded-xl text-rose-700 text-sm">
          <div className="flex items-center gap-2">
            <AlertCircle className="w-4 h-4 flex-shrink-0" />
            <span>{error}</span>
          </div>
          <button onClick={() => setError(null)} className="text-rose-600 hover:text-rose-800">
            <X className="w-4 h-4" />
          </button>
        </div>
      )}

      {/* Main 2-Column Layout: Sidebar of Memos + Memo Reader */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
        {/* Left Column: Memos List (4 cols) */}
        <div className="lg:col-span-4 space-y-4">
          <div className="bg-white p-3 rounded-xl border border-slate-200 shadow-sm flex items-center justify-between">
            <span className="text-xs font-semibold uppercase text-slate-500">Memos History</span>
            <select
              value={statusFilter}
              onChange={(e) => {
                setStatusFilter(e.target.value);
                if (clientId) void loadMemos(clientId);
              }}
              className="px-2 py-1 bg-slate-50 border border-slate-200 rounded-lg text-xs font-medium text-slate-700 outline-none"
            >
              <option value="">All Statuses</option>
              <option value="draft">Draft</option>
              <option value="review">Review</option>
              <option value="approved">Approved</option>
              <option value="published">Published</option>
            </select>
          </div>

          {loading ? (
            <div className="p-8 text-center text-slate-400 text-xs">
              <RefreshCw className="w-5 h-5 animate-spin mx-auto text-blue-600 mb-2" />
              Loading client memos…
            </div>
          ) : memos.length === 0 ? (
            <div className="bg-white border border-slate-200 rounded-xl p-8 text-center text-slate-400">
              <FileText className="w-8 h-8 text-slate-300 mx-auto mb-2" />
              <p className="text-sm font-semibold text-slate-700">No memos created yet</p>
              <p className="text-xs text-slate-400 mt-1">
                Click &quot;Generate New 30-Day Memo&quot; above to synthesize the first executive report.
              </p>
            </div>
          ) : (
            <div className="space-y-2">
              {memos.map((memo) => {
                const isSelected = selectedMemo?.id === memo.id;
                return (
                  <button
                    key={memo.id}
                    onClick={() => setSelectedMemo(memo)}
                    className={`w-full text-left p-4 rounded-xl border transition flex items-start justify-between gap-3 ${
                      isSelected
                        ? "bg-blue-50/70 border-blue-300 shadow-sm"
                        : "bg-white border-slate-200 hover:border-slate-300"
                    }`}
                  >
                    <div className="space-y-1.5 flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span
                          className={`px-2 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wider ${
                            memo.status === "published"
                              ? "bg-emerald-100 text-emerald-800"
                              : memo.status === "approved"
                              ? "bg-blue-100 text-blue-800"
                              : memo.status === "review"
                              ? "bg-amber-100 text-amber-800"
                              : "bg-slate-100 text-slate-700"
                          }`}
                        >
                          {memo.status}
                        </span>
                        <span className="text-xs text-slate-400 truncate">
                          {memo.period_start} → {memo.period_end}
                        </span>
                      </div>
                      <h4 className="font-semibold text-sm text-slate-900 truncate">
                        {memo.title || "Executive Client Memo"}
                      </h4>
                      <p className="text-xs text-slate-500">
                        Generated {formatDateTime(memo.created_at)}
                      </p>
                    </div>
                    <ChevronRight className={`w-4 h-4 mt-1 flex-shrink-0 ${isSelected ? "text-blue-600" : "text-slate-300"}`} />
                  </button>
                );
              })}
            </div>
          )}
        </div>

        {/* Right Column: Active Memo Reader & Workflow (8 cols) */}
        <div className="lg:col-span-8">
          {!selectedMemo ? (
            <div className="bg-white border border-slate-200 rounded-xl p-16 text-center text-slate-400">
              <Eye className="w-10 h-10 text-slate-300 mx-auto mb-3" />
              <p className="text-base font-semibold text-slate-700">Select a memo to review</p>
              <p className="text-xs text-slate-400 mt-1">
                View synthesized ROI, won citations, and strategic recommendations.
              </p>
            </div>
          ) : (
            <div className="bg-white border border-slate-200 rounded-xl shadow-sm overflow-hidden">
              {/* Memo Header & Controls */}
              <div className="p-6 border-b border-slate-200 bg-slate-50/50 space-y-4">
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                  <div>
                    <div className="flex items-center gap-2">
                      <h2 className="text-xl font-bold text-slate-900">{selectedMemo.title}</h2>
                      <span
                        className={`px-2.5 py-0.5 rounded-full text-xs font-semibold uppercase tracking-wider ${
                          selectedMemo.status === "published"
                            ? "bg-emerald-100 text-emerald-800 border border-emerald-200"
                            : selectedMemo.status === "approved"
                            ? "bg-blue-100 text-blue-800 border border-blue-200"
                            : selectedMemo.status === "review"
                            ? "bg-amber-100 text-amber-800 border border-amber-200"
                            : "bg-slate-100 text-slate-700"
                        }`}
                      >
                        {selectedMemo.status}
                      </span>
                    </div>
                    <p className="text-xs text-slate-500 mt-1 flex items-center gap-2">
                      <Calendar className="w-3.5 h-3.5" />
                      <span>
                        Reporting Period: {selectedMemo.period_start} to {selectedMemo.period_end}
                      </span>
                    </p>
                  </div>

                  {/* Actions / Export Bar */}
                  <div className="flex items-center gap-2 flex-wrap">
                    <button
                      onClick={() => handleCopyMarkdown(selectedMemo.markdown_body || "")}
                      className="px-3 py-1.5 bg-white border border-slate-200 hover:bg-slate-50 text-slate-700 rounded-lg text-xs font-medium transition inline-flex items-center gap-1.5 shadow-sm"
                    >
                      {copied ? <Check className="w-3.5 h-3.5 text-emerald-600" /> : <Copy className="w-3.5 h-3.5" />}
                      <span>{copied ? "Copied" : "Copy Markdown"}</span>
                    </button>

                    <button
                      onClick={() => handleExportMarkdown(selectedMemo.id)}
                      className="px-3 py-1.5 bg-white border border-slate-200 hover:bg-slate-50 text-slate-700 rounded-lg text-xs font-medium transition inline-flex items-center gap-1.5 shadow-sm"
                    >
                      <Download className="w-3.5 h-3.5" />
                      <span>Export .md</span>
                    </button>
                  </div>
                </div>

                {/* KPI Pill Rollup */}
                {metrics && (
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 pt-2">
                    <div className="bg-white p-3 rounded-lg border border-slate-200 shadow-xs">
                      <div className="text-[11px] text-slate-500 uppercase tracking-wider font-semibold">Visibility Rate</div>
                      <div className="text-lg font-bold text-slate-900 mt-0.5">
                        {metrics.visibility_pct != null ? `${Number(metrics.visibility_pct).toFixed(1)}%` : "—"}
                      </div>
                    </div>
                    <div className="bg-white p-3 rounded-lg border border-slate-200 shadow-xs">
                      <div className="text-[11px] text-slate-500 uppercase tracking-wider font-semibold">Won Gaps</div>
                      <div className="text-lg font-bold text-emerald-600 mt-0.5">
                        {metrics.won_gaps_count ?? 0}
                      </div>
                    </div>
                    <div className="bg-white p-3 rounded-lg border border-slate-200 shadow-xs">
                      <div className="text-[11px] text-slate-500 uppercase tracking-wider font-semibold">Mentions Gained</div>
                      <div className="text-lg font-bold text-indigo-600 mt-0.5">
                        {metrics.mentions_count ?? 0}
                      </div>
                    </div>
                    <div className="bg-white p-3 rounded-lg border border-slate-200 shadow-xs">
                      <div className="text-[11px] text-slate-500 uppercase tracking-wider font-semibold">Content Shipped</div>
                      <div className="text-lg font-bold text-blue-600 mt-0.5">
                        {metrics.published_count ?? 0}
                      </div>
                    </div>
                  </div>
                )}

                {/* Workflow Buttons Bar */}
                <div className="flex items-center justify-between pt-3 border-t border-slate-200">
                  <div className="text-xs text-slate-500">
                    {selectedMemo.published_url ? (
                      <span className="flex items-center gap-1 text-emerald-700 font-medium">
                        <CheckCircle2 className="w-3.5 h-3.5" /> Portal URL: {selectedMemo.published_url}
                      </span>
                    ) : (
                      <span>Requires editor sign-off before client release</span>
                    )}
                  </div>

                  <div className="flex items-center gap-2">
                    {/* Approve / Revise / Reject controls */}
                    {(selectedMemo.status === "review" || selectedMemo.status === "draft") && (
                      <>
                        <button
                          onClick={() => {
                            setFeedbackDecision("revise");
                            setShowFeedbackModal(true);
                          }}
                          className="px-3 py-1.5 text-slate-600 hover:bg-slate-100 rounded-lg text-xs font-medium transition"
                        >
                          Request Revision
                        </button>
                        <button
                          onClick={() => handleApproveMemo(selectedMemo.id)}
                          disabled={actionLoading === "approve"}
                          className="px-4 py-1.5 bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg text-xs font-semibold transition shadow-sm inline-flex items-center gap-1"
                        >
                          <ThumbsUp className="w-3.5 h-3.5" />
                          <span>{actionLoading === "approve" ? "Approving…" : "Approve Memo"}</span>
                        </button>
                      </>
                    )}

                    {/* Publish to Portal button */}
                    {selectedMemo.status === "approved" && (
                      <button
                        onClick={() => handlePublishMemo(selectedMemo.id)}
                        disabled={actionLoading === "publish"}
                        className="px-4 py-1.5 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-xs font-semibold transition shadow-sm inline-flex items-center gap-1"
                      >
                        <Send className="w-3.5 h-3.5" />
                        <span>{actionLoading === "publish" ? "Publishing…" : "Publish to Client Portal"}</span>
                      </button>
                    )}
                  </div>
                </div>
              </div>

              {/* Memo Body: Rendered Markdown */}
              <div className="p-8 prose prose-slate max-w-none text-sm leading-relaxed whitespace-pre-wrap font-sans text-slate-800 bg-white">
                {selectedMemo.markdown_body || "No memo content available."}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* MODAL: Request Revision or Reject */}
      {showFeedbackModal && (
        <div className="fixed inset-0 z-50 bg-black/40 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl max-w-md w-full p-6 shadow-xl space-y-4">
            <div className="flex items-center justify-between pb-3 border-b border-slate-100">
              <h3 className="font-semibold text-slate-900">
                {feedbackDecision === "revise" ? "Request Changes" : "Reject Memo"}
              </h3>
              <button onClick={() => setShowFeedbackModal(false)} className="text-slate-400 hover:text-slate-600">
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="space-y-3">
              <label className="block text-xs font-semibold text-slate-700 uppercase">
                Feedback for Strategist
              </label>
              <textarea
                rows={4}
                required
                placeholder="Specify required additions, fact updates, or strategic adjustments…"
                value={feedbackText}
                onChange={(e) => setFeedbackText(e.target.value)}
                className="w-full px-3 py-2 bg-white border border-slate-200 rounded-lg text-sm text-slate-800 outline-none"
              />
            </div>

            <div className="flex items-center justify-end gap-3 pt-3 border-t border-slate-100">
              <button
                type="button"
                onClick={() => setShowFeedbackModal(false)}
                className="px-4 py-2 text-slate-600 hover:bg-slate-100 rounded-lg text-sm font-medium transition"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleSubmitFeedback}
                disabled={actionLoading === "feedback"}
                className="px-4 py-2 bg-amber-600 hover:bg-amber-700 text-white rounded-lg text-sm font-medium transition"
              >
                {actionLoading === "feedback" ? "Submitting…" : "Submit Feedback"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
