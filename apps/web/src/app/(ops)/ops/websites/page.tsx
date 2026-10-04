"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Globe, Plus, Radar } from "lucide-react";
import {
  audits,
  clients,
  getSelectedClientId,
  setSelectedClientId,
  websites,
  type ClientSummary,
} from "../../../../lib/api";
import DemoBadge from "../../../../components/DemoBadge";
import { formatDateTime, pct, statusBadgeClass, statusLabel } from "../../../../lib/ui";

export default function WebsitesPage() {
  const router = useRouter();
  const [list, setList] = useState<ClientSummary[]>([]);
  const [includeDemo, setIncludeDemo] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [newName, setNewName] = useState("");
  const [newDomain, setNewDomain] = useState("");
  const [saving, setSaving] = useState(false);
  const [auditingId, setAuditingId] = useState<string | null>(null);

  async function load(demo: boolean) {
    try {
      const data = await websites.list(demo);
      setList(data);
      const stored = getSelectedClientId();
      setSelected(stored && data.some((c) => c.id === stored) ? stored : (data[0]?.id ?? null));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load websites");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void (async () => load(includeDemo))();
  }, [includeDemo]);

  function selectClient(id: string) {
    setSelectedClientId(id);
    setSelected(id);
  }

  function openWebsite(id: string) {
    selectClient(id);
    router.push(`/ops/websites/${id}`);
  }

  async function onCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!newName.trim() || !newDomain.trim()) return;
    setSaving(true);
    setError(null);
    try {
      const created = await clients.create({
        name: newName.trim(),
        primary_domain: newDomain.trim().replace(/^https?:\/\//, "").replace(/\/.*$/, ""),
      });
      setSelectedClientId(created.id);
      setNewName("");
      setNewDomain("");
      setShowForm(false);
      await load(includeDemo);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to add website");
    } finally {
      setSaving(false);
    }
  }

  async function auditNow(clientId: string) {
    selectClient(clientId);
    setAuditingId(clientId);
    setError(null);
    try {
      await audits.start(clientId);
      router.push("/ops/site-audit");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Audit failed");
      setAuditingId(null);
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-end flex-wrap gap-4">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight text-slate-900">Websites</h1>
          <p className="text-slate-600 mt-1">
            Every website is tracked separately. Status is derived from its setup checklist and from the
            data actually collected for it.
          </p>
        </div>
        <div className="flex items-center gap-4">
          <label className="flex items-center gap-2 text-sm text-slate-600">
            <input
              type="checkbox"
              checked={includeDemo}
              onChange={(e) => setIncludeDemo(e.target.checked)}
              className="h-4 w-4 rounded border-slate-300"
            />
            Show demo data
          </label>
          <button
            onClick={() => setShowForm((v) => !v)}
            className="flex items-center px-4 py-2 bg-slate-900 text-white rounded-lg hover:bg-slate-800 transition font-medium text-sm shadow-sm"
          >
            <Plus className="w-4 h-4 mr-2" />
            Add website
          </button>
        </div>
      </div>

      {error && (
        <div className="text-sm text-rose-600 bg-rose-50 border border-rose-200 rounded-lg px-4 py-3">{error}</div>
      )}

      {showForm && (
        <form onSubmit={onCreate} className="bg-white border border-slate-200 rounded-xl shadow-sm p-6 space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label htmlFor="site-name" className="block text-sm font-medium text-slate-700 mb-1">
                Name
              </label>
              <input
                id="site-name"
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                required
                placeholder="e.g. My Company"
                className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-slate-900"
              />
            </div>
            <div>
              <label htmlFor="site-domain" className="block text-sm font-medium text-slate-700 mb-1">
                Domain
              </label>
              <input
                id="site-domain"
                value={newDomain}
                onChange={(e) => setNewDomain(e.target.value)}
                required
                placeholder="example.com"
                className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-slate-900"
              />
            </div>
          </div>
          <div className="flex gap-3">
            <button
              type="submit"
              disabled={saving || !newName.trim() || !newDomain.trim()}
              className="px-4 py-2 bg-slate-900 text-white rounded-lg hover:bg-slate-800 transition font-medium text-sm disabled:opacity-60"
            >
              {saving ? "Adding…" : "Add website"}
            </button>
            <button
              type="button"
              onClick={() => setShowForm(false)}
              className="px-4 py-2 border border-slate-200 text-slate-600 rounded-lg hover:bg-slate-50 transition font-medium text-sm"
            >
              Cancel
            </button>
          </div>
        </form>
      )}

      <div className="bg-white border border-slate-200 rounded-xl shadow-sm overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm min-w-[64rem]">
            <thead className="bg-slate-50 border-b border-slate-200 text-slate-500">
              <tr>
                <th className="px-6 py-4 font-medium">Website</th>
                <th className="px-4 py-4 font-medium">Status</th>
                <th className="px-4 py-4 font-medium">Setup</th>
                <th className="px-4 py-4 font-medium">Last collection</th>
                <th className="px-4 py-4 font-medium">Visibility 7d</th>
                <th className="px-4 py-4 font-medium">Open issues</th>
                <th className="px-4 py-4 font-medium">Approvals</th>
                <th className="px-6 py-4 font-medium text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {loading ? (
                <tr>
                  <td colSpan={8} className="px-6 py-8 text-center text-slate-400">
                    Loading websites…
                  </td>
                </tr>
              ) : list.length === 0 ? (
                <tr>
                  <td colSpan={8} className="px-6 py-8 text-center text-slate-400">
                    {includeDemo
                      ? "No websites found."
                      : "No live websites yet — add one, or tick “Show demo data” to see the seeded examples."}
                  </td>
                </tr>
              ) : (
                list.map((c) => {
                  const isSelected = c.id === selected;
                  return (
                    <tr
                      key={c.id}
                      onClick={() => openWebsite(c.id)}
                      className={`cursor-pointer transition-colors ${isSelected ? "bg-slate-50" : "hover:bg-slate-50/60"}`}
                    >
                      <td className="px-6 py-4">
                        <div className="flex items-center gap-2.5 flex-wrap">
                          <Globe className={`w-4 h-4 ${isSelected ? "text-emerald-500" : "text-slate-300"}`} />
                          <Link
                            href={`/ops/websites/${c.id}`}
                            onClick={(e) => e.stopPropagation()}
                            className="font-medium text-slate-900 hover:text-blue-700 hover:underline"
                          >
                            {c.name}
                          </Link>
                          {c.is_demo && <DemoBadge />}
                          {isSelected && (
                            <span className="px-2 py-0.5 bg-emerald-50 text-emerald-700 border border-emerald-200 rounded-full text-xs font-medium">
                              Selected
                            </span>
                          )}
                        </div>
                        <div className="text-xs text-slate-400 mt-0.5 ml-6">{c.primary_domain}</div>
                      </td>
                      <td className="px-4 py-4">
                        <span
                          className={`px-2.5 py-1 rounded-full text-xs font-medium border ${statusBadgeClass(c.derived_status)}`}
                        >
                          {statusLabel(c.derived_status)}
                        </span>
                      </td>
                      <td className="px-4 py-4">
                        <div className="flex items-center gap-2">
                          <span className="text-slate-700 font-medium">
                            {c.setup_progress}/{c.setup_total}
                          </span>
                          <div className="w-16 h-1.5 bg-slate-100 rounded-full overflow-hidden">
                            <div
                              className="h-1.5 bg-emerald-500"
                              style={{ width: `${(c.setup_progress / c.setup_total) * 100}%` }}
                            />
                          </div>
                        </div>
                      </td>
                      <td className="px-4 py-4 text-slate-600">{formatDateTime(c.last_collection_at)}</td>
                      <td className="px-4 py-4 text-slate-700 font-medium">{pct(c.visibility_pct)}</td>
                      <td className="px-4 py-4">
                        {c.open_issues > 0 ? (
                          <span className="text-amber-700 font-medium">{c.open_issues}</span>
                        ) : (
                          <span className="text-slate-400">0</span>
                        )}
                      </td>
                      <td className="px-4 py-4">
                        {c.pending_approvals > 0 ? (
                          <span className="text-blue-700 font-medium">{c.pending_approvals}</span>
                        ) : (
                          <span className="text-slate-400">0</span>
                        )}
                      </td>
                      <td className="px-6 py-4 text-right">
                        <div className="flex items-center justify-end gap-2">
                          <Link
                            href={`/ops/websites/${c.id}`}
                            onClick={(e) => e.stopPropagation()}
                            className="inline-flex items-center px-3 py-1.5 bg-white border border-slate-200 text-slate-700 rounded-lg hover:bg-slate-50 transition font-medium text-xs"
                          >
                            Open
                          </Link>
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              void auditNow(c.id);
                            }}
                            disabled={auditingId === c.id}
                            className="inline-flex items-center px-3 py-1.5 bg-white border border-slate-200 text-slate-700 rounded-lg hover:bg-slate-50 transition font-medium text-xs disabled:opacity-60"
                          >
                            <Radar className={`w-3.5 h-3.5 mr-1.5 ${auditingId === c.id ? "animate-spin" : ""}`} />
                            {auditingId === c.id ? "Auditing…" : "Audit now"}
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>

      <p className="text-xs text-slate-400">
        Tip: use the website switcher in the header to change the active website — it drives every page and is
        remembered in this browser.
      </p>
    </div>
  );
}
