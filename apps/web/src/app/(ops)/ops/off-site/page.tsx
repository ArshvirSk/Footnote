"use client";

import { useCallback, useEffect, useState } from "react";
import {
  MessageSquare,
  Share2,
  Send,
  CheckCircle2,
  Lock,
  Unlock,
  Sparkles,
  ExternalLink,
  Plus,
  Search,
  Filter,
  Globe,
  FileText,
  AlertTriangle,
  Trash2,
  Copy,
  Check,
  RefreshCw,
  Clock,
  ShieldCheck,
  X,
} from "lucide-react";
import {
  CLIENT_CHANGED_EVENT,
  getSelectedClientId,
  thirdPartyApi,
  outreachApi,
  websites,
  type ThirdPartyTask,
  type OutreachTarget,
  type OutreachMessage,
  type ClientSummary,
} from "@/lib/api";
import { formatDateTime } from "@/lib/ui";

type TabMode = "tasks" | "outreach";

export default function OffSitePage() {
  const [clientId, setClientId] = useState<string | null>(null);
  const [client, setClient] = useState<ClientSummary | null>(null);
  const [activeTab, setActiveTab] = useState<TabMode>("tasks");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  // Third-Party Tasks state
  const [tasks, setTasks] = useState<ThirdPartyTask[]>([]);
  const [platformFilter, setPlatformFilter] = useState<string>("");
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [showNewTaskModal, setShowNewTaskModal] = useState(false);
  const [newTaskPlatform, setNewTaskPlatform] = useState("reddit");
  const [newTaskUrl, setNewTaskUrl] = useState("");
  const [newTaskTitle, setNewTaskTitle] = useState("");
  const [newTaskContext, setNewTaskContext] = useState("");
  const [draftingTaskId, setDraftingTaskId] = useState<string | null>(null);
  const [selectedTask, setSelectedTask] = useState<ThirdPartyTask | null>(null);
  const [postedUrlInput, setPostedUrlInput] = useState("");

  // Digital PR & Outreach state
  const [targets, setTargets] = useState<OutreachTarget[]>([]);
  const [discovering, setDiscovering] = useState(false);
  const [selectedTarget, setSelectedTarget] = useState<(OutreachTarget & { messages: OutreachMessage[] }) | null>(null);
  const [draftingTargetId, setDraftingTargetId] = useState<string | null>(null);
  const [pitchType, setPitchType] = useState<string>("resource_addition");
  const [dispatchingId, setDispatchingId] = useState<string | null>(null);
  const [copiedId, setCopiedId] = useState<string | null>(null);

  const loadTasks = useCallback(async (cid: string) => {
    try {
      const data = await thirdPartyApi.listTasks(cid, {
        platform: platformFilter || undefined,
        status: statusFilter || undefined,
      });
      setTasks(data);
    } catch (err: any) {
      setError(err?.message || "Failed to load third-party tasks");
    }
  }, [platformFilter, statusFilter]);

  const loadTargets = useCallback(async (cid: string) => {
    try {
      const data = await outreachApi.listTargets(cid);
      setTargets(data);
    } catch (err: any) {
      setError(err?.message || "Failed to load outreach targets");
    }
  }, []);

  const loadAll = useCallback(
    async (cid: string) => {
      setLoading(true);
      setError(null);
      await Promise.all([loadTasks(cid), loadTargets(cid)]);
      setLoading(false);
    },
    [loadTasks, loadTargets]
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
      await loadAll(resolvedId);
    } catch (err: any) {
      setError(err?.message || "Failed to load websites");
      setLoading(false);
    }
  }, [loadAll]);

  useEffect(() => {
    void initClient();

    const handleClientChange = () => {
      const stored = getSelectedClientId();
      if (stored && stored !== clientId) {
        setClientId(stored);
        void loadAll(stored);
      }
    };

    window.addEventListener(CLIENT_CHANGED_EVENT, handleClientChange);
    return () => window.removeEventListener(CLIENT_CHANGED_EVENT, handleClientChange);
  }, [initClient, clientId, loadAll]);

  // Third-party handlers
  const handleCreateTask = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!clientId || !newTaskUrl) return;
    try {
      await thirdPartyApi.createTask(clientId, {
        platform: newTaskPlatform,
        thread_url: newTaskUrl,
        thread_title: newTaskTitle || undefined,
        prompt_context: newTaskContext || undefined,
      });
      setShowNewTaskModal(false);
      setNewTaskUrl("");
      setNewTaskTitle("");
      setNewTaskContext("");
      setNotice("Thread task added to board!");
      await loadTasks(clientId);
    } catch (err: any) {
      setError(err?.message || "Failed to create task");
    }
  };

  const handleDraftResponse = async (task: ThirdPartyTask) => {
    if (!clientId) return;
    try {
      setDraftingTaskId(task.id);
      setError(null);
      const res = await thirdPartyApi.draftResponse(clientId, task.id);
      setNotice("AI value-first response draft generated!");
      const updated = { ...task, response_draft: res.response_draft, status: "drafting" };
      setSelectedTask(updated);
      await loadTasks(clientId);
    } catch (err: any) {
      setError(err?.message || "Failed to draft response");
    } finally {
      setDraftingTaskId(null);
    }
  };

  const handleMarkAsPosted = async (task: ThirdPartyTask) => {
    if (!clientId) return;
    try {
      await thirdPartyApi.updateTask(clientId, task.id, {
        status: "posted",
        posted_url: postedUrlInput || task.thread_url,
      });
      setNotice("Task marked as live & verified!");
      setSelectedTask(null);
      setPostedUrlInput("");
      await loadTasks(clientId);
    } catch (err: any) {
      setError(err?.message || "Failed to update task");
    }
  };

  const handleDeleteTask = async (taskId: string) => {
    if (!clientId || !confirm("Delete this thread task?")) return;
    try {
      await thirdPartyApi.deleteTask(clientId, taskId);
      if (selectedTask?.id === taskId) setSelectedTask(null);
      await loadTasks(clientId);
    } catch (err: any) {
      setError(err?.message || "Failed to delete task");
    }
  };

  // Outreach handlers
  const handleDiscoverTargets = async () => {
    if (!clientId) return;
    try {
      setDiscovering(true);
      setError(null);
      const res = await outreachApi.discoverTargets(clientId, 20);
      setNotice(`Discovered ${res.inserted} new high-authority AI citation domains!`);
      await loadTargets(clientId);
    } catch (err: any) {
      setError(err?.message || "Discovery failed");
    } finally {
      setDiscovering(false);
    }
  };

  const handleViewTarget = async (targetId: string) => {
    if (!clientId) return;
    try {
      const full = await outreachApi.getTarget(clientId, targetId);
      setSelectedTarget(full);
    } catch (err: any) {
      setError(err?.message || "Failed to load target details");
    }
  };

  const handleDraftPitch = async (targetId: string) => {
    if (!clientId) return;
    try {
      setDraftingTargetId(targetId);
      setError(null);
      await outreachApi.draftPitch(clientId, targetId, pitchType);
      setNotice("Personalized pitch drafted and enqueued for review!");
      await loadTargets(clientId);
      if (selectedTarget?.id === targetId) {
        await handleViewTarget(targetId);
      }
    } catch (err: any) {
      setError(err?.message || "Failed to draft pitch");
    } finally {
      setDraftingTargetId(null);
    }
  };

  const handleDispatchMessage = async (messageId: string) => {
    if (!clientId) return;
    try {
      setDispatchingId(messageId);
      setError(null);
      const res = await outreachApi.dispatchMessage(clientId, messageId, true);
      setNotice(`Message dispatched successfully! (${res.detail})`);
      if (selectedTarget) {
        await handleViewTarget(selectedTarget.id);
      }
      await loadTargets(clientId);
    } catch (err: any) {
      setError(err?.message || "Dispatch blocked: Approval required");
    } finally {
      setDispatchingId(null);
    }
  };

  const copyToClipboard = (text: string, id: string) => {
    navigator.clipboard.writeText(text);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 2000);
  };

  return (
    <div className="space-y-6">
      {/* Top Title & Sub-tabs */}
      <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-3xl font-semibold tracking-tight text-slate-900">
              Off-Site Authority & PR
            </h1>
            {client && (
              <span className="px-2.5 py-0.5 rounded-full text-xs font-medium bg-blue-50 text-blue-700 border border-blue-200">
                {client.name}
              </span>
            )}
          </div>
          <p className="text-slate-600 mt-1 text-sm">
            Influence frontier LLM weights via high-authority community platforms & gated digital PR outreach.
          </p>
        </div>

        {/* Tab switchers */}
        <div className="flex items-center bg-slate-100 p-1 rounded-xl border border-slate-200 shadow-sm">
          <button
            onClick={() => setActiveTab("tasks")}
            className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition ${
              activeTab === "tasks"
                ? "bg-white text-slate-900 shadow-sm"
                : "text-slate-600 hover:text-slate-900"
            }`}
          >
            <MessageSquare className="w-4 h-4 text-blue-600" />
            <span>Third-Party Board</span>
            <span className="text-xs px-2 py-0.5 rounded-full bg-slate-100 text-slate-600">
              {tasks.length}
            </span>
          </button>
          <button
            onClick={() => setActiveTab("outreach")}
            className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition ${
              activeTab === "outreach"
                ? "bg-white text-slate-900 shadow-sm"
                : "text-slate-600 hover:text-slate-900"
            }`}
          >
            <Share2 className="w-4 h-4 text-purple-600" />
            <span>Digital PR Outreach</span>
            <span className="text-xs px-2 py-0.5 rounded-full bg-slate-100 text-slate-600">
              {targets.length}
            </span>
          </button>
        </div>
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
            <AlertTriangle className="w-4 h-4 flex-shrink-0" />
            <span>{error}</span>
          </div>
          <button onClick={() => setError(null)} className="text-rose-600 hover:text-rose-800">
            <X className="w-4 h-4" />
          </button>
        </div>
      )}

      {/* TAB 1: THIRD-PARTY TASK BOARD */}
      {activeTab === "tasks" && (
        <div className="space-y-6">
          {/* Controls Bar */}
          <div className="flex flex-col sm:flex-row items-center justify-between gap-4 bg-white p-4 rounded-xl border border-slate-200 shadow-sm">
            <div className="flex items-center gap-3 w-full sm:w-auto">
              <select
                value={platformFilter}
                onChange={(e) => {
                  setPlatformFilter(e.target.value);
                  if (clientId) void loadTasks(clientId);
                }}
                className="px-3 py-1.5 bg-slate-50 border border-slate-200 rounded-lg text-sm text-slate-700 outline-none"
              >
                <option value="">All Platforms</option>
                <option value="reddit">Reddit</option>
                <option value="quora">Quora</option>
                <option value="hackernews">Hacker News</option>
                <option value="forum">Niche Forum</option>
              </select>

              <select
                value={statusFilter}
                onChange={(e) => {
                  setStatusFilter(e.target.value);
                  if (clientId) void loadTasks(clientId);
                }}
                className="px-3 py-1.5 bg-slate-50 border border-slate-200 rounded-lg text-sm text-slate-700 outline-none"
              >
                <option value="">All Statuses</option>
                <option value="todo">To Do</option>
                <option value="drafting">Drafting</option>
                <option value="review">Review</option>
                <option value="posted">Posted</option>
              </select>
            </div>

            <button
              onClick={() => setShowNewTaskModal(true)}
              className="w-full sm:w-auto flex items-center justify-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-sm font-medium transition shadow-sm"
            >
              <Plus className="w-4 h-4" />
              <span>Add Thread Task</span>
            </button>
          </div>

          {/* Tasks Grid */}
          {loading ? (
            <div className="p-12 text-center text-slate-400 text-sm">
              <RefreshCw className="w-6 h-6 animate-spin mx-auto text-blue-600 mb-2" />
              Loading authority tasks…
            </div>
          ) : tasks.length === 0 ? (
            <div className="bg-white border border-slate-200 rounded-xl p-12 text-center text-slate-400">
              <MessageSquare className="w-10 h-10 text-slate-300 mx-auto mb-3" />
              <p className="text-base font-semibold text-slate-700">No off-site thread tasks yet</p>
              <p className="text-xs text-slate-400 mt-1 max-w-md mx-auto">
                Add target Reddit, Quora, or forum threads frequently cited by LLMs to draft value-first responses citing your brand.
              </p>
              <button
                onClick={() => setShowNewTaskModal(true)}
                className="mt-4 px-4 py-2 bg-slate-900 text-white text-xs font-medium rounded-lg hover:bg-slate-800 transition"
              >
                Add First Thread Task
              </button>
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {tasks.map((task) => (
                <div
                  key={task.id}
                  className="bg-white border border-slate-200 rounded-xl p-5 shadow-sm hover:border-slate-300 transition flex flex-col justify-between"
                >
                  <div className="space-y-3">
                    <div className="flex items-center justify-between">
                      <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold capitalize bg-slate-100 text-slate-700 border border-slate-200">
                        {task.platform}
                      </span>
                      <span
                        className={`px-2 py-0.5 rounded text-xs font-medium uppercase tracking-wider ${
                          task.status === "posted"
                            ? "bg-emerald-50 text-emerald-700 border border-emerald-200"
                            : task.status === "review"
                            ? "bg-amber-50 text-amber-700 border border-amber-200"
                            : task.status === "drafting"
                            ? "bg-blue-50 text-blue-700 border border-blue-200"
                            : "bg-slate-50 text-slate-600 border border-slate-200"
                        }`}
                      >
                        {task.status}
                      </span>
                    </div>

                    <h3 className="font-semibold text-sm text-slate-900 line-clamp-2">
                      {task.thread_title || "Discussion Thread"}
                    </h3>

                    {task.prompt_context && (
                      <p className="text-xs text-slate-500 line-clamp-2 bg-slate-50 p-2 rounded border border-slate-100">
                        <strong className="text-slate-600 font-medium">Context:</strong> {task.prompt_context}
                      </p>
                    )}

                    <div className="flex items-center gap-1 text-xs text-slate-500 truncate">
                      <ExternalLink className="w-3.5 h-3.5 flex-shrink-0 text-slate-400" />
                      <a
                        href={task.thread_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-blue-600 hover:underline truncate"
                      >
                        {task.thread_url}
                      </a>
                    </div>
                  </div>

                  <div className="mt-4 pt-3 border-t border-slate-100 flex items-center justify-between gap-2">
                    <button
                      onClick={() => handleDraftResponse(task)}
                      disabled={draftingTaskId === task.id}
                      className="flex-1 flex items-center justify-center gap-1.5 px-3 py-1.5 bg-blue-50 text-blue-700 hover:bg-blue-100 rounded-lg text-xs font-medium transition disabled:opacity-50"
                    >
                      <Sparkles className="w-3.5 h-3.5 text-blue-600" />
                      <span>{draftingTaskId === task.id ? "Drafting…" : task.response_draft ? "Re-Draft" : "AI Draft"}</span>
                    </button>

                    {task.response_draft && (
                      <button
                        onClick={() => setSelectedTask(task)}
                        className="px-3 py-1.5 bg-slate-100 hover:bg-slate-200 text-slate-800 rounded-lg text-xs font-medium transition"
                      >
                        View Draft
                      </button>
                    )}

                    <button
                      onClick={() => handleDeleteTask(task.id)}
                      className="p-1.5 text-slate-400 hover:text-rose-600 transition rounded"
                      title="Delete task"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* TAB 2: DIGITAL PR & OUTREACH */}
      {activeTab === "outreach" && (
        <div className="space-y-6">
          {/* Header Action Bar */}
          <div className="flex flex-col sm:flex-row items-center justify-between gap-4 bg-white p-4 rounded-xl border border-slate-200 shadow-sm">
            <div>
              <h2 className="text-base font-semibold text-slate-900">Prospect High-Authority Citations</h2>
              <p className="text-xs text-slate-500 mt-0.5">
                Domains frequently cited by ChatGPT, Perplexity, and Gemini where your brand is currently omitted.
              </p>
            </div>

            <button
              onClick={handleDiscoverTargets}
              disabled={discovering}
              className="w-full sm:w-auto flex items-center justify-center gap-2 px-4 py-2 bg-purple-600 hover:bg-purple-700 text-white rounded-lg text-sm font-medium transition shadow-sm disabled:opacity-50"
            >
              <Search className="w-4 h-4" />
              <span>{discovering ? "Mining AI Citations…" : "Discover Citation Targets"}</span>
            </button>
          </div>

          {/* Hard Approval Gate Reminder Banner */}
          <div className="bg-amber-50/70 border border-amber-200/80 rounded-xl p-4 flex items-start gap-3">
            <Lock className="w-5 h-5 text-amber-700 flex-shrink-0 mt-0.5" />
            <div className="text-xs text-amber-900 leading-relaxed">
              <span className="font-semibold">Strict Governance & Approval Gate Active:</span> Outbound PR messages cannot be dispatched until explicitly reviewed and approved by an authorized editor in the approval queue. This ensures zero spam and verified message quality.
            </div>
          </div>

          {/* Targets Table */}
          {loading ? (
            <div className="p-12 text-center text-slate-400 text-sm">
              <RefreshCw className="w-6 h-6 animate-spin mx-auto text-purple-600 mb-2" />
              Loading citation opportunities…
            </div>
          ) : targets.length === 0 ? (
            <div className="bg-white border border-slate-200 rounded-xl p-12 text-center text-slate-400">
              <Globe className="w-10 h-10 text-slate-300 mx-auto mb-3" />
              <p className="text-base font-semibold text-slate-700">No citation targets discovered yet</p>
              <p className="text-xs text-slate-400 mt-1 max-w-md mx-auto">
                Click &quot;Discover Citation Targets&quot; to inspect daily LLM telemetry and automatically surface candidate domains cited by competitors.
              </p>
              <button
                onClick={handleDiscoverTargets}
                className="mt-4 px-4 py-2 bg-purple-600 text-white text-xs font-medium rounded-lg hover:bg-purple-700 transition"
              >
                Discover Targets Now
              </button>
            </div>
          ) : (
            <div className="bg-white border border-slate-200 rounded-xl shadow-sm overflow-hidden">
              <table className="w-full text-left text-sm">
                <thead className="bg-slate-50 border-b border-slate-100 text-slate-500 text-xs uppercase tracking-wider">
                  <tr>
                    <th className="px-6 py-3 font-medium">Domain</th>
                    <th className="px-6 py-3 font-medium">AI Citation Freq</th>
                    <th className="px-6 py-3 font-medium">Status</th>
                    <th className="px-6 py-3 font-medium">Created</th>
                    <th className="px-6 py-3 font-medium text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {targets.map((target) => (
                    <tr key={target.id} className="hover:bg-slate-50/60 transition-colors">
                      <td className="px-6 py-4">
                        <div className="font-semibold text-slate-900 flex items-center gap-2">
                          <Globe className="w-4 h-4 text-purple-600" />
                          <span>{target.domain}</span>
                        </div>
                        {target.target_url && (
                          <a
                            href={target.target_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-xs text-blue-600 hover:underline flex items-center gap-1 mt-0.5 truncate max-w-sm"
                          >
                            {target.target_url}
                            <ExternalLink className="w-3 h-3" />
                          </a>
                        )}
                      </td>
                      <td className="px-6 py-4">
                        <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-semibold bg-purple-50 text-purple-700 border border-purple-200">
                          {target.citation_frequency ?? 1} AI citations
                        </span>
                      </td>
                      <td className="px-6 py-4">
                        <span
                          className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium uppercase tracking-wider ${
                            target.status === "won"
                              ? "bg-emerald-50 text-emerald-700 border border-emerald-200"
                              : target.status === "contacted"
                              ? "bg-blue-50 text-blue-700 border border-blue-200"
                              : target.status === "pitch_ready"
                              ? "bg-amber-50 text-amber-700 border border-amber-200"
                              : "bg-slate-100 text-slate-700"
                          }`}
                        >
                          {target.status.replace("_", " ")}
                        </span>
                      </td>
                      <td className="px-6 py-4 text-xs text-slate-500">
                        {formatDateTime(target.created_at)}
                      </td>
                      <td className="px-6 py-4 text-right space-x-2">
                        <button
                          onClick={() => handleViewTarget(target.id)}
                          className="px-3 py-1.5 bg-slate-100 hover:bg-slate-200 text-slate-800 rounded-lg text-xs font-medium transition"
                        >
                          View Target
                        </button>
                        <button
                          onClick={() => handleDraftPitch(target.id)}
                          disabled={draftingTargetId === target.id}
                          className="px-3 py-1.5 bg-purple-50 hover:bg-purple-100 text-purple-700 border border-purple-200 rounded-lg text-xs font-medium transition disabled:opacity-50 inline-flex items-center gap-1"
                        >
                          <Sparkles className="w-3 h-3 text-purple-600" />
                          <span>{draftingTargetId === target.id ? "Drafting…" : "Draft Pitch"}</span>
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* MODAL 1: Add New Third-Party Task */}
      {showNewTaskModal && (
        <div className="fixed inset-0 z-50 bg-black/40 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl max-w-md w-full p-6 shadow-xl space-y-4">
            <div className="flex items-center justify-between pb-3 border-b border-slate-100">
              <h3 className="font-semibold text-slate-900">Add Discussion Thread Task</h3>
              <button onClick={() => setShowNewTaskModal(false)} className="text-slate-400 hover:text-slate-600">
                <X className="w-5 h-5" />
              </button>
            </div>

            <form onSubmit={handleCreateTask} className="space-y-4">
              <div>
                <label className="block text-xs font-semibold text-slate-700 uppercase mb-1">Platform</label>
                <select
                  value={newTaskPlatform}
                  onChange={(e) => setNewTaskPlatform(e.target.value)}
                  className="w-full px-3 py-2 bg-white border border-slate-200 rounded-lg text-sm text-slate-800 outline-none"
                >
                  <option value="reddit">Reddit (r/technology, r/saas, etc.)</option>
                  <option value="quora">Quora</option>
                  <option value="hackernews">Hacker News</option>
                  <option value="forum">Specialized Forum / Community</option>
                </select>
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-700 uppercase mb-1">Thread URL *</label>
                <input
                  type="url"
                  required
                  placeholder="https://reddit.com/r/..."
                  value={newTaskUrl}
                  onChange={(e) => setNewTaskUrl(e.target.value)}
                  className="w-full px-3 py-2 bg-white border border-slate-200 rounded-lg text-sm text-slate-800 outline-none focus:border-blue-500"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-700 uppercase mb-1">Thread Title</label>
                <input
                  type="text"
                  placeholder="e.g. Best alternatives to Salesforce for mid-market?"
                  value={newTaskTitle}
                  onChange={(e) => setNewTaskTitle(e.target.value)}
                  className="w-full px-3 py-2 bg-white border border-slate-200 rounded-lg text-sm text-slate-800 outline-none"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-700 uppercase mb-1">Prompt Context</label>
                <textarea
                  rows={2}
                  placeholder="What user query or pain point does this conversation resolve?"
                  value={newTaskContext}
                  onChange={(e) => setNewTaskContext(e.target.value)}
                  className="w-full px-3 py-2 bg-white border border-slate-200 rounded-lg text-sm text-slate-800 outline-none resize-none"
                />
              </div>

              <div className="flex items-center justify-end gap-3 pt-3 border-t border-slate-100">
                <button
                  type="button"
                  onClick={() => setShowNewTaskModal(false)}
                  className="px-4 py-2 text-slate-600 hover:bg-slate-100 rounded-lg text-sm font-medium transition"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-sm font-medium transition"
                >
                  Create Task
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* MODAL 2: View Third-Party Task & Response Draft */}
      {selectedTask && (
        <div className="fixed inset-0 z-50 bg-black/40 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl max-w-2xl w-full p-6 shadow-xl space-y-4 max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between pb-3 border-b border-slate-100">
              <div>
                <span className="text-xs font-semibold uppercase text-slate-400">{selectedTask.platform} Thread</span>
                <h3 className="font-semibold text-slate-900 mt-0.5">{selectedTask.thread_title || "Thread Task"}</h3>
              </div>
              <button onClick={() => setSelectedTask(null)} className="text-slate-400 hover:text-slate-600">
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="space-y-4">
              <div className="bg-slate-50 p-3 rounded-lg border border-slate-200 text-xs space-y-1">
                <div className="text-slate-500">Live Thread:</div>
                <a
                  href={selectedTask.thread_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-blue-600 hover:underline flex items-center gap-1 font-mono break-all"
                >
                  {selectedTask.thread_url}
                  <ExternalLink className="w-3 h-3 flex-shrink-0" />
                </a>
              </div>

              {selectedTask.response_draft ? (
                <div>
                  <div className="flex items-center justify-between mb-2">
                    <label className="text-xs font-semibold text-slate-700 uppercase flex items-center gap-1.5">
                      <Sparkles className="w-3.5 h-3.5 text-blue-600" />
                      <span>AI Grounded Value-First Draft</span>
                    </label>
                    <button
                      onClick={() => copyToClipboard(selectedTask.response_draft!, selectedTask.id)}
                      className="text-xs text-blue-600 hover:underline flex items-center gap-1"
                    >
                      {copiedId === selectedTask.id ? <Check className="w-3.5 h-3.5" /> : <Copy className="w-3.5 h-3.5" />}
                      <span>{copiedId === selectedTask.id ? "Copied" : "Copy Draft"}</span>
                    </button>
                  </div>
                  <div className="p-4 bg-slate-900 text-slate-100 rounded-xl text-sm font-sans whitespace-pre-wrap leading-relaxed">
                    {selectedTask.response_draft}
                  </div>
                </div>
              ) : (
                <div className="text-center py-6 text-slate-400 text-sm">
                  No draft generated yet. Click &quot;AI Draft&quot; to produce an authentic, value-focused response.
                </div>
              )}

              {/* Verified Post Submission */}
              <div className="pt-3 border-t border-slate-100 space-y-3">
                <label className="block text-xs font-semibold text-slate-700 uppercase">
                  Mark as Posted (Live URL Verification)
                </label>
                <input
                  type="url"
                  placeholder="Paste comment permalink URL"
                  value={postedUrlInput}
                  onChange={(e) => setPostedUrlInput(e.target.value)}
                  className="w-full px-3 py-2 bg-white border border-slate-200 rounded-lg text-sm text-slate-800 outline-none"
                />
                <div className="flex items-center justify-end gap-3">
                  <button
                    type="button"
                    onClick={() => handleDraftResponse(selectedTask)}
                    disabled={draftingTaskId === selectedTask.id}
                    className="px-4 py-2 bg-slate-100 hover:bg-slate-200 text-slate-800 rounded-lg text-sm font-medium transition"
                  >
                    Regenerate Draft
                  </button>
                  <button
                    type="button"
                    onClick={() => handleMarkAsPosted(selectedTask)}
                    className="px-4 py-2 bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg text-sm font-medium transition flex items-center gap-1.5"
                  >
                    <CheckCircle2 className="w-4 h-4" />
                    <span>Confirm Live Post</span>
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* MODAL 3: View Target & Pitch Messages (Hard Approval Gate) */}
      {selectedTarget && (
        <div className="fixed inset-0 z-50 bg-black/40 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl max-w-2xl w-full p-6 shadow-xl space-y-5 max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between pb-3 border-b border-slate-100">
              <div className="flex items-center gap-2">
                <Globe className="w-5 h-5 text-purple-600" />
                <h3 className="font-semibold text-slate-900">{selectedTarget.domain}</h3>
                <span className="text-xs px-2 py-0.5 rounded-full bg-purple-50 text-purple-700 border border-purple-200 font-medium">
                  {selectedTarget.citation_frequency} AI Citations
                </span>
              </div>
              <button onClick={() => setSelectedTarget(null)} className="text-slate-400 hover:text-slate-600">
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* Draft Pitch Form */}
            <div className="bg-slate-50 p-4 rounded-xl border border-slate-200 space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold text-slate-700 uppercase">Generate New Personalized Pitch</span>
                <select
                  value={pitchType}
                  onChange={(e) => setPitchType(e.target.value)}
                  className="px-2.5 py-1 bg-white border border-slate-200 rounded-lg text-xs font-medium text-slate-700"
                >
                  <option value="resource_addition">Resource Addition (Recommended)</option>
                  <option value="broken_link">Broken Link Replacement</option>
                  <option value="expert_commentary">Expert Commentary</option>
                </select>
              </div>
              <button
                onClick={() => handleDraftPitch(selectedTarget.id)}
                disabled={draftingTargetId === selectedTarget.id}
                className="w-full flex items-center justify-center gap-2 px-4 py-2 bg-purple-600 hover:bg-purple-700 text-white rounded-lg text-xs font-medium transition disabled:opacity-50"
              >
                <Sparkles className="w-3.5 h-3.5" />
                <span>{draftingTargetId === selectedTarget.id ? "Synthesizing Pitch…" : "Generate Pitch Draft"}</span>
              </button>
            </div>

            {/* Outreach Messages List */}
            <div className="space-y-4">
              <h4 className="text-xs font-semibold uppercase text-slate-500 tracking-wider">
                Outreach Messages ({selectedTarget.messages?.length || 0})
              </h4>

              {(!selectedTarget.messages || selectedTarget.messages.length === 0) ? (
                <div className="text-center py-6 text-slate-400 text-xs">
                  No pitch messages generated yet for this target domain.
                </div>
              ) : (
                selectedTarget.messages.map((msg) => (
                  <div
                    key={msg.id}
                    className="border border-slate-200 rounded-xl p-4 bg-white shadow-sm space-y-3"
                  >
                    <div className="flex items-center justify-between">
                      <span className="font-semibold text-sm text-slate-900">{msg.subject}</span>
                      <div className="flex items-center gap-2">
                        {msg.status === "approved" ? (
                          <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-emerald-50 text-emerald-700 border border-emerald-200">
                            <Unlock className="w-3 h-3" /> Approved by Editor
                          </span>
                        ) : msg.status === "sent" ? (
                          <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-blue-50 text-blue-700 border border-blue-200">
                            <Send className="w-3 h-3" /> Dispatched
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-amber-50 text-amber-700 border border-amber-200">
                            <Lock className="w-3 h-3" /> Gated (Requires Approval)
                          </span>
                        )}
                      </div>
                    </div>

                    <div className="p-3 bg-slate-50 rounded-lg text-xs font-mono text-slate-700 whitespace-pre-wrap max-h-48 overflow-y-auto">
                      {msg.body}
                    </div>

                    <div className="flex items-center justify-between pt-2 border-t border-slate-100 text-xs">
                      <span className="text-slate-400">Created: {formatDateTime(msg.created_at)}</span>

                      <div className="flex items-center gap-2">
                        <button
                          onClick={() => copyToClipboard(msg.body, msg.id)}
                          className="px-2.5 py-1 text-slate-600 hover:bg-slate-100 rounded text-xs font-medium inline-flex items-center gap-1"
                        >
                          {copiedId === msg.id ? <Check className="w-3 h-3" /> : <Copy className="w-3 h-3" />}
                          <span>{copiedId === msg.id ? "Copied" : "Copy"}</span>
                        </button>

                        {/* Dispatch Button with Hard Approval Gate Check */}
                        {msg.status === "approved" && (
                          <button
                            onClick={() => handleDispatchMessage(msg.id)}
                            disabled={dispatchingId === msg.id}
                            className="px-3 py-1 bg-emerald-600 hover:bg-emerald-700 text-white rounded text-xs font-medium transition inline-flex items-center gap-1"
                          >
                            <Send className="w-3 h-3" />
                            <span>{dispatchingId === msg.id ? "Sending…" : "Dispatch Pitch"}</span>
                          </button>
                        )}

                        {msg.status !== "approved" && msg.status !== "sent" && (
                          <button
                            disabled
                            className="px-3 py-1 bg-slate-100 text-slate-400 rounded text-xs font-medium cursor-not-allowed inline-flex items-center gap-1"
                            title="Cannot dispatch: message must be approved in the approvals queue first"
                          >
                            <Lock className="w-3 h-3 text-slate-400" />
                            <span>Dispatch Locked</span>
                          </button>
                        )}
                      </div>
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
