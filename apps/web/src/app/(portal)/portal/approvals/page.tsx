"use client";

import { useEffect, useState } from "react";
import {
  AlertCircle,
  Check,
  CheckCircle2,
  Clock,
  ExternalLink,
  FileText,
  Loader2,
  Lock,
  MessageSquare,
  RefreshCw,
  ShieldCheck,
  X,
} from "lucide-react";
import {
  PortalApprovalItem,
  portalApi,
  getSelectedClientId,
} from "@/lib/api";

export default function ClientApprovalsPage() {
  const [clientId, setClientId] = useState<string | null>(null);
  const [userRole, setUserRole] = useState<string>("client_approver");
  const [loading, setLoading] = useState(true);
  const [items, setItems] = useState<PortalApprovalItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [actionLoading, setActionLoading] = useState<string | null>(null);

  // Tab: pending vs all
  const [tab, setTab] = useState<"pending" | "all">("pending");

  // Review modal
  const [selectedItem, setSelectedItem] = useState<PortalApprovalItem | null>(null);
  const [decisionAction, setDecisionAction] = useState<"approved" | "rejected" | "changes_requested">("approved");
  const [comment, setComment] = useState("");

  const loadApprovals = async (cid?: string) => {
    try {
      setLoading(true);
      setError(null);
      const data = await portalApi.listApprovals(cid);
      setItems(data);
    } catch (err: any) {
      setError(err?.message || "Failed to load approval items");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    const activeCid = getSelectedClientId() || undefined;
    portalApi.getMe(activeCid)
      .then((me) => {
        setUserRole(me.role);
        const resolvedCid = me.active_client_id || undefined;
        setClientId(resolvedCid || null);
        return loadApprovals(resolvedCid);
      })
      .catch((err) => {
        setError(err.message || "Failed to load client credentials");
        setLoading(false);
      });
  }, []);

  const isViewer = userRole === "client_viewer";

  const handleAction = async (
    item: PortalApprovalItem,
    action: "approved" | "rejected" | "changes_requested",
    customComment?: string
  ) => {
    if (isViewer) {
      setError("Client viewers have read-only access and cannot decide approvals");
      return;
    }
    try {
      setActionLoading(item.id);
      await portalApi.decideApproval(item.id, action, customComment);
      setNotice(`Decision submitted: ${action.replace("_", " ")}`);
      setSelectedItem(null);
      setComment("");
      await loadApprovals(clientId || undefined);
    } catch (err: any) {
      setError(err?.message || "Failed to submit approval decision");
    } finally {
      setActionLoading(null);
    }
  };

  const filteredItems = items.filter((i) => {
    if (tab === "pending") return i.status === "pending";
    return true;
  });

  const pendingCount = items.filter((i) => i.status === "pending").length;

  return (
    <div className="space-y-6 max-w-5xl mx-auto pb-12 animate-in fade-in duration-300">
      {/* Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-2 border-b border-slate-200">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-2xl font-bold tracking-tight text-slate-900">Content Approvals</h1>
            {pendingCount > 0 && (
              <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-bold bg-amber-100 text-amber-800">
                {pendingCount} Pending
              </span>
            )}
          </div>
          <p className="text-sm text-slate-500 mt-0.5">
            Strict human verification gate. Nothing is published to search engines or AI crawlers without signoff.
          </p>
        </div>

        <button
          onClick={() => loadApprovals(clientId || undefined)}
          disabled={loading}
          className="inline-flex items-center px-3 py-1.5 border border-slate-200 rounded-lg text-xs font-medium text-slate-700 bg-white hover:bg-slate-50 transition shadow-2xs disabled:opacity-50"
        >
          <RefreshCw className={`w-3.5 h-3.5 mr-1.5 ${loading ? "animate-spin text-slate-400" : "text-slate-600"}`} />
          Refresh
        </button>
      </div>

      {/* Read-Only Banner for client_viewer */}
      {isViewer && (
        <div className="bg-slate-100 border border-slate-200 text-slate-700 px-4 py-3 rounded-xl text-xs flex items-center gap-2.5">
          <Lock className="w-4 h-4 text-slate-500 flex-shrink-0" />
          <span>
            <strong>Read-only Access:</strong> You are signed in with the <em>Client Viewer</em> role. You can review proposed content, but approval and rejection rights require an authorized <em>Client Approver</em>.
          </span>
        </div>
      )}

      {/* Notices */}
      {notice && (
        <div className="bg-emerald-50 border border-emerald-200 text-emerald-800 px-4 py-2.5 rounded-xl text-xs flex items-center justify-between shadow-2xs animate-in fade-in">
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
        <div className="bg-rose-50 border border-rose-200 text-rose-800 px-4 py-2.5 rounded-xl text-xs flex items-center justify-between shadow-2xs animate-in fade-in">
          <div className="flex items-center gap-2">
            <AlertCircle className="w-4 h-4 text-rose-600 flex-shrink-0" />
            <span>{error}</span>
          </div>
          <button onClick={() => setError(null)} className="text-rose-600 hover:text-rose-800">
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      )}

      {/* Tabs */}
      <div className="flex items-center space-x-2 border-b border-slate-200 text-xs font-medium">
        <button
          onClick={() => setTab("pending")}
          className={`px-4 py-2 border-b-2 transition flex items-center gap-1.5 ${
            tab === "pending"
              ? "border-slate-900 text-slate-900 font-semibold"
              : "border-transparent text-slate-500 hover:text-slate-800"
          }`}
        >
          Pending Signoff ({pendingCount})
        </button>
        <button
          onClick={() => setTab("all")}
          className={`px-4 py-2 border-b-2 transition flex items-center gap-1.5 ${
            tab === "all"
              ? "border-slate-900 text-slate-900 font-semibold"
              : "border-transparent text-slate-500 hover:text-slate-800"
          }`}
        >
          All Activity ({items.length})
        </button>
      </div>

      {/* Approvals List */}
      <div className="space-y-3">
        {loading && items.length === 0 ? (
          <div className="h-64 flex flex-col items-center justify-center text-slate-400 gap-2">
            <Loader2 className="w-6 h-6 animate-spin text-slate-600" />
            <span className="text-xs">Loading pending approvals...</span>
          </div>
        ) : filteredItems.length === 0 ? (
          <div className="p-12 bg-white border border-slate-200 rounded-2xl text-center space-y-2 shadow-2xs">
            <ShieldCheck className="w-8 h-8 text-emerald-500 mx-auto" />
            <h4 className="text-base font-semibold text-slate-900">All caught up!</h4>
            <p className="text-xs text-slate-500 max-w-sm mx-auto">
              There are no content items currently waiting on your approval. When new briefs or drafts are generated, they will appear here.
            </p>
          </div>
        ) : (
          filteredItems.map((item) => {
            const isActing = actionLoading === item.id;
            const isPending = item.status === "pending";

            return (
              <div
                key={item.id}
                className="bg-white border border-slate-200 rounded-2xl p-5 shadow-2xs flex flex-col md:flex-row md:items-center justify-between gap-4 hover:border-slate-300 transition"
              >
                <div className="flex items-start space-x-3.5">
                  <div
                    className={`p-2.5 rounded-xl flex-shrink-0 ${
                      item.subject_type === "brief"
                        ? "bg-blue-50 text-blue-600"
                        : item.subject_type === "memo"
                        ? "bg-emerald-50 text-emerald-600"
                        : "bg-purple-50 text-purple-600"
                    }`}
                  >
                    <FileText className="w-5 h-5" />
                  </div>
                  <div>
                    <div className="flex items-center space-x-2">
                      <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400">
                        {item.subject_type} Gate
                      </span>
                      <span className="w-1 h-1 bg-slate-300 rounded-full" />
                      <span className="text-xs text-slate-500 flex items-center">
                        <Clock className="w-3 h-3 mr-1" />{" "}
                        {item.requested_at
                          ? new Date(item.requested_at).toLocaleDateString()
                          : "Recently"}
                      </span>
                      <span
                        className={`text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded ${
                          item.status === "approved"
                            ? "bg-emerald-100 text-emerald-800"
                            : item.status === "rejected"
                            ? "bg-rose-100 text-rose-800"
                            : item.status === "changes_requested"
                            ? "bg-amber-100 text-amber-800"
                            : "bg-slate-100 text-slate-700"
                        }`}
                      >
                        {item.status.replace("_", " ")}
                      </span>
                    </div>

                    <h3 className="text-base font-semibold text-slate-900 mt-1">
                      {item.title}
                    </h3>

                    {item.subtitle && (
                      <p className="text-xs text-slate-500 mt-0.5 italic">
                        {item.subtitle}
                      </p>
                    )}

                    {item.preview.excerpt && (
                      <p className="text-xs text-slate-600 mt-2 bg-slate-50 p-2.5 rounded-lg border border-slate-100 leading-relaxed font-sans">
                        &ldquo;{item.preview.excerpt}&rdquo;
                      </p>
                    )}

                    {item.comment && (
                      <div className="mt-2 text-xs bg-slate-50 border border-slate-200/80 rounded-lg p-2 text-slate-600">
                        <strong>Reviewer note:</strong> {item.comment}
                      </div>
                    )}
                  </div>
                </div>

                {/* Actions */}
                {isPending && (
                  <div className="flex items-center space-x-2 self-end md:self-center flex-shrink-0">
                    <button
                      onClick={() => {
                        setSelectedItem(item);
                        setDecisionAction("changes_requested");
                      }}
                      disabled={isActing || isViewer}
                      title={isViewer ? "Viewer mode is read-only" : undefined}
                      className="inline-flex items-center px-3.5 py-1.5 bg-white border border-slate-200 text-slate-700 rounded-lg hover:bg-slate-50 transition text-xs font-medium disabled:opacity-50"
                    >
                      <MessageSquare className="w-3.5 h-3.5 mr-1.5 text-slate-500" />
                      Feedback
                    </button>

                    <button
                      onClick={() => handleAction(item, "approved", "Approved via client portal")}
                      disabled={isActing || isViewer}
                      title={isViewer ? "Viewer mode is read-only" : undefined}
                      className="inline-flex items-center px-4 py-1.5 bg-emerald-600 text-white rounded-lg hover:bg-emerald-700 transition text-xs font-medium shadow-2xs disabled:opacity-50"
                    >
                      {isActing ? (
                        <Loader2 className="w-3.5 h-3.5 animate-spin mr-1.5" />
                      ) : (
                        <Check className="w-3.5 h-3.5 mr-1.5" />
                      )}
                      Approve
                    </button>
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>

      {/* Review Feedback Modal */}
      {selectedItem && (
        <div className="fixed inset-0 bg-slate-900/40 backdrop-blur-xs flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-2xl max-w-md w-full border border-slate-200 shadow-xl overflow-hidden animate-in zoom-in-95 duration-200">
            <div className="px-6 py-4 border-b border-slate-100 flex items-center justify-between">
              <div>
                <h3 className="text-base font-bold text-slate-900">Review &amp; Feedback</h3>
                <p className="text-xs text-slate-500 truncate max-w-xs">{selectedItem.title}</p>
              </div>
              <button
                onClick={() => setSelectedItem(null)}
                className="text-slate-400 hover:text-slate-600 p-1 rounded-lg"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="p-6 space-y-4">
              <div>
                <label className="block text-xs font-medium text-slate-700 mb-1.5">Action</label>
                <div className="grid grid-cols-2 gap-2">
                  <button
                    type="button"
                    onClick={() => setDecisionAction("changes_requested")}
                    className={`py-2 px-3 rounded-lg text-xs font-medium border flex items-center justify-center gap-1 transition ${
                      decisionAction === "changes_requested"
                        ? "bg-amber-600 text-white border-amber-600"
                        : "bg-white text-slate-700 border-slate-200 hover:bg-slate-50"
                    }`}
                  >
                    <MessageSquare className="w-3.5 h-3.5" /> Request Revisions
                  </button>
                  <button
                    type="button"
                    onClick={() => setDecisionAction("rejected")}
                    className={`py-2 px-3 rounded-lg text-xs font-medium border flex items-center justify-center gap-1 transition ${
                      decisionAction === "rejected"
                        ? "bg-rose-600 text-white border-rose-600"
                        : "bg-white text-slate-700 border-slate-200 hover:bg-slate-50"
                    }`}
                  >
                    <X className="w-3.5 h-3.5" /> Reject
                  </button>
                </div>
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-700 mb-1">
                  Required Changes / Feedback Notes
                </label>
                <textarea
                  rows={3}
                  value={comment}
                  onChange={(e) => setComment(e.target.value)}
                  placeholder="e.g. Please clarify paragraph 2 regarding our enterprise pricing tier..."
                  className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-slate-900/10 focus:border-slate-900"
                />
              </div>

              <div className="flex items-center justify-end gap-2 pt-2 border-t border-slate-100">
                <button
                  type="button"
                  onClick={() => setSelectedItem(null)}
                  className="px-4 py-2 border border-slate-200 rounded-lg text-xs font-medium text-slate-700 hover:bg-slate-50"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={() => handleAction(selectedItem, decisionAction, comment)}
                  disabled={actionLoading === selectedItem.id}
                  className="px-4 py-2 bg-slate-900 text-white rounded-lg text-xs font-medium hover:bg-slate-800 shadow-sm flex items-center gap-1.5 disabled:opacity-50"
                >
                  {actionLoading === selectedItem.id ? (
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  ) : (
                    <Check className="w-3.5 h-3.5" />
                  )}
                  Submit Decision
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
