"use client";

import { useEffect, useState } from "react";
import { CheckCircle2, Globe, Key, Loader2, Plus, RefreshCw, Trash2, XCircle } from "lucide-react";
import {
  publishingApi,
  type PublishTarget,
  type PublishTargetCreate,
  type PublishTargetTestResponse,
} from "../lib/api";

interface Props {
  clientId: string;
}

export default function PublishTargetsPanel({ clientId }: Props) {
  const [targets, setTargets] = useState<PublishTarget[]>([]);
  const [loading, setLoading] = useState(true);
  const [testingId, setTestingId] = useState<string | null>(null);
  const [testResults, setTestResults] = useState<Record<string, PublishTargetTestResponse>>({});
  const [showAddModal, setShowAddModal] = useState(false);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Form state
  const [kind, setKind] = useState<"wordpress" | "feeds" | "webhook">("wordpress");
  const [name, setName] = useState("");
  const [isDefault, setIsDefault] = useState(false);
  const [wpEndpoint, setWpEndpoint] = useState("");
  const [wpUsername, setWpUsername] = useState("");
  const [wpAppPassword, setWpAppPassword] = useState("");
  const [feedsMount, setFeedsMount] = useState("/feeds");
  const [feedsDomain, setFeedsDomain] = useState("");
  const [webhookUrl, setWebhookUrl] = useState("");

  const loadTargets = async () => {
    try {
      setLoading(true);
      const res = await publishingApi.listTargets(clientId);
      setTargets(res);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load publishing targets");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadTargets();
  }, [clientId]);

  const handleTest = async (targetId: string) => {
    setTestingId(targetId);
    try {
      const res = await publishingApi.testTarget(clientId, targetId);
      setTestResults((prev) => ({ ...prev, [targetId]: res }));
      void loadTargets();
    } catch (err) {
      setTestResults((prev) => ({
        ...prev,
        [targetId]: {
          status: "failed",
          detail: err instanceof Error ? err.message : "Connection test failed",
          latency_ms: 0,
        },
      }));
    } finally {
      setTestingId(null);
    }
  };

  const handleDelete = async (targetId: string) => {
    if (!confirm("Are you sure you want to delete this publish target?")) return;
    try {
      await publishingApi.deleteTarget(clientId, targetId);
      setTargets((prev) => prev.filter((t) => t.id !== targetId));
    } catch (err) {
      alert(err instanceof Error ? err.message : "Failed to delete target");
    }
  };

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    setCreating(true);
    setError(null);

    let config: Record<string, any> = {};
    if (kind === "wordpress") {
      config = {
        endpoint: wpEndpoint.trim(),
        username: wpUsername.trim(),
        app_password: wpAppPassword.trim(),
      };
    } else if (kind === "feeds") {
      config = {
        mount_path: feedsMount.trim() || "/feeds",
        custom_domain: feedsDomain.trim() || undefined,
      };
    } else if (kind === "webhook") {
      config = {
        webhook_url: webhookUrl.trim(),
      };
    }

    const payload: PublishTargetCreate = {
      name: name.trim() || (kind === "wordpress" ? "WordPress Blog" : kind === "feeds" ? "Static Edge Feeds" : "Webhook"),
      kind,
      is_default: isDefault,
      config,
    };

    try {
      await publishingApi.createTarget(clientId, payload);
      setShowAddModal(false);
      setName("");
      setWpEndpoint("");
      setWpUsername("");
      setWpAppPassword("");
      await loadTargets();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create target");
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="font-medium text-slate-900">Publishing Targets</h2>
          <p className="text-sm text-slate-500 mt-0.5">
            Configure CMS endpoints and static feeds. Hard rule: content cannot publish without an approved version.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setShowAddModal(true)}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-medium rounded-lg shadow-sm transition"
        >
          <Plus className="w-3.5 h-3.5" /> Add Target
        </button>
      </div>

      {error && (
        <div className="text-xs text-rose-600 bg-rose-50 border border-rose-200 rounded-lg p-3">
          {error}
        </div>
      )}

      {loading ? (
        <div className="text-xs text-slate-400 py-4">Loading configured targets…</div>
      ) : targets.length === 0 ? (
        <div className="bg-slate-50 border border-dashed border-slate-200 rounded-xl p-8 text-center">
          <Globe className="w-8 h-8 text-slate-400 mx-auto mb-2" />
          <h3 className="text-sm font-medium text-slate-700">No Publishing Targets</h3>
          <p className="text-xs text-slate-500 max-w-sm mx-auto mt-1 mb-4">
            Connect a WordPress site or enable Footnote Feeds so approved content can be shipped with JSON-LD schema.
          </p>
          <button
            type="button"
            onClick={() => setShowAddModal(true)}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-slate-900 hover:bg-black text-white text-xs font-medium rounded-lg"
          >
            <Plus className="w-3.5 h-3.5" /> Configure WordPress or Feeds
          </button>
        </div>
      ) : (
        <div className="grid gap-3">
          {targets.map((target) => {
            const testResult = testResults[target.id];
            const isTesting = testingId === target.id;

            return (
              <div
                key={target.id}
                className="bg-white border border-slate-200 rounded-xl p-4 flex flex-col md:flex-row md:items-center justify-between gap-4 shadow-sm hover:border-slate-300 transition"
              >
                <div className="space-y-1">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="font-semibold text-sm text-slate-900">
                      {target.name || target.kind.toUpperCase()}
                    </span>
                    <span className="px-2 py-0.5 rounded-full text-[11px] font-medium uppercase bg-slate-100 text-slate-700 border border-slate-200">
                      {target.kind}
                    </span>
                    {target.is_default && (
                      <span className="px-2 py-0.5 rounded-full text-[11px] font-medium bg-emerald-50 text-emerald-700 border border-emerald-200">
                        Default
                      </span>
                    )}
                    {target.last_test_status === "success" && (
                      <span className="inline-flex items-center gap-1 text-[11px] text-emerald-600 bg-emerald-50 px-2 py-0.5 rounded-md border border-emerald-100">
                        <CheckCircle2 className="w-3 h-3" /> Connected
                      </span>
                    )}
                    {target.last_test_status === "failed" && (
                      <span className="inline-flex items-center gap-1 text-[11px] text-rose-600 bg-rose-50 px-2 py-0.5 rounded-md border border-rose-100">
                        <XCircle className="w-3 h-3" /> Test Failed
                      </span>
                    )}
                  </div>

                  <div className="text-xs text-slate-500 font-mono flex items-center gap-3">
                    {target.kind === "wordpress" && (
                      <>
                        <span>Endpoint: {target.config.endpoint || target.config.url || "Not set"}</span>
                        <span>User: {target.config.username || "—"}</span>
                        <span>Key: {target.config.app_password || "••••••••"}</span>
                      </>
                    )}
                    {target.kind === "feeds" && (
                      <>
                        <span>Mount: {target.config.mount_path || "/feeds"}</span>
                        {target.config.custom_domain && <span>Domain: {target.config.custom_domain}</span>}
                      </>
                    )}
                    {target.kind === "webhook" && (
                      <span>URL: {target.config.webhook_url || target.config.url}</span>
                    )}
                  </div>

                  {/* Inline test message banner */}
                  {testResult && (
                    <div
                      className={`text-xs p-2 rounded-lg mt-2 ${
                        testResult.status === "success"
                          ? "bg-emerald-50 text-emerald-800 border border-emerald-200"
                          : "bg-rose-50 text-rose-800 border border-rose-200"
                      }`}
                    >
                      <div className="font-medium flex items-center justify-between">
                        <span>{testResult.detail}</span>
                        {testResult.latency_ms > 0 && (
                          <span className="text-[10px] opacity-75">{testResult.latency_ms}ms</span>
                        )}
                      </div>
                    </div>
                  )}
                </div>

                <div className="flex items-center gap-2 self-end md:self-center">
                  <button
                    type="button"
                    onClick={() => handleTest(target.id)}
                    disabled={isTesting}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-lg transition disabled:opacity-50"
                  >
                    {isTesting ? (
                      <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    ) : (
                      <RefreshCw className="w-3.5 h-3.5" />
                    )}
                    Test Connection
                  </button>

                  <button
                    type="button"
                    onClick={() => handleDelete(target.id)}
                    className="p-1.5 text-slate-400 hover:text-rose-600 rounded-lg hover:bg-rose-50 transition"
                    title="Delete target"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Add Target Modal */}
      {showAddModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 backdrop-blur-sm p-4">
          <div className="bg-white rounded-2xl max-w-lg w-full p-6 shadow-2xl border border-slate-200">
            <h3 className="text-lg font-semibold text-slate-900">Add Publishing Target</h3>
            <p className="text-xs text-slate-500 mt-0.5 mb-4">
              Credentials are securely stored using AES-256-GCM encryption.
            </p>

            <form onSubmit={handleCreate} className="space-y-4">
              <div>
                <label className="block text-xs font-medium text-slate-700 mb-1">Target Type</label>
                <div className="grid grid-cols-3 gap-2">
                  {(["wordpress", "feeds", "webhook"] as const).map((k) => (
                    <button
                      key={k}
                      type="button"
                      onClick={() => setKind(k)}
                      className={`px-3 py-2 text-xs font-medium rounded-lg border capitalize transition ${
                        kind === k
                          ? "bg-slate-900 text-white border-slate-900 shadow-sm"
                          : "bg-white text-slate-700 border-slate-200 hover:bg-slate-50"
                      }`}
                    >
                      {k}
                    </button>
                  ))}
                </div>
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-700 mb-1">Target Name</label>
                <input
                  type="text"
                  required
                  placeholder={kind === "wordpress" ? "Main WordPress Blog" : "Static Feeds Hub"}
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  className="w-full text-xs px-3 py-2 border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-emerald-500"
                />
              </div>

              {kind === "wordpress" && (
                <div className="space-y-3 bg-slate-50 p-3.5 rounded-xl border border-slate-200">
                  <div>
                    <label className="block text-xs font-medium text-slate-700 mb-1">WordPress Site URL</label>
                    <input
                      type="url"
                      required
                      placeholder="https://example.com"
                      value={wpEndpoint}
                      onChange={(e) => setWpEndpoint(e.target.value)}
                      className="w-full text-xs px-3 py-2 border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-emerald-500 bg-white"
                    />
                  </div>
                  <div className="grid grid-cols-2 gap-2">
                    <div>
                      <label className="block text-xs font-medium text-slate-700 mb-1">Username</label>
                      <input
                        type="text"
                        required
                        placeholder="editor_admin"
                        value={wpUsername}
                        onChange={(e) => setWpUsername(e.target.value)}
                        className="w-full text-xs px-3 py-2 border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-emerald-500 bg-white"
                      />
                    </div>
                    <div>
                      <label className="block text-xs font-medium text-slate-700 mb-1">
                        Application Password
                      </label>
                      <input
                        type="password"
                        required
                        placeholder="xxxx xxxx xxxx xxxx"
                        value={wpAppPassword}
                        onChange={(e) => setWpAppPassword(e.target.value)}
                        className="w-full text-xs px-3 py-2 border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-emerald-500 bg-white"
                      />
                    </div>
                  </div>
                  <p className="text-[11px] text-slate-500">
                    Generate an Application Password in WordPress: Users &rarr; Profile &rarr; Application Passwords.
                  </p>
                </div>
              )}

              {kind === "feeds" && (
                <div className="space-y-3 bg-slate-50 p-3.5 rounded-xl border border-slate-200">
                  <div>
                    <label className="block text-xs font-medium text-slate-700 mb-1">Mount Path</label>
                    <input
                      type="text"
                      placeholder="/feeds"
                      value={feedsMount}
                      onChange={(e) => setFeedsMount(e.target.value)}
                      className="w-full text-xs px-3 py-2 border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-emerald-500 bg-white"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-slate-700 mb-1">Custom Domain (Optional)</label>
                    <input
                      type="text"
                      placeholder="feeds.client.com"
                      value={feedsDomain}
                      onChange={(e) => setFeedsDomain(e.target.value)}
                      className="w-full text-xs px-3 py-2 border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-emerald-500 bg-white"
                    />
                  </div>
                </div>
              )}

              {kind === "webhook" && (
                <div className="space-y-3 bg-slate-50 p-3.5 rounded-xl border border-slate-200">
                  <div>
                    <label className="block text-xs font-medium text-slate-700 mb-1">Webhook Endpoint URL</label>
                    <input
                      type="url"
                      required
                      placeholder="https://api.client.com/webhooks/footnote-publish"
                      value={webhookUrl}
                      onChange={(e) => setWebhookUrl(e.target.value)}
                      className="w-full text-xs px-3 py-2 border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-emerald-500 bg-white"
                    />
                  </div>
                </div>
              )}

              <div className="flex items-center gap-2">
                <input
                  type="checkbox"
                  id="is-default-target"
                  checked={isDefault}
                  onChange={(e) => setIsDefault(e.target.checked)}
                  className="rounded border-slate-300 text-emerald-600 focus:ring-emerald-500"
                />
                <label htmlFor="is-default-target" className="text-xs text-slate-700">
                  Set as default publish target for this website
                </label>
              </div>

              <div className="flex items-center justify-end gap-2 pt-2 border-t border-slate-100">
                <button
                  type="button"
                  onClick={() => setShowAddModal(false)}
                  className="px-3 py-1.5 text-xs text-slate-600 hover:text-slate-800"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={creating}
                  className="px-4 py-1.5 bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-medium rounded-lg disabled:opacity-50 transition"
                >
                  {creating ? "Encrypting & Saving…" : "Save Target"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
