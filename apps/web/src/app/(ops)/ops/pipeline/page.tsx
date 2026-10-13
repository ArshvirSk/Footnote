"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  AlertCircle,
  ArrowRight,
  Check,
  CheckCircle2,
  Clock,
  ExternalLink,
  FileText,
  Filter,
  Loader2,
  MoreHorizontal,
  PenTool,
  Plus,
  RefreshCw,
  Sparkles,
  X,
  Zap,
} from "lucide-react";
import {
  contentApi,
  refreshApi,
  getDefaultClientId,
  KanbanCard,
  PipelineKanbanColumn,
  PipelineKanbanResponse,
  type RefreshProposal,
} from "@/lib/api";

export default function PipelinePage() {
  const [clientId, setClientId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [columns, setColumns] = useState<PipelineKanbanColumn[]>([]);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  // New brief modal
  const [showNewBrief, setShowNewBrief] = useState(false);
  const [briefTitle, setBriefTitle] = useState("");
  const [briefAngle, setBriefAngle] = useState("");
  const [briefSources, setBriefSources] = useState("");

  // Content Refresh & Decay state
  const [proposals, setProposals] = useState<RefreshProposal[]>([]);
  const [showProposals, setShowProposals] = useState(false);
  const [scanningDecay, setScanningDecay] = useState(false);

  const loadProposals = async (cid: string) => {
    try {
      const list = await refreshApi.listProposals(cid, "pending");
      setProposals(list);
    } catch {
      // non-fatal
    }
  };

  const loadPipeline = async (cid: string) => {
    try {
      setLoading(true);
      setError(null);
      const data = await contentApi.pipeline(cid);
      setColumns(data.columns);
    } catch (err: any) {
      setError(err?.message || "Failed to load pipeline data");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    getDefaultClientId()
      .then((cid) => {
        setClientId(cid);
        void loadProposals(cid);
        return loadPipeline(cid);
      })
      .catch((err) => {
        setError(err.message || "Failed to resolve active client");
        setLoading(false);
      });
  }, []);

  const handleScanDecay = async () => {
    if (!clientId) return;
    try {
      setScanningDecay(true);
      setError(null);
      const res = await refreshApi.scan(clientId);
      setNotice(
        `Decay scan complete: ${res.scanned} scanned, ${res.decayed_found} decayed items detected, ${res.proposals_created} refresh proposals created.`
      );
      await loadProposals(clientId);
      await loadPipeline(clientId);
      if (res.proposals_created > 0) setShowProposals(true);
    } catch (err: any) {
      setError(err?.message || "Decay scan failed");
    } finally {
      setScanningDecay(false);
    }
  };

  const handleDecideProposal = async (proposalId: string, decision: "approved" | "rejected") => {
    if (!clientId) return;
    try {
      setActionLoading(`prop-${proposalId}`);
      await refreshApi.decideProposal(clientId, proposalId, decision);
      setNotice(`Refresh proposal ${decision === "approved" ? "approved & queued for publishing" : "rejected"}.`);
      await loadProposals(clientId);
      await loadPipeline(clientId);
    } catch (err: any) {
      setError(err?.message || "Proposal decision failed");
    } finally {
      setActionLoading(null);
    }
  };

  const handleGenerateBrief = async (gapId: string) => {
    if (!clientId) return;
    try {
      setActionLoading(`brief-${gapId}`);
      await contentApi.generateBrief(clientId, gapId);
      setNotice("AI brief generated from gap!");
      await loadPipeline(clientId);
    } catch (err: any) {
      setError(err?.message || "Failed to generate brief");
    } finally {
      setActionLoading(null);
    }
  };

  const handleGenerateDraft = async (briefId: string) => {
    if (!clientId) return;
    try {
      setActionLoading(`draft-${briefId}`);
      await contentApi.generateDraft(clientId, briefId);
      setNotice("3-pass AI draft generated (Strategist → Writer → Editor)!");
      await loadPipeline(clientId);
    } catch (err: any) {
      setError(err?.message || "Failed to generate draft");
    } finally {
      setActionLoading(null);
    }
  };

  const handleActionApproval = async (approvalId: string, action: "approve" | "reject") => {
    if (!clientId) return;
    try {
      setActionLoading(`appr-${approvalId}`);
      await contentApi.actionApproval(clientId, approvalId, action);
      setNotice(`Gate decision: ${action === "approve" ? "Approved" : "Rejected"} successfully`);
      await loadPipeline(clientId);
    } catch (err: any) {
      setError(err?.message || "Approval decision failed");
    } finally {
      setActionLoading(null);
    }
  };

  const handlePublish = async (itemId: string) => {
    if (!clientId) return;
    try {
      setActionLoading(`pub-${itemId}`);
      await contentApi.updateItem(clientId, itemId, { status: "published" });
      setNotice("Content published to live targets!");
      await loadPipeline(clientId);
    } catch (err: any) {
      setError(err?.message || "Publishing failed. Ensure approval gate is signed off.");
    } finally {
      setActionLoading(null);
    }
  };

  const handleCreateManualBrief = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!clientId || !briefTitle.trim()) return;

    try {
      setActionLoading("new-brief");
      await contentApi.createBrief(clientId, {
        title: briefTitle,
        angle: briefAngle,
        sources: briefSources
          .split("\n")
          .map((s) => s.trim())
          .filter(Boolean),
        outline: [
          { heading: "Executive Summary", points: ["Key thesis", "Context"] },
          { heading: "Deep Dive", points: ["Core analysis", "Supporting data"] },
          { heading: "Recommendation & Next Steps", points: ["Action items"] },
        ],
      });
      setShowNewBrief(false);
      setBriefTitle("");
      setBriefAngle("");
      setBriefSources("");
      setNotice("Brief created successfully!");
      await loadPipeline(clientId);
    } catch (err: any) {
      setError(err?.message || "Failed to create brief");
    } finally {
      setActionLoading(null);
    }
  };

  return (
    <div className="h-[calc(100vh-6rem)] flex flex-col space-y-4">
      {/* Header bar */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-2 border-b border-slate-200">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-2xl font-bold tracking-tight text-slate-900">Content Pipeline</h1>
            <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-emerald-100 text-emerald-800">
              M4 Engine Live
            </span>
          </div>
          <p className="text-sm text-slate-500 mt-0.5">
            Gaps &rarr; 3-Pass AI Engine &rarr; Human Approval Hard Gates &rarr; Verified Publishing.
          </p>
        </div>

        <div className="flex items-center gap-2">
          {clientId && (
            <>
              <button
                onClick={handleScanDecay}
                disabled={scanningDecay}
                className="inline-flex items-center px-3 py-1.5 border border-purple-200 rounded-lg text-xs font-medium text-purple-700 bg-purple-50 hover:bg-purple-100 transition shadow-2xs disabled:opacity-50"
              >
                <Sparkles className={`w-3.5 h-3.5 mr-1.5 ${scanningDecay ? "animate-spin text-purple-500" : "text-purple-600"}`} />
                {scanningDecay ? "Scanning…" : "Scan Decay"}
              </button>

              {proposals.length > 0 && (
                <button
                  onClick={() => setShowProposals(true)}
                  className="inline-flex items-center px-3 py-1.5 bg-amber-500 text-white rounded-lg text-xs font-semibold hover:bg-amber-600 transition shadow-2xs animate-pulse"
                >
                  <Zap className="w-3.5 h-3.5 mr-1" />
                  Refresh Proposals ({proposals.length})
                </button>
              )}

              <button
                onClick={() => loadPipeline(clientId)}
                disabled={loading}
                className="inline-flex items-center px-3 py-1.5 border border-slate-300 rounded-lg text-xs font-medium text-slate-700 bg-white hover:bg-slate-50 transition shadow-sm disabled:opacity-50"
              >
                <RefreshCw className={`w-3.5 h-3.5 mr-1.5 ${loading ? "animate-spin text-slate-400" : "text-slate-600"}`} />
                Refresh
              </button>
            </>
          )}
          <button
            onClick={() => setShowNewBrief(true)}
            className="inline-flex items-center px-3.5 py-1.5 bg-slate-900 text-white rounded-lg text-xs font-medium hover:bg-slate-800 transition shadow-sm"
          >
            <Plus className="w-3.5 h-3.5 mr-1.5" />
            New Brief
          </button>
        </div>
      </div>

      {/* Notifications / Errors */}
      {notice && (
        <div className="bg-emerald-50 border border-emerald-200 text-emerald-800 px-4 py-2 rounded-lg text-xs flex items-center justify-between shadow-sm animate-in fade-in">
          <div className="flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4 text-emerald-600 flex-shrink-0" />
            <span>{notice}</span>
          </div>
          <button onClick={() => setNotice(null)} className="text-emerald-600 hover:text-emerald-800">
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      )}

      {error && (
        <div className="bg-rose-50 border border-rose-200 text-rose-800 px-4 py-2 rounded-lg text-xs flex items-center justify-between shadow-sm animate-in fade-in">
          <div className="flex items-center gap-2">
            <AlertCircle className="w-4 h-4 text-rose-600 flex-shrink-0" />
            <span>{error}</span>
          </div>
          <button onClick={() => setError(null)} className="text-rose-600 hover:text-rose-800">
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      )}

      {/* Kanban Board Container */}
      <div className="flex-1 overflow-x-auto pb-4">
        {loading && columns.length === 0 ? (
          <div className="h-64 flex flex-col items-center justify-center text-slate-400 gap-2">
            <Loader2 className="w-6 h-6 animate-spin text-slate-500" />
            <span className="text-sm">Loading content pipeline stages...</span>
          </div>
        ) : (
          <div className="flex gap-4 min-w-max h-full">
            {columns.map((col) => (
              <div
                key={col.id}
                className="w-80 flex flex-col bg-slate-100/70 rounded-xl border border-slate-200/80 p-3 shadow-inner"
              >
                {/* Column header */}
                <div className="flex items-center justify-between mb-3 px-1">
                  <div className="flex items-center gap-2">
                    <h3 className="font-semibold text-slate-800 text-xs tracking-wide uppercase">
                      {col.name}
                    </h3>
                    <span className="inline-flex items-center justify-center px-1.5 py-0.5 text-[11px] font-bold rounded-full bg-white text-slate-600 border border-slate-200 shadow-2xs">
                      {col.count}
                    </span>
                  </div>
                </div>

                {/* Card list */}
                <div className="flex-1 space-y-3 overflow-y-auto pr-1">
                  {col.items.length === 0 ? (
                    <div className="h-28 border border-dashed border-slate-300 rounded-lg flex flex-col items-center justify-center text-slate-400 text-xs px-2 text-center">
                      <span>No items in this stage</span>
                    </div>
                  ) : (
                    col.items.map((card) => renderCard(card))
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* New Brief Modal */}
      {showNewBrief && (
        <div className="fixed inset-0 bg-slate-900/40 backdrop-blur-xs flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-2xl max-w-lg w-full border border-slate-200 shadow-xl overflow-hidden animate-in zoom-in-95 duration-200">
            <div className="px-6 py-4 border-b border-slate-100 flex items-center justify-between">
              <div>
                <h3 className="text-lg font-semibold text-slate-900">Create Content Brief</h3>
                <p className="text-xs text-slate-500">Grounded blueprint for SEO and AEO authority.</p>
              </div>
              <button
                onClick={() => setShowNewBrief(false)}
                className="text-slate-400 hover:text-slate-600 p-1 rounded-lg"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <form onSubmit={handleCreateManualBrief} className="p-6 space-y-4">
              <div>
                <label className="block text-xs font-medium text-slate-700 mb-1">
                  Working Title *
                </label>
                <input
                  type="text"
                  required
                  value={briefTitle}
                  onChange={(e) => setBriefTitle(e.target.value)}
                  placeholder="e.g. Best Enterprise CRM Platforms Compared"
                  className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-slate-900/10 focus:border-slate-900"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-700 mb-1">
                  Unique Angle / Thesis
                </label>
                <input
                  type="text"
                  value={briefAngle}
                  onChange={(e) => setBriefAngle(e.target.value)}
                  placeholder="e.g. Why legacy CRMs cost 3x in integration overhead"
                  className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-slate-900/10 focus:border-slate-900"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-700 mb-1">
                  Required Proof Points & Citations (1 per line)
                </label>
                <textarea
                  rows={3}
                  value={briefSources}
                  onChange={(e) => setBriefSources(e.target.value)}
                  placeholder="https://example.com/research-report&#10;Internal study 2026: 99.9% reliability guarantee"
                  className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-slate-900/10 focus:border-slate-900"
                />
              </div>

              <div className="flex items-center justify-end gap-2 pt-2 border-t border-slate-100">
                <button
                  type="button"
                  onClick={() => setShowNewBrief(false)}
                  className="px-4 py-2 border border-slate-200 rounded-lg text-xs font-medium text-slate-700 hover:bg-slate-50"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={actionLoading === "new-brief"}
                  className="px-4 py-2 bg-slate-900 text-white rounded-lg text-xs font-medium hover:bg-slate-800 shadow-sm flex items-center gap-1.5 disabled:opacity-50"
                >
                  {actionLoading === "new-brief" ? (
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  ) : (
                    <Check className="w-3.5 h-3.5" />
                  )}
                  Create Brief
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Refresh Proposals Modal */}
      {showProposals && (
        <div className="fixed inset-0 z-50 bg-black/40 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl max-w-2xl w-full p-6 shadow-xl space-y-4 max-h-[85vh] overflow-y-auto">
            <div className="flex items-center justify-between pb-3 border-b border-slate-100">
              <div className="flex items-center gap-2">
                <Zap className="w-5 h-5 text-amber-500" />
                <h3 className="font-semibold text-slate-900">Content Refresh Proposals</h3>
                <span className="text-xs px-2 py-0.5 rounded-full bg-amber-50 text-amber-700 border border-amber-200 font-medium">
                  {proposals.length} Pending
                </span>
              </div>
              <button onClick={() => setShowProposals(false)} className="text-slate-400 hover:text-slate-600">
                <X className="w-5 h-5" />
              </button>
            </div>

            <p className="text-xs text-slate-500">
              The Refresh Engine monitors published content against daily LLM runs. When mention rates decay or new competitor citations emerge, diffs are generated for editor approval.
            </p>

            {proposals.length === 0 ? (
              <div className="text-center py-8 text-slate-400 text-xs">
                No pending refresh proposals. All published content items are maintaining target visibility.
              </div>
            ) : (
              <div className="space-y-4">
                {proposals.map((p) => {
                  const isProcessing = actionLoading === `prop-${p.id}`;
                  return (
                    <div
                      key={p.id}
                      className="border border-slate-200 rounded-xl p-4 bg-slate-50/50 space-y-3"
                    >
                      <div className="flex items-center justify-between">
                        <div>
                          <span className="text-xs font-semibold text-slate-900">
                            {p.item_title || p.slug || "Published Item"}
                          </span>
                          {p.decay_score != null && (
                            <span className="ml-2 text-[10px] px-2 py-0.5 rounded bg-rose-50 text-rose-700 border border-rose-200 font-medium">
                              Decay Score: {Number(p.decay_score).toFixed(2)}
                            </span>
                          )}
                        </div>
                        <span className="text-[11px] text-slate-400">
                          {p.created_at ? new Date(p.created_at).toLocaleDateString() : "Recent"}
                        </span>
                      </div>

                      {p.diff_summary && (
                        <div className="bg-white p-3 rounded-lg border border-slate-200 text-xs font-mono text-slate-700 whitespace-pre-wrap max-h-36 overflow-y-auto">
                          {p.diff_summary}
                        </div>
                      )}

                      <div className="flex items-center justify-end gap-2 pt-2 border-t border-slate-100">
                        <button
                          onClick={() => handleDecideProposal(p.id, "rejected")}
                          disabled={isProcessing}
                          className="px-3 py-1.5 text-xs text-slate-600 hover:bg-slate-200 rounded-lg font-medium transition"
                        >
                          Reject
                        </button>
                        <button
                          onClick={() => handleDecideProposal(p.id, "approved")}
                          disabled={isProcessing}
                          className="px-4 py-1.5 bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg text-xs font-semibold transition flex items-center gap-1.5 shadow-2xs"
                        >
                          {isProcessing ? (
                            <Loader2 className="w-3.5 h-3.5 animate-spin" />
                          ) : (
                            <Check className="w-3.5 h-3.5" />
                          )}
                          <span>Approve Diff & Republish</span>
                        </button>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );

  function renderCard(card: KanbanCard) {
    const isBriefing = actionLoading === `brief-${card.gap_id}`;
    const isDrafting = actionLoading === `draft-${card.brief_id}`;
    const isDeciding = actionLoading === `appr-${card.approval_id}`;
    const isPublishing = actionLoading === `pub-${card.item_id}`;

    return (
      <div
        key={card.id}
        className="bg-white p-3.5 rounded-xl border border-slate-200 shadow-2xs hover:border-slate-300 hover:shadow-xs transition flex flex-col justify-between group"
      >
        <div>
          {/* Card badge header */}
          <div className="flex items-center justify-between mb-2">
            <span
              className={`text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded ${
                card.type === "Gap"
                  ? "bg-amber-100 text-amber-800"
                  : card.type === "Brief"
                  ? "bg-blue-100 text-blue-800"
                  : "bg-purple-100 text-purple-800"
              }`}
            >
              {card.type}
            </span>

            {card.approval_status && (
              <span
                className={`text-[10px] font-semibold px-1.5 py-0.5 rounded ${
                  card.approval_status === "approved"
                    ? "bg-emerald-50 text-emerald-700 border border-emerald-200"
                    : card.approval_status === "rejected"
                    ? "bg-rose-50 text-rose-700 border border-rose-200"
                    : "bg-amber-50 text-amber-700 border border-amber-200"
                }`}
              >
                {card.approval_status}
              </span>
            )}
          </div>

          {/* Title */}
          <h4 className="font-semibold text-slate-900 text-sm leading-snug line-clamp-2">
            {card.title}
          </h4>

          {/* Subtitle / metadata */}
          {card.subtitle && (
            <p className="text-xs text-slate-500 mt-1 line-clamp-2">{card.subtitle}</p>
          )}

          {card.decay_score && card.decay_score > 0 ? (
            <div className="mt-2 text-[11px] font-medium text-rose-600 flex items-center">
              <Zap className="w-3 h-3 mr-1" /> Decay score: {card.decay_score.toFixed(1)}
            </div>
          ) : null}
        </div>

        {/* Action controls */}
        <div className="mt-3 pt-2.5 border-t border-slate-100 flex items-center justify-between gap-1 text-xs">
          {/* 1. Gap card action: Trigger AI Brief */}
          {card.type === "Gap" && card.gap_id && (
            <button
              onClick={() => handleGenerateBrief(card.gap_id!)}
              disabled={isBriefing}
              className="w-full inline-flex items-center justify-center px-2.5 py-1.5 bg-amber-50 text-amber-800 border border-amber-200 hover:bg-amber-100 rounded-lg text-xs font-medium transition disabled:opacity-50"
            >
              {isBriefing ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin mr-1.5" />
              ) : (
                <Sparkles className="w-3.5 h-3.5 mr-1.5 text-amber-600" />
              )}
              Generate Brief
            </button>
          )}

          {/* 2. Brief card action: Trigger 3-Pass AI Draft */}
          {card.type === "Brief" && card.brief_id && (
            <div className="w-full flex items-center justify-between gap-1">
              <button
                onClick={() => handleGenerateDraft(card.brief_id!)}
                disabled={isDrafting}
                className="flex-1 inline-flex items-center justify-center px-2 py-1.5 bg-blue-50 text-blue-800 border border-blue-200 hover:bg-blue-100 rounded-lg text-xs font-medium transition disabled:opacity-50"
              >
                {isDrafting ? (
                  <Loader2 className="w-3.5 h-3.5 animate-spin mr-1" />
                ) : (
                  <PenTool className="w-3.5 h-3.5 mr-1 text-blue-600" />
                )}
                Generate Draft
              </button>

              {card.approval_id && card.approval_status === "pending" && (
                <div className="flex items-center gap-1">
                  <button
                    onClick={() => handleActionApproval(card.approval_id!, "approve")}
                    disabled={isDeciding}
                    title="Signoff Brief"
                    className="p-1.5 bg-emerald-50 text-emerald-700 hover:bg-emerald-100 border border-emerald-200 rounded-lg transition"
                  >
                    <Check className="w-3.5 h-3.5" />
                  </button>
                  <button
                    onClick={() => handleActionApproval(card.approval_id!, "reject")}
                    disabled={isDeciding}
                    title="Reject Brief"
                    className="p-1.5 bg-rose-50 text-rose-700 hover:bg-rose-100 border border-rose-200 rounded-lg transition"
                  >
                    <X className="w-3.5 h-3.5" />
                  </button>
                </div>
              )}
            </div>
          )}

          {/* 3. Draft card action: Content workspace link, approvals, publish */}
          {card.type === "Draft" && card.item_id && (
            <div className="w-full space-y-2">
              <div className="flex items-center justify-between gap-1">
                <Link
                  href={`/ops/content/${card.item_id}`}
                  className="inline-flex items-center text-xs font-medium text-slate-700 hover:text-slate-900 group-hover:underline"
                >
                  <FileText className="w-3.5 h-3.5 mr-1 text-slate-500" />
                  Open Workspace &rarr;
                </Link>

                {card.published_url && (
                  <a
                    href={card.published_url}
                    target="_blank"
                    rel="noreferrer"
                    className="text-slate-400 hover:text-slate-700 p-1"
                    title="View live URL"
                  >
                    <ExternalLink className="w-3.5 h-3.5" />
                  </a>
                )}
              </div>

              {/* Approval controls for drafts in review */}
              {card.approval_id && card.approval_status === "pending" && (
                <div className="flex items-center gap-1.5 pt-1">
                  <button
                    onClick={() => handleActionApproval(card.approval_id!, "approve")}
                    disabled={isDeciding}
                    className="flex-1 inline-flex items-center justify-center px-2 py-1 bg-emerald-600 text-white hover:bg-emerald-700 rounded-lg text-xs font-medium transition shadow-2xs"
                  >
                    {isDeciding ? <Loader2 className="w-3 h-3 animate-spin mr-1" /> : <Check className="w-3 h-3 mr-1" />}
                    Approve Gate
                  </button>
                  <button
                    onClick={() => handleActionApproval(card.approval_id!, "reject")}
                    disabled={isDeciding}
                    className="px-2 py-1 bg-slate-100 text-slate-700 hover:bg-slate-200 rounded-lg text-xs font-medium transition"
                  >
                    Reject
                  </button>
                </div>
              )}

              {/* Publish button for approved drafts */}
              {card.status === "approved" && (
                <button
                  onClick={() => handlePublish(card.item_id!)}
                  disabled={isPublishing}
                  className="w-full inline-flex items-center justify-center px-2 py-1.5 bg-slate-900 text-white hover:bg-slate-800 rounded-lg text-xs font-medium transition shadow-2xs disabled:opacity-50"
                >
                  {isPublishing ? (
                    <Loader2 className="w-3 h-3 animate-spin mr-1.5" />
                  ) : (
                    <ExternalLink className="w-3 h-3 mr-1.5" />
                  )}
                  Publish Now
                </button>
              )}
            </div>
          )}
        </div>
      </div>
    );
  }
}
