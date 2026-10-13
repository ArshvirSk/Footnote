"use client";

import { useEffect, useState } from "react";
import {
  Activity,
  AlertCircle,
  Building2,
  Check,
  CheckCircle2,
  ChevronRight,
  Clock,
  DollarSign,
  Edit2,
  Eye,
  FileCode,
  HardDrive,
  Key,
  Layers,
  Loader2,
  Lock,
  Plus,
  RefreshCw,
  Search,
  Shield,
  ShieldAlert,
  Trash2,
  UserCheck,
  UserPlus,
  Users,
  X,
  Zap,
  Cpu,
  Database,
  Play,
  Server,
  ShieldCheck,
  ArrowUpRight,
} from "lucide-react";
import {
  AdminSpendResponse,
  AdminUser,
  AgentRunItem,
  AuditLogItem,
  Client,
  EngineStatusItem,
  ModelDriftSummary,
  ModelReleaseEventItem,
  DaemonStatus,
  adminApi,
  clients,
} from "@/lib/api";

type AdminTab = "users" | "audit" | "spend" | "caps" | "engines";

export default function AdminPage() {
  const [activeTab, setActiveTab] = useState<AdminTab>("users");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  // 1. Users state
  const [userList, setUserList] = useState<AdminUser[]>([]);
  const [allClients, setAllClients] = useState<Client[]>([]);
  const [showInviteModal, setShowInviteModal] = useState(false);
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState("editor");
  const [inviteClientIds, setInviteClientIds] = useState<string[]>([]);
  const [inviteSubmitting, setInviteSubmitting] = useState(false);

  // 2. Audit logs state
  const [auditLogs, setAuditLogs] = useState<AuditLogItem[]>([]);
  const [auditTotal, setAuditTotal] = useState(0);
  const [auditActionFilter, setAuditActionFilter] = useState("");
  const [selectedMetaLog, setSelectedMetaLog] = useState<AuditLogItem | null>(null);

  // 3. Spend & Agent runs state
  const [spendData, setSpendData] = useState<AdminSpendResponse | null>(null);
  const [agentRuns, setAgentRuns] = useState<AgentRunItem[]>([]);

  // 4. Billing caps state
  const [selectedClientForCaps, setSelectedClientForCaps] = useState<Client | null>(null);
  const [capMaxPrompts, setCapMaxPrompts] = useState("");
  const [capMaxMonthlySpend, setCapMaxMonthlySpend] = useState("");
  const [capMaxRunsPerDay, setCapMaxRunsPerDay] = useState("");
  const [capSubmitting, setCapSubmitting] = useState(false);

  // 5. Engine status state
  const [engineStatus, setEngineStatus] = useState<EngineStatusItem[]>([]);
  const [reparsing, setReparsing] = useState(false);
  const [reparseResult, setReparseResult] = useState<string | null>(null);

  // 6. M8 Automation & Hardening state
  const [modelReleases, setModelReleases] = useState<ModelReleaseEventItem[]>([]);
  const [driftSummary, setDriftSummary] = useState<ModelDriftSummary | null>(null);
  const [daemonStatus, setDaemonStatus] = useState<DaemonStatus | null>(null);
  const [tableCounts, setTableCounts] = useState<Record<string, number>>({});
  const [checkingModels, setCheckingModels] = useState(false);
  const [rebaselining, setRebaselining] = useState(false);
  const [triggeringDaemon, setTriggeringDaemon] = useState(false);
  const [pruningData, setPruningData] = useState(false);
  const [pruneResult, setPruneResult] = useState<string | null>(null);

  const loadDataForTab = async (tab: AdminTab) => {
    try {
      setLoading(true);
      setError(null);

      if (tab === "users") {
        const [users, clientList] = await Promise.all([
          adminApi.listUsers(),
          clients.list(true),
        ]);
        setUserList(users);
        setAllClients(clientList);
      } else if (tab === "audit") {
        const res = await adminApi.listAuditLogs({
          action: auditActionFilter || undefined,
          limit: 50,
        });
        setAuditLogs(res.items);
        setAuditTotal(res.total);
      } else if (tab === "spend") {
        const [spend, runs] = await Promise.all([
          adminApi.getSpend(),
          adminApi.listAgentRuns({ limit: 40 }),
        ]);
        setSpendData(spend);
        setAgentRuns(runs);
      } else if (tab === "caps") {
        const clientList = await clients.list(true);
        setAllClients(clientList);
      } else if (tab === "engines") {
        const [statuses, releases, drift, daemon, tables] = await Promise.all([
          adminApi.getEngineStatus(),
          adminApi.listModelReleases(),
          adminApi.getModelDriftSummary(),
          adminApi.getDaemonStatus(),
          adminApi.getMaintenanceTables(),
        ]);
        setEngineStatus(statuses);
        setModelReleases(releases);
        setDriftSummary(drift);
        setDaemonStatus(daemon);
        setTableCounts(tables);
      }
    } catch (err: any) {
      setError(err?.message || "Failed to load admin module data");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadDataForTab(activeTab);
  }, [activeTab]);

  // Handle User Invitation
  const handleInviteUser = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!inviteEmail) return;

    try {
      setInviteSubmitting(true);
      setError(null);
      await adminApi.createUser({
        email: inviteEmail,
        role: inviteRole,
        client_ids: inviteClientIds,
      });
      setNotice(`User ${inviteEmail} successfully created/invited with role ${inviteRole}`);
      setShowInviteModal(false);
      setInviteEmail("");
      setInviteClientIds([]);
      await loadDataForTab("users");
    } catch (err: any) {
      setError(err?.message || "Failed to create user");
    } finally {
      setInviteSubmitting(false);
    }
  };

  // Handle User Deletion
  const handleDeleteUser = async (uid: string, email: string) => {
    if (!confirm(`Are you sure you want to revoke all access for ${email}?`)) return;
    try {
      await adminApi.deleteUser(uid);
      setNotice(`Access revoked for ${email}`);
      await loadDataForTab("users");
    } catch (err: any) {
      setError(err?.message || "Failed to delete user");
    }
  };

  // Handle Caps Submission
  const handleSaveCaps = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedClientForCaps) return;

    try {
      setCapSubmitting(true);
      await adminApi.updateBillingLimits(selectedClientForCaps.id, {
        max_prompts: capMaxPrompts ? parseInt(capMaxPrompts, 10) : undefined,
        max_monthly_spend_usd: capMaxMonthlySpend ? parseFloat(capMaxMonthlySpend) : undefined,
        max_runs_per_day: capMaxRunsPerDay ? parseInt(capMaxRunsPerDay, 10) : undefined,
      });
      setNotice(`Safety caps updated for ${selectedClientForCaps.name}`);
      setSelectedClientForCaps(null);
      await loadDataForTab("caps");
    } catch (err: any) {
      setError(err?.message || "Failed to update safety caps");
    } finally {
      setCapSubmitting(false);
    }
  };

  // Handle Trigger Reparse
  const handleTriggerReparse = async () => {
    try {
      setReparsing(true);
      const res = await adminApi.triggerReparse();
      setReparseResult(`Queued re-parsing of ${res.count} answer items.`);
      setNotice(`Engine answers re-parsing dispatched (${res.count} records)`);
    } catch (err: any) {
      setError(err?.message || "Failed to dispatch re-parse");
    } finally {
      setReparsing(false);
    }
  };

  // M8: Model check handler
  const handleCheckModels = async () => {
    try {
      setCheckingModels(true);
      setError(null);
      const res = await adminApi.checkModelReleases();
      setNotice(
        res.newly_detected.length > 0
          ? `Discovered ${res.newly_detected.length} new model release(s)!`
          : "Engine scan complete: all models match baseline registry."
      );
      await loadDataForTab("engines");
    } catch (err: any) {
      setError(err?.message || "Failed to scan model releases");
    } finally {
      setCheckingModels(false);
    }
  };

  // M8: Re-baseline prompts handler
  const handleRebaseline = async (engine?: string, releaseId?: string) => {
    try {
      setRebaselining(true);
      setError(null);
      let res;
      if (releaseId) {
        res = await adminApi.rebaselineForRelease(releaseId);
      } else {
        res = await adminApi.rebaselinePrompts({ engine });
      }
      setNotice(`Successfully calibrated and re-baselined ${res.updated_prompts} prompt(s).`);
      await loadDataForTab("engines");
    } catch (err: any) {
      setError(err?.message || "Failed to re-baseline prompts");
    } finally {
      setRebaselining(false);
    }
  };

  // M8: Trigger daemon cycle handler
  const handleTriggerDaemon = async () => {
    try {
      setTriggeringDaemon(true);
      setError(null);
      const res = await adminApi.triggerDaemon();
      setNotice(`Background daemon completed cycle: ${Object.keys(res.tasks).length} tasks executed.`);
      await loadDataForTab("engines");
    } catch (err: any) {
      setError(err?.message || "Failed to run background daemon cycle");
    } finally {
      setTriggeringDaemon(false);
    }
  };

  // M8: Prune maintenance data handler
  const handlePruneData = async () => {
    try {
      setPruningData(true);
      setError(null);
      const res = await adminApi.pruneMaintenanceData({
        failed_answers_days: 30,
        historical_answers_days: 365,
        agent_runs_days: 90,
        audit_logs_days: 180,
      });
      setPruneResult(
        `Pruned ${res.total_pruned} total records (${res.pruned_failed_answers} failed answers, ${res.pruned_agent_runs} agent runs, ${res.pruned_audit_logs} audit logs).`
      );
      setNotice(`Database maintenance completed: ${res.total_pruned} rows cleaned up.`);
      await loadDataForTab("engines");
    } catch (err: any) {
      setError(err?.message || "Failed to prune database records");
    } finally {
      setPruningData(false);
    }
  };

  const isPortalRole = inviteRole === "client_approver" || inviteRole === "client_viewer";

  return (
    <div className="space-y-6 max-w-7xl mx-auto pb-16 animate-in fade-in duration-300">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-slate-200 pb-5">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-2xl font-bold tracking-tight text-slate-900">
              Enterprise Admin Console
            </h1>
            <span className="bg-slate-900 text-white text-[11px] font-bold px-2 py-0.5 rounded uppercase tracking-wider">
              Governance
            </span>
          </div>
          <p className="text-sm text-slate-500 mt-1">
            Role-based access control, queryable audit trail, LLM cost telemetry, and client safety limits.
          </p>
        </div>

        <button
          onClick={() => loadDataForTab(activeTab)}
          disabled={loading}
          className="inline-flex items-center px-3.5 py-2 border border-slate-200 rounded-xl text-xs font-semibold text-slate-700 bg-white hover:bg-slate-50 shadow-2xs transition disabled:opacity-50"
        >
          <RefreshCw className={`w-3.5 h-3.5 mr-1.5 ${loading ? "animate-spin text-slate-400" : "text-slate-600"}`} />
          Refresh Console
        </button>
      </div>

      {/* Notices & Errors */}
      {notice && (
        <div className="bg-emerald-50 border border-emerald-200 text-emerald-800 px-4 py-3 rounded-xl text-xs flex items-center justify-between shadow-2xs animate-in fade-in">
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
        <div className="bg-rose-50 border border-rose-200 text-rose-800 px-4 py-3 rounded-xl text-xs flex items-center justify-between shadow-2xs animate-in fade-in">
          <div className="flex items-center gap-2">
            <AlertCircle className="w-4 h-4 text-rose-600 flex-shrink-0" />
            <span>{error}</span>
          </div>
          <button onClick={() => setError(null)} className="text-rose-600 hover:text-rose-800">
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      )}

      {/* Admin Tabs */}
      <div className="flex items-center gap-2 border-b border-slate-200 text-xs font-semibold">
        <button
          onClick={() => setActiveTab("users")}
          className={`px-4 py-3 border-b-2 flex items-center gap-2 transition ${
            activeTab === "users"
              ? "border-slate-900 text-slate-900"
              : "border-transparent text-slate-500 hover:text-slate-800"
          }`}
        >
          <Users className="w-4 h-4" /> Users &amp; Permissions
        </button>
        <button
          onClick={() => setActiveTab("audit")}
          className={`px-4 py-3 border-b-2 flex items-center gap-2 transition ${
            activeTab === "audit"
              ? "border-slate-900 text-slate-900"
              : "border-transparent text-slate-500 hover:text-slate-800"
          }`}
        >
          <Activity className="w-4 h-4" /> Audit Trail ({auditTotal || "Live"})
        </button>
        <button
          onClick={() => setActiveTab("spend")}
          className={`px-4 py-3 border-b-2 flex items-center gap-2 transition ${
            activeTab === "spend"
              ? "border-slate-900 text-slate-900"
              : "border-transparent text-slate-500 hover:text-slate-800"
          }`}
        >
          <DollarSign className="w-4 h-4" /> Agent Runs &amp; LLM Spend
        </button>
        <button
          onClick={() => setActiveTab("caps")}
          className={`px-4 py-3 border-b-2 flex items-center gap-2 transition ${
            activeTab === "caps"
              ? "border-slate-900 text-slate-900"
              : "border-transparent text-slate-500 hover:text-slate-800"
          }`}
        >
          <Shield className="w-4 h-4" /> Client Safety Caps
        </button>
        <button
          onClick={() => setActiveTab("engines")}
          className={`px-4 py-3 border-b-2 flex items-center gap-2 transition ${
            activeTab === "engines"
              ? "border-slate-900 text-slate-900"
              : "border-transparent text-slate-500 hover:text-slate-800"
          }`}
        >
          <Zap className="w-4 h-4" /> System &amp; Engine Status
        </button>
      </div>

      {/* ─────────────────────────────────────────────────────────────────── */}
      {/* TAB 1: USERS & PERMISSIONS (RBAC) */}
      {/* ─────────────────────────────────────────────────────────────────── */}
      {activeTab === "users" && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-base font-bold text-slate-900">Team &amp; Client Access Roster</h2>
              <p className="text-xs text-slate-500">
                Manage organization operators (`owner`, `admin`, `strategist`, `editor`) and client stakeholders (`client_approver`, `client_viewer`).
              </p>
            </div>
            <button
              onClick={() => setShowInviteModal(true)}
              className="inline-flex items-center px-4 py-2 bg-slate-900 hover:bg-slate-800 text-white text-xs font-semibold rounded-xl shadow-2xs transition"
            >
              <UserPlus className="w-3.5 h-3.5 mr-1.5" />
              Add / Invite User
            </button>
          </div>

          <div className="bg-white border border-slate-200 rounded-2xl overflow-hidden shadow-2xs">
            <table className="w-full text-left text-xs text-slate-600">
              <thead className="bg-slate-50 border-b border-slate-200 text-slate-900 font-bold uppercase tracking-wider text-[11px]">
                <tr>
                  <th className="py-3.5 px-4">User Email</th>
                  <th className="py-3.5 px-4">Assigned Role</th>
                  <th className="py-3.5 px-4">Access Scope</th>
                  <th className="py-3.5 px-4">Created</th>
                  <th className="py-3.5 px-4 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {userList.map((u) => {
                  const isClient = u.role === "client_approver" || u.role === "client_viewer";

                  return (
                    <tr key={u.user_id} className="hover:bg-slate-50/70 transition">
                      <td className="py-3.5 px-4 font-semibold text-slate-900">
                        {u.email}
                      </td>
                      <td className="py-3.5 px-4">
                        <span className={`inline-flex items-center px-2 py-0.5 rounded text-[11px] font-bold uppercase tracking-wider ${
                          u.role === "owner" || u.role === "admin"
                            ? "bg-purple-100 text-purple-800"
                            : u.role === "client_approver"
                            ? "bg-emerald-100 text-emerald-800"
                            : u.role === "client_viewer"
                            ? "bg-slate-100 text-slate-700"
                            : "bg-blue-100 text-blue-800"
                        }`}>
                          {u.role.replace("_", " ")}
                        </span>
                      </td>
                      <td className="py-3.5 px-4">
                        {isClient ? (
                          <div className="flex flex-wrap gap-1">
                            {u.clients.length > 0 ? (
                              u.clients.map((c) => (
                                <span
                                  key={c.id}
                                  className="inline-flex items-center px-2 py-0.5 bg-slate-100 rounded text-[10px] text-slate-700 font-medium"
                                >
                                  {c.name}
                                </span>
                              ))
                            ) : (
                              <span className="text-slate-400 italic">No clients assigned</span>
                            )}
                          </div>
                        ) : (
                          <span className="text-slate-600 font-medium flex items-center gap-1">
                            <Building2 className="w-3 h-3 text-slate-400" /> All Agency Clients
                          </span>
                        )}
                      </td>
                      <td className="py-3.5 px-4 text-slate-400">
                        {u.created_at ? new Date(u.created_at).toLocaleDateString() : "—"}
                      </td>
                      <td className="py-3.5 px-4 text-right">
                        <button
                          onClick={() => handleDeleteUser(u.user_id, u.email)}
                          className="text-rose-600 hover:text-rose-800 p-1 hover:bg-rose-50 rounded"
                          title="Revoke access"
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ─────────────────────────────────────────────────────────────────── */}
      {/* TAB 2: AUDIT TRAIL */}
      {/* ─────────────────────────────────────────────────────────────────── */}
      {activeTab === "audit" && (
        <div className="space-y-4">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
            <div>
              <h2 className="text-base font-bold text-slate-900">Immutable Audit Trail</h2>
              <p className="text-xs text-slate-500">
                Cryptographically verifiable event log recording user actions, approvals, publishing, and system re-configurations.
              </p>
            </div>
            <div className="flex items-center gap-2">
              <input
                type="text"
                placeholder="Filter by action (e.g. user, approval)…"
                value={auditActionFilter}
                onChange={(e) => setAuditActionFilter(e.target.value)}
                className="px-3 py-1.5 bg-white border border-slate-200 rounded-lg text-xs w-60 focus:outline-none focus:ring-1 focus:ring-slate-900"
              />
              <button
                onClick={() => loadDataForTab("audit")}
                className="px-3 py-1.5 bg-slate-900 text-white rounded-lg text-xs font-semibold hover:bg-slate-800"
              >
                Filter
              </button>
            </div>
          </div>

          <div className="bg-white border border-slate-200 rounded-2xl overflow-hidden shadow-2xs">
            <table className="w-full text-left text-xs text-slate-600">
              <thead className="bg-slate-50 border-b border-slate-200 text-slate-900 font-bold uppercase tracking-wider text-[11px]">
                <tr>
                  <th className="py-3.5 px-4">Event ID</th>
                  <th className="py-3.5 px-4">Timestamp</th>
                  <th className="py-3.5 px-4">Actor</th>
                  <th className="py-3.5 px-4">Action</th>
                  <th className="py-3.5 px-4">Entity</th>
                  <th className="py-3.5 px-4 text-right">Details</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {auditLogs.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="py-8 text-center text-slate-400">
                      No audit events recorded matching current filters.
                    </td>
                  </tr>
                ) : (
                  auditLogs.map((log) => (
                    <tr key={log.id} className="hover:bg-slate-50/70 transition">
                      <td className="py-3 px-4 font-mono text-[11px] text-slate-400">
                        #{log.id}
                      </td>
                      <td className="py-3 px-4 whitespace-nowrap text-slate-500">
                        {new Date(log.at).toLocaleString()}
                      </td>
                      <td className="py-3 px-4 font-semibold text-slate-900">
                        {log.actor_email || (log.actor ? `${log.actor.slice(0, 8)}…` : "System")}
                      </td>
                      <td className="py-3 px-4">
                        <span className="font-mono text-[11px] px-2 py-0.5 rounded bg-slate-100 text-slate-800 font-semibold border border-slate-200">
                          {log.action}
                        </span>
                      </td>
                      <td className="py-3 px-4 capitalize text-slate-700">
                        {log.entity}
                      </td>
                      <td className="py-3 px-4 text-right">
                        <button
                          onClick={() => setSelectedMetaLog(log)}
                          className="text-xs text-blue-600 hover:text-blue-800 font-semibold underline"
                        >
                          View Meta
                        </button>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ─────────────────────────────────────────────────────────────────── */}
      {/* TAB 3: SPEND & AGENT RUNS */}
      {/* ─────────────────────────────────────────────────────────────────── */}
      {activeTab === "spend" && spendData && (
        <div className="space-y-6">
          {/* 4 Summary Cards */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            <div className="bg-white p-5 rounded-2xl border border-slate-200 shadow-2xs">
              <span className="text-xs font-semibold text-slate-500 uppercase">Total Spend (All Time)</span>
              <div className="text-3xl font-extrabold text-slate-900 mt-2">
                ${spendData.total_spend_usd.toFixed(2)}
              </div>
              <p className="text-[11px] text-slate-400 mt-1">Across all frontier LLMs</p>
            </div>

            <div className="bg-white p-5 rounded-2xl border border-slate-200 shadow-2xs">
              <span className="text-xs font-semibold text-slate-500 uppercase">30-Day Monthly Run-rate</span>
              <div className="text-3xl font-extrabold text-emerald-600 mt-2">
                ${spendData.spend_30d_usd.toFixed(2)}
              </div>
              <p className="text-[11px] text-slate-400 mt-1">Current monthly consumption</p>
            </div>

            <div className="bg-white p-5 rounded-2xl border border-slate-200 shadow-2xs">
              <span className="text-xs font-semibold text-slate-500 uppercase">Tokens Processed</span>
              <div className="text-3xl font-extrabold text-slate-900 mt-2">
                {((spendData.total_tokens_in + spendData.total_tokens_out) / 1000).toFixed(1)}k
              </div>
              <p className="text-[11px] text-slate-400 mt-1">
                {spendData.total_tokens_in.toLocaleString()} in / {spendData.total_tokens_out.toLocaleString()} out
              </p>
            </div>

            <div className="bg-white p-5 rounded-2xl border border-slate-200 shadow-2xs">
              <span className="text-xs font-semibold text-slate-500 uppercase">Total Agent Runs</span>
              <div className="text-3xl font-extrabold text-slate-900 mt-2">
                {spendData.total_runs}
              </div>
              <p className="text-[11px] text-slate-400 mt-1">Research, drafting, auditing</p>
            </div>
          </div>

          {/* Breakdown: By Agent & By Model */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div className="bg-white border border-slate-200 rounded-2xl p-6 shadow-2xs space-y-4">
              <h3 className="text-sm font-bold text-slate-900 flex items-center gap-2">
                <Layers className="w-4 h-4 text-slate-600" />
                Cost Breakdown by Agent Specialty
              </h3>
              <div className="space-y-2">
                {spendData.by_agent.map((ag) => (
                  <div
                    key={ag.agent}
                    className="flex items-center justify-between p-3 bg-slate-50 rounded-xl border border-slate-200/80 text-xs"
                  >
                    <div>
                      <span className="font-bold text-slate-900 capitalize">{ag.agent} Agent</span>
                      <p className="text-[11px] text-slate-400">{ag.runs} runs &bull; {ag.tokens.toLocaleString()} tokens</p>
                    </div>
                    <span className="font-mono font-bold text-slate-800">${ag.spend_usd.toFixed(4)}</span>
                  </div>
                ))}
              </div>
            </div>

            <div className="bg-white border border-slate-200 rounded-2xl p-6 shadow-2xs space-y-4">
              <h3 className="text-sm font-bold text-slate-900 flex items-center gap-2">
                <Zap className="w-4 h-4 text-slate-600" />
                Spend by Model
              </h3>
              <div className="space-y-2">
                {spendData.by_model.map((md) => (
                  <div
                    key={md.model}
                    className="flex items-center justify-between p-3 bg-slate-50 rounded-xl border border-slate-200/80 text-xs"
                  >
                    <div>
                      <span className="font-mono font-bold text-slate-900">{md.model}</span>
                      <p className="text-[11px] text-slate-400">{md.runs} executions</p>
                    </div>
                    <span className="font-mono font-bold text-slate-800">${md.spend_usd.toFixed(4)}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Execution History Table */}
          <div className="bg-white border border-slate-200 rounded-2xl overflow-hidden shadow-2xs space-y-2">
            <div className="px-6 py-4 border-b border-slate-100 flex items-center justify-between">
              <h3 className="text-sm font-bold text-slate-900">Recent Agent Executions</h3>
              <span className="text-xs text-slate-400">Latest 40 runs</span>
            </div>
            <table className="w-full text-left text-xs text-slate-600">
              <thead className="bg-slate-50 border-b border-slate-200 text-slate-900 font-bold uppercase tracking-wider text-[11px]">
                <tr>
                  <th className="py-3 px-4">Agent</th>
                  <th className="py-3 px-4">Client</th>
                  <th className="py-3 px-4">Model</th>
                  <th className="py-3 px-4">Tokens</th>
                  <th className="py-3 px-4">Cost</th>
                  <th className="py-3 px-4">Status</th>
                  <th className="py-3 px-4">Started</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {agentRuns.map((r) => (
                  <tr key={r.id} className="hover:bg-slate-50/70 transition">
                    <td className="py-3 px-4 font-bold text-slate-900 capitalize">
                      {r.agent}
                    </td>
                    <td className="py-3 px-4 text-slate-700">
                      {r.client_name || "—"}
                    </td>
                    <td className="py-3 px-4 font-mono text-[11px] text-slate-500">
                      {r.model || "default"}
                    </td>
                    <td className="py-3 px-4 text-slate-600">
                      {(r.tokens_in || 0) + (r.tokens_out || 0)}
                    </td>
                    <td className="py-3 px-4 font-mono text-slate-800">
                      ${(r.cost_usd || 0).toFixed(4)}
                    </td>
                    <td className="py-3 px-4">
                      <span className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase ${
                        r.status === "succeeded"
                          ? "bg-emerald-100 text-emerald-800"
                          : r.status === "failed"
                          ? "bg-rose-100 text-rose-800"
                          : "bg-amber-100 text-amber-800"
                      }`}>
                        {r.status}
                      </span>
                    </td>
                    <td className="py-3 px-4 text-slate-400">
                      {r.started_at ? new Date(r.started_at).toLocaleTimeString() : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ─────────────────────────────────────────────────────────────────── */}
      {/* TAB 4: CLIENT SAFETY CAPS */}
      {/* ─────────────────────────────────────────────────────────────────── */}
      {activeTab === "caps" && (
        <div className="space-y-4">
          <div>
            <h2 className="text-base font-bold text-slate-900">Client Safety Caps &amp; Billing Limits</h2>
            <p className="text-xs text-slate-500">
              Configure hard bounds per brand: max prompts tracked, monthly spend cap ($USD), and daily run throttling.
            </p>
          </div>

          <div className="bg-white border border-slate-200 rounded-2xl overflow-hidden shadow-2xs">
            <table className="w-full text-left text-xs text-slate-600">
              <thead className="bg-slate-50 border-b border-slate-200 text-slate-900 font-bold uppercase tracking-wider text-[11px]">
                <tr>
                  <th className="py-3.5 px-4">Client Brand</th>
                  <th className="py-3.5 px-4">Primary Domain</th>
                  <th className="py-3.5 px-4">Monthly Spend Cap</th>
                  <th className="py-3.5 px-4">Max Prompts</th>
                  <th className="py-3.5 px-4">Daily Run Limit</th>
                  <th className="py-3.5 px-4 text-right">Configure</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {allClients.map((c) => (
                  <tr key={c.id} className="hover:bg-slate-50/70 transition">
                    <td className="py-3.5 px-4 font-bold text-slate-900">
                      {c.name}
                    </td>
                    <td className="py-3.5 px-4 font-mono text-slate-600">
                      {c.primary_domain}
                    </td>
                    <td className="py-3.5 px-4 font-medium text-slate-800">
                      $500.00 / mo
                    </td>
                    <td className="py-3.5 px-4 text-slate-600">
                      1,000 Prompts
                    </td>
                    <td className="py-3.5 px-4 text-slate-600">
                      50 Runs / day
                    </td>
                    <td className="py-3.5 px-4 text-right">
                      <button
                        onClick={() => {
                          setSelectedClientForCaps(c);
                          setCapMaxPrompts("1000");
                          setCapMaxMonthlySpend("500");
                          setCapMaxRunsPerDay("50");
                        }}
                        className="inline-flex items-center px-3 py-1 bg-slate-100 hover:bg-slate-200 text-slate-800 rounded-lg text-xs font-semibold transition"
                      >
                        <Edit2 className="w-3 h-3 mr-1" /> Edit Caps
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ─────────────────────────────────────────────────────────────────── */}
      {/* TAB 5: SYSTEM & ENGINES */}
      {/* ─────────────────────────────────────────────────────────────────── */}
      {activeTab === "engines" && (
        <div className="space-y-6">
          <div className="bg-white border border-slate-200 rounded-2xl p-6 md:p-8 shadow-2xs space-y-4">
            <h3 className="text-base font-bold text-slate-900 flex items-center gap-2">
              <Key className="w-5 h-5 text-slate-500" />
              Frontier Engine Provider Keys
            </h3>
            <p className="text-xs text-slate-500 leading-relaxed">
              Realtime telemetry from application settings. When keys are configured, workers collect real responses directly from the frontier model.
            </p>

            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 pt-2">
              {engineStatus.map((eng) => (
                <div
                  key={eng.engine}
                  className="p-4 bg-slate-50 border border-slate-200/80 rounded-xl space-y-2"
                >
                  <div className="flex items-center justify-between">
                    <span className="font-bold text-slate-900 uppercase tracking-wide text-xs">
                      {eng.engine}
                    </span>
                    <span className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase ${
                      eng.configured
                        ? "bg-emerald-100 text-emerald-800"
                        : "bg-slate-200 text-slate-600"
                    }`}>
                      {eng.configured ? "Configured" : "Not Set"}
                    </span>
                  </div>
                  <div className="text-xs text-slate-500">
                    Model: <span className="font-mono text-slate-800 font-semibold">{eng.model}</span>
                  </div>
                  <div className="text-[11px] font-mono text-slate-400 bg-white p-2 rounded border border-slate-200">
                    {eng.key_preview}
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Re-parse Tool */}
          <div className="bg-white border border-slate-200 rounded-2xl p-6 md:p-8 shadow-2xs flex flex-col md:flex-row md:items-center justify-between gap-6">
            <div className="space-y-1">
              <h3 className="text-base font-bold text-slate-900 flex items-center gap-2">
                <RefreshCw className="w-4 h-4 text-slate-600" />
                Trigger Answer Re-Parsing
              </h3>
              <p className="text-xs text-slate-500 max-w-xl">
                Re-evaluates collected raw responses against updated entity aliases and judges without incurring fresh LLM token costs.
              </p>
              {reparseResult && (
                <p className="text-xs text-emerald-700 font-medium pt-1">{reparseResult}</p>
              )}
            </div>

            <button
              onClick={handleTriggerReparse}
              disabled={reparsing}
              className="inline-flex items-center px-4 py-2 bg-slate-900 hover:bg-slate-800 text-white rounded-xl text-xs font-semibold shadow-2xs transition disabled:opacity-50 flex-shrink-0"
            >
              {reparsing ? <Loader2 className="w-3.5 h-3.5 animate-spin mr-1.5" /> : <RefreshCw className="w-3.5 h-3.5 mr-1.5" />}
              Dispatch Re-parse
            </button>
          </div>

          {/* ───────────────────────────────────────────────────────────── */}
          {/* M8: Model Release Drift Detection & Re-baselining */}
          {/* ───────────────────────────────────────────────────────────── */}
          <div className="bg-white border border-slate-200 rounded-2xl p-6 md:p-8 shadow-2xs space-y-5">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
              <div>
                <h3 className="text-base font-bold text-slate-900 flex items-center gap-2">
                  <Cpu className="w-5 h-5 text-slate-500" />
                  Model Release Detection &amp; Version Drift
                </h3>
                <p className="text-xs text-slate-500">
                  Monitors AI engine base-model upgrades. When models change, prompts can be calibrated and re-baselined.
                </p>
              </div>

              <div className="flex items-center gap-2">
                <button
                  onClick={handleCheckModels}
                  disabled={checkingModels}
                  className="inline-flex items-center px-3.5 py-1.5 bg-slate-100 hover:bg-slate-200 text-slate-800 rounded-xl text-xs font-semibold transition disabled:opacity-50"
                >
                  {checkingModels ? <Loader2 className="w-3.5 h-3.5 animate-spin mr-1.5" /> : <RefreshCw className="w-3.5 h-3.5 mr-1.5" />}
                  Scan Engine Releases
                </button>
                <button
                  onClick={() => handleRebaseline()}
                  disabled={rebaselining}
                  className="inline-flex items-center px-3.5 py-1.5 bg-slate-900 hover:bg-slate-800 text-white rounded-xl text-xs font-semibold transition disabled:opacity-50"
                >
                  {rebaselining ? <Loader2 className="w-3.5 h-3.5 animate-spin mr-1.5" /> : <ShieldCheck className="w-3.5 h-3.5 mr-1.5" />}
                  Re-baseline All Prompts
                </button>
              </div>
            </div>

            {/* Drift Telemetry Cards */}
            {driftSummary && (
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                <div className="p-4 bg-slate-50 border border-slate-200/80 rounded-xl space-y-1">
                  <div className="text-[11px] font-medium text-slate-500">Active Prompts Monitored</div>
                  <div className="text-xl font-bold text-slate-900">{driftSummary.total_active_prompts}</div>
                  <div className="text-[11px] text-slate-500">
                    <span className="font-semibold text-emerald-600">{driftSummary.baselined_prompts}</span> baselined
                    {driftSummary.never_baselined_prompts > 0 && (
                      <span className="text-amber-600 font-semibold ml-1.5">
                        ({driftSummary.never_baselined_prompts} uncalibrated)
                      </span>
                    )}
                  </div>
                </div>

                <div className="p-4 bg-slate-50 border border-slate-200/80 rounded-xl space-y-1">
                  <div className="text-[11px] font-medium text-slate-500">Engine Releases Detected</div>
                  <div className="text-xl font-bold text-slate-900">{modelReleases.length}</div>
                  <div className="text-[11px] text-slate-500">
                    {driftSummary.recent_releases_count} new in past 7 days
                  </div>
                </div>

                <div className="p-4 bg-slate-50 border border-slate-200/80 rounded-xl space-y-1">
                  <div className="text-[11px] font-medium text-slate-500">Drift Baseline Status</div>
                  <div className="text-xl font-bold">
                    {driftSummary.has_unbaselined_drift ? (
                      <span className="text-amber-600">Re-baseline Needed</span>
                    ) : (
                      <span className="text-emerald-600">Fully Calibrated</span>
                    )}
                  </div>
                  <div className="text-[11px] text-slate-500">
                    {driftSummary.latest_release
                      ? `Latest: ${driftSummary.latest_release.engine} (${driftSummary.latest_release.model_label})`
                      : "No version drift detected"}
                  </div>
                </div>
              </div>
            )}

            {/* Model Releases Table */}
            <div className="border border-slate-200 rounded-xl overflow-hidden">
              <table className="w-full text-left text-xs">
                <thead className="bg-slate-50 border-b border-slate-200 text-slate-500 uppercase tracking-wider font-semibold text-[10px]">
                  <tr>
                    <th className="px-4 py-3">Engine</th>
                    <th className="px-4 py-3">Detected Model Label</th>
                    <th className="px-4 py-3">Detected At</th>
                    <th className="px-4 py-3">Source &amp; Release Notes</th>
                    <th className="px-4 py-3 text-right">Action</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 font-medium text-slate-700">
                  {modelReleases.length === 0 ? (
                    <tr>
                      <td colSpan={5} className="px-4 py-6 text-center text-slate-400">
                        No model release events recorded yet. Click &quot;Scan Engine Releases&quot; above to initialize.
                      </td>
                    </tr>
                  ) : (
                    modelReleases.map((rel) => (
                      <tr key={rel.id} className="hover:bg-slate-50/50">
                        <td className="px-4 py-3 font-bold text-slate-900 uppercase">{rel.engine}</td>
                        <td className="px-4 py-3 font-mono text-slate-900">{rel.model_label}</td>
                        <td className="px-4 py-3 text-slate-500">
                          {rel.detected_at ? new Date(rel.detected_at).toLocaleDateString() : "Baseline"}
                        </td>
                        <td className="px-4 py-3">
                          {rel.source_url ? (
                            <a
                              href={rel.source_url}
                              target="_blank"
                              rel="noreferrer"
                              className="text-slate-600 hover:text-slate-900 underline inline-flex items-center gap-1"
                            >
                              View Notes <ArrowUpRight className="w-3 h-3" />
                            </a>
                          ) : (
                            <span className="text-slate-400">Official Catalog</span>
                          )}
                        </td>
                        <td className="px-4 py-3 text-right">
                          <button
                            onClick={() => handleRebaseline(rel.engine, rel.id)}
                            className="px-2.5 py-1 text-[11px] font-semibold bg-slate-100 hover:bg-slate-200 text-slate-800 rounded-lg transition"
                          >
                            Re-baseline {rel.engine}
                          </button>
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>

          {/* ───────────────────────────────────────────────────────────── */}
          {/* M8: Background Worker Daemon Telemetry */}
          {/* ───────────────────────────────────────────────────────────── */}
          <div className="bg-white border border-slate-200 rounded-2xl p-6 md:p-8 shadow-2xs space-y-5">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
              <div>
                <h3 className="text-base font-bold text-slate-900 flex items-center gap-2">
                  <Server className="w-5 h-5 text-slate-500" />
                  Background Worker Daemon
                </h3>
                <p className="text-xs text-slate-500">
                  Autonomous task runner for prompt collection, rollups, content decay scans, and data retention.
                </p>
              </div>

              <div className="flex items-center gap-3">
                {daemonStatus && (
                  <span className={`px-2.5 py-1 rounded-full text-xs font-semibold flex items-center gap-1.5 ${
                    daemonStatus.status === "active"
                      ? "bg-emerald-50 text-emerald-700 border border-emerald-200"
                      : "bg-slate-100 text-slate-600"
                  }`}>
                    <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
                    Daemon {daemonStatus.status === "active" ? "Active" : "Idle"}
                  </span>
                )}
                <button
                  onClick={handleTriggerDaemon}
                  disabled={triggeringDaemon}
                  className="inline-flex items-center px-3.5 py-1.5 bg-slate-900 hover:bg-slate-800 text-white rounded-xl text-xs font-semibold transition disabled:opacity-50"
                >
                  {triggeringDaemon ? <Loader2 className="w-3.5 h-3.5 animate-spin mr-1.5" /> : <Play className="w-3.5 h-3.5 mr-1.5" />}
                  Run Maintenance Cycle
                </button>
              </div>
            </div>

            {/* Daemon Telemetry Cards */}
            {daemonStatus && (
              <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
                {[
                  { key: "daily_batch", label: "Daily Batch", desc: "Nightly collection" },
                  { key: "nightly_rollup", label: "Metric Rollup", desc: "Daily metrics & gaps" },
                  { key: "decay_scan", label: "Decay Scanner", desc: "Citation loss checks" },
                  { key: "model_release_check", label: "Model Drift", desc: "Provider catalog scan" },
                  { key: "retention_prune", label: "Data Retention", desc: "Clean expired logs" },
                ].map((task) => (
                  <div key={task.key} className="p-3 bg-slate-50 border border-slate-200/80 rounded-xl space-y-1">
                    <div className="text-[10px] uppercase font-bold text-slate-500">{task.label}</div>
                    <div className="text-lg font-bold text-slate-900">
                      {daemonStatus.task_counts[task.key] || 0}
                      <span className="text-[10px] font-normal text-slate-400 ml-1">runs</span>
                    </div>
                    <div className="text-[10px] text-slate-400 truncate">
                      {daemonStatus.last_run[task.key]
                        ? new Date(daemonStatus.last_run[task.key]).toLocaleTimeString()
                        : "Scheduled"}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* ───────────────────────────────────────────────────────────── */}
          {/* M8: Database Retention & Hygiene */}
          {/* ───────────────────────────────────────────────────────────── */}
          <div className="bg-white border border-slate-200 rounded-2xl p-6 md:p-8 shadow-2xs space-y-5">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
              <div>
                <h3 className="text-base font-bold text-slate-900 flex items-center gap-2">
                  <Database className="w-5 h-5 text-slate-500" />
                  Database Hygiene &amp; Data Retention
                </h3>
                <p className="text-xs text-slate-500">
                  Prunes expired error logs, failed runs, and stale historical answers beyond retention thresholds while preserving aggregated metrics.
                </p>
              </div>

              <button
                onClick={handlePruneData}
                disabled={pruningData}
                className="inline-flex items-center px-3.5 py-1.5 bg-rose-50 hover:bg-rose-100 text-rose-700 border border-rose-200 rounded-xl text-xs font-semibold transition disabled:opacity-50"
              >
                {pruningData ? <Loader2 className="w-3.5 h-3.5 animate-spin mr-1.5" /> : <Trash2 className="w-3.5 h-3.5 mr-1.5" />}
                Prune Expired Data
              </button>
            </div>

            {pruneResult && (
              <div className="p-3 bg-emerald-50 border border-emerald-200 text-emerald-800 rounded-xl text-xs font-medium">
                {pruneResult}
              </div>
            )}

            {/* Live table count badges */}
            <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-3">
              {Object.entries(tableCounts).map(([table, count]) => (
                <div key={table} className="p-3 bg-slate-50 border border-slate-200/80 rounded-xl space-y-0.5">
                  <div className="text-[10px] font-mono text-slate-500 truncate">{table}</div>
                  <div className="text-base font-bold text-slate-900">{count}</div>
                  <div className="text-[10px] text-slate-400">rows</div>
                </div>
              ))}
            </div>

            <div className="text-[11px] text-slate-400 border-t border-slate-100 pt-3">
              Retention policies: Failed/mock answers (30 days) &bull; Historical answers (365 days) &bull; Agent runs (90 days) &bull; Audit trail logs (180 days).
            </div>
          </div>
        </div>
      )}

      {/* ─────────────────────────────────────────────────────────────────── */}
      {/* MODAL: Add / Invite User */}
      {/* ─────────────────────────────────────────────────────────────────── */}
      {showInviteModal && (
        <div className="fixed inset-0 bg-slate-900/40 backdrop-blur-xs flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-2xl max-w-md w-full border border-slate-200 shadow-xl overflow-hidden animate-in zoom-in-95 duration-200">
            <div className="px-6 py-4 border-b border-slate-100 flex items-center justify-between">
              <h3 className="text-base font-bold text-slate-900">Add / Invite New User</h3>
              <button onClick={() => setShowInviteModal(false)} className="text-slate-400 hover:text-slate-600">
                <X className="w-5 h-5" />
              </button>
            </div>

            <form onSubmit={handleInviteUser} className="p-6 space-y-4">
              <div>
                <label className="block text-xs font-semibold text-slate-700 mb-1">Email Address</label>
                <input
                  type="email"
                  required
                  placeholder="user@example.com"
                  value={inviteEmail}
                  onChange={(e) => setInviteEmail(e.target.value)}
                  className="w-full px-3 py-2 border border-slate-200 rounded-xl text-xs focus:outline-none focus:ring-2 focus:ring-slate-900/10 focus:border-slate-900"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-700 mb-1">Role</label>
                <select
                  value={inviteRole}
                  onChange={(e) => setInviteRole(e.target.value)}
                  className="w-full px-3 py-2 border border-slate-200 rounded-xl text-xs focus:outline-none focus:ring-2 focus:ring-slate-900/10 focus:border-slate-900"
                >
                  <optgroup label="Internal Staff">
                    <option value="owner">Owner (Full Admin)</option>
                    <option value="admin">Admin</option>
                    <option value="strategist">Strategist</option>
                    <option value="editor">Editor</option>
                  </optgroup>
                  <optgroup label="Client Portal Users">
                    <option value="client_approver">Client Approver (Can Sign Off)</option>
                    <option value="client_viewer">Client Viewer (Read Only)</option>
                  </optgroup>
                </select>
              </div>

              {isPortalRole && (
                <div>
                  <label className="block text-xs font-semibold text-slate-700 mb-1">
                    Assign Accessible Brands
                  </label>
                  <div className="max-h-36 overflow-y-auto space-y-1.5 border border-slate-200 rounded-xl p-2.5">
                    {allClients.map((c) => {
                      const isChecked = inviteClientIds.includes(c.id);
                      return (
                        <label key={c.id} className="flex items-center gap-2 text-xs text-slate-700 cursor-pointer">
                          <input
                            type="checkbox"
                            checked={isChecked}
                            onChange={() => {
                              if (isChecked) {
                                setInviteClientIds(inviteClientIds.filter((id) => id !== c.id));
                              } else {
                                setInviteClientIds([...inviteClientIds, c.id]);
                              }
                            }}
                            className="rounded border-slate-300 text-slate-900 focus:ring-slate-900"
                          />
                          <span>{c.name}</span>
                        </label>
                      );
                    })}
                  </div>
                </div>
              )}

              <div className="flex items-center justify-end gap-2 pt-2 border-t border-slate-100">
                <button
                  type="button"
                  onClick={() => setShowInviteModal(false)}
                  className="px-4 py-2 border border-slate-200 rounded-xl text-xs font-medium text-slate-700 hover:bg-slate-50"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={inviteSubmitting}
                  className="px-4 py-2 bg-slate-900 text-white rounded-xl text-xs font-semibold hover:bg-slate-800 disabled:opacity-50 flex items-center gap-1.5"
                >
                  {inviteSubmitting && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                  Save Member
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ─────────────────────────────────────────────────────────────────── */}
      {/* MODAL: Configure Safety Caps */}
      {/* ─────────────────────────────────────────────────────────────────── */}
      {selectedClientForCaps && (
        <div className="fixed inset-0 bg-slate-900/40 backdrop-blur-xs flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-2xl max-w-md w-full border border-slate-200 shadow-xl overflow-hidden animate-in zoom-in-95 duration-200">
            <div className="px-6 py-4 border-b border-slate-100 flex items-center justify-between">
              <div>
                <h3 className="text-base font-bold text-slate-900">Configure Safety Caps</h3>
                <p className="text-xs text-slate-500">{selectedClientForCaps.name}</p>
              </div>
              <button onClick={() => setSelectedClientForCaps(null)} className="text-slate-400 hover:text-slate-600">
                <X className="w-5 h-5" />
              </button>
            </div>

            <form onSubmit={handleSaveCaps} className="p-6 space-y-4">
              <div>
                <label className="block text-xs font-semibold text-slate-700 mb-1">
                  Max Tracked Prompts Cap
                </label>
                <input
                  type="number"
                  value={capMaxPrompts}
                  onChange={(e) => setCapMaxPrompts(e.target.value)}
                  placeholder="e.g. 1000"
                  className="w-full px-3 py-2 border border-slate-200 rounded-xl text-xs focus:outline-none focus:ring-2 focus:ring-slate-900/10 focus:border-slate-900"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-700 mb-1">
                  Monthly Spend Limit ($USD)
                </label>
                <input
                  type="number"
                  step="0.01"
                  value={capMaxMonthlySpend}
                  onChange={(e) => setCapMaxMonthlySpend(e.target.value)}
                  placeholder="e.g. 500.00"
                  className="w-full px-3 py-2 border border-slate-200 rounded-xl text-xs focus:outline-none focus:ring-2 focus:ring-slate-900/10 focus:border-slate-900"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-700 mb-1">
                  Max Runs Per Day Throttling
                </label>
                <input
                  type="number"
                  value={capMaxRunsPerDay}
                  onChange={(e) => setCapMaxRunsPerDay(e.target.value)}
                  placeholder="e.g. 50"
                  className="w-full px-3 py-2 border border-slate-200 rounded-xl text-xs focus:outline-none focus:ring-2 focus:ring-slate-900/10 focus:border-slate-900"
                />
              </div>

              <div className="flex items-center justify-end gap-2 pt-2 border-t border-slate-100">
                <button
                  type="button"
                  onClick={() => setSelectedClientForCaps(null)}
                  className="px-4 py-2 border border-slate-200 rounded-xl text-xs font-medium text-slate-700 hover:bg-slate-50"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={capSubmitting}
                  className="px-4 py-2 bg-slate-900 text-white rounded-xl text-xs font-semibold hover:bg-slate-800 disabled:opacity-50 flex items-center gap-1.5"
                >
                  {capSubmitting && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                  Update Caps
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ─────────────────────────────────────────────────────────────────── */}
      {/* MODAL: Audit Event Metadata Viewer */}
      {/* ─────────────────────────────────────────────────────────────────── */}
      {selectedMetaLog && (
        <div className="fixed inset-0 bg-slate-900/40 backdrop-blur-xs flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-2xl max-w-lg w-full border border-slate-200 shadow-xl overflow-hidden animate-in zoom-in-95 duration-200">
            <div className="px-6 py-4 border-b border-slate-100 flex items-center justify-between">
              <div>
                <h3 className="text-base font-bold text-slate-900">
                  Audit Event #{selectedMetaLog.id}
                </h3>
                <p className="text-xs text-slate-500 font-mono">{selectedMetaLog.action}</p>
              </div>
              <button onClick={() => setSelectedMetaLog(null)} className="text-slate-400 hover:text-slate-600">
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="p-6 space-y-3">
              <div className="text-xs text-slate-500 flex justify-between">
                <span>Actor: <strong>{selectedMetaLog.actor_email || selectedMetaLog.actor || "System"}</strong></span>
                <span>{new Date(selectedMetaLog.at).toLocaleString()}</span>
              </div>
              <pre className="p-4 bg-slate-900 text-emerald-400 rounded-xl text-xs font-mono overflow-x-auto max-h-72">
                {JSON.stringify(selectedMetaLog.meta, null, 2)}
              </pre>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
