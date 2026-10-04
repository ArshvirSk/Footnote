"use client";

import { Fragment, useCallback, useEffect, useState } from "react";
import {
  AlertCircle,
  Check,
  ChevronDown,
  ChevronRight,
  RotateCcw,
  TrendingDown,
  X,
} from "lucide-react";
import { gapsApi, getDefaultClientId, type Gap, type GapDetail } from "../../../../lib/api";
import { formatDate } from "../../../../lib/ui";

const FILTERS = [
  { key: "all", label: "All" },
  { key: "open", label: "Open" },
  { key: "in_progress", label: "In progress" },
  { key: "won", label: "Won" },
  { key: "dismissed", label: "Dismissed" },
] as const;

function gapStatusClass(status: string): string {
  switch (status) {
    case "open":
      return "bg-amber-50 text-amber-700 border-amber-200";
    case "in_progress":
      return "bg-sky-50 text-sky-700 border-sky-200";
    case "won":
      return "bg-emerald-50 text-emerald-700 border-emerald-200";
    default:
      return "bg-slate-100 text-slate-600 border-slate-200";
  }
}

function GapTypeBadge({ gapType }: { gapType: string }) {
  if (gapType === "slipped") {
    return (
      <span className="inline-flex items-center text-amber-700 font-medium">
        <TrendingDown className="w-4 h-4 mr-1.5" /> Ranking slipped
      </span>
    );
  }
  return (
    <span className="inline-flex items-center text-rose-700 font-medium">
      <AlertCircle className="w-4 h-4 mr-1.5" /> {gapType.replace(/_/g, " ")}
    </span>
  );
}

function EvidencePanel({ detail }: { detail: GapDetail }) {
  return (
    <div className="space-y-4">
      <div className="text-sm text-slate-600 bg-slate-50 border border-slate-100 rounded-lg px-3 py-2">{detail.why}</div>

      {Object.entries(detail.details).filter(([, v]) => ["string", "number", "boolean"].includes(typeof v)).length > 0 && (
        <div className="flex flex-wrap gap-x-6 gap-y-1 text-xs text-slate-500">
          {Object.entries(detail.details)
            .filter(([, v]) => ["string", "number", "boolean"].includes(typeof v))
            .map(([k, v]) => (
              <span key={k}>
                <span className="text-slate-400">{k}:</span> {String(v)}
              </span>
            ))}
        </div>
      )}

      {detail.evidence.length === 0 ? (
        <div className="text-sm text-slate-400">No collected answers behind this gap yet.</div>
      ) : (
        <ul className="space-y-3">
          {detail.evidence.map((e) => (
            <li key={e.answer_id} className="border border-slate-100 rounded-lg p-3 bg-slate-50/50">
              <div className="flex flex-wrap items-center gap-2 text-xs">
                <span className="font-medium text-slate-700 capitalize">{e.engine.replace("_", " ")}</span>
                <span className="text-slate-400">run {e.run_index}</span>
                {e.day && <span className="text-slate-400">{formatDate(e.day)}</span>}
                <span
                  className={`px-2 py-0.5 rounded-full border ${
                    e.brand_mentioned
                      ? "bg-emerald-50 text-emerald-700 border-emerald-200"
                      : "bg-slate-100 text-slate-500 border-slate-200"
                  }`}
                >
                  {e.brand_mentioned ? "brand mentioned" : "brand absent"}
                </span>
                {e.competitor_mentioned && (
                  <span className="px-2 py-0.5 rounded-full bg-rose-50 text-rose-700 border border-rose-200">
                    competitor present
                  </span>
                )}
              </div>
              {e.excerpt && (
                <p className="text-sm text-slate-700 mt-2 whitespace-pre-wrap">{e.excerpt}</p>
              )}
              {e.citations.length > 0 && (
                <ul className="mt-2 space-y-0.5">
                  {e.citations.map((c) => (
                    <li key={c.url} className="text-xs truncate">
                      <a
                        href={c.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className={`hover:underline ${c.owned ? "text-emerald-700" : "text-slate-500"}`}
                      >
                        {c.owned ? "[owned] " : ""}
                        {c.title || c.url}
                      </a>
                    </li>
                  ))}
                </ul>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default function GapsPage() {
  const [clientId, setClientId] = useState<string | null>(null);
  const [gaps, setGaps] = useState<Gap[]>([]);
  const [filter, setFilter] = useState<(typeof FILTERS)[number]["key"]>("open");
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [details, setDetails] = useState<Record<string, GapDetail>>({});
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (cid?: string) => {
    try {
      const client = cid ?? (await getDefaultClientId());
      if (!cid) setClientId(client);
      setGaps(await gapsApi.list(client));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load gaps");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void (async () => load())();
  }, [load]);

  async function toggleEvidence(gap: Gap) {
    if (expandedId === gap.id) {
      setExpandedId(null);
      return;
    }
    setExpandedId(gap.id);
    if (!details[gap.id] || details[gap.id].status !== gap.status) {
      if (!clientId) return;
      setLoadingDetail(true);
      try {
        const detail = await gapsApi.detail(clientId, gap.id);
        setDetails((prev) => ({ ...prev, [gap.id]: detail }));
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load evidence");
      } finally {
        setLoadingDetail(false);
      }
    }
  }

  async function setStatus(gap: Gap, status: string) {
    if (!clientId) return;
    setBusy(true);
    try {
      const updated = await gapsApi.setStatus(clientId, gap.id, status);
      setGaps((prev) => prev.map((g) => (g.id === gap.id ? { ...g, status: updated.status } : g)));
      setDetails((prev) => {
        const existing = prev[gap.id];
        return existing ? { ...prev, [gap.id]: { ...existing, status: updated.status } } : prev;
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Status update failed");
    } finally {
      setBusy(false);
    }
  }

  const counts = FILTERS.reduce<Record<string, number>>((acc, f) => {
    acc[f.key] = f.key === "all" ? gaps.length : gaps.filter((g) => g.status === f.key).length;
    return acc;
  }, {});
  const visible = filter === "all" ? gaps : gaps.filter((g) => g.status === filter);

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-end flex-wrap gap-3">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight text-slate-900">Gaps &amp; Slips</h1>
          <p className="text-slate-600 mt-1">
            Automatically detected visibility losses and competitor citations, with the raw answers behind each one.
          </p>
        </div>
      </div>

      {error && (
        <div className="text-sm text-rose-600 bg-rose-50 border border-rose-200 rounded-lg px-4 py-3">{error}</div>
      )}

      <div className="flex flex-wrap gap-2">
        {FILTERS.map((f) => (
          <button
            key={f.key}
            onClick={() => setFilter(f.key)}
            className={`px-3 py-1.5 rounded-lg text-sm border transition ${
              filter === f.key ? "bg-slate-900 text-white border-slate-900" : "bg-white text-slate-600 border-slate-200 hover:bg-slate-50"
            }`}
          >
            {f.label}
            <span className={`ml-1.5 text-xs ${filter === f.key ? "text-slate-300" : "text-slate-400"}`}>{counts[f.key]}</span>
          </button>
        ))}
      </div>

      <div className="bg-white border border-slate-200 rounded-xl shadow-sm overflow-hidden">
        <table className="w-full text-left text-sm">
          <thead className="bg-slate-50 border-b border-slate-200 text-slate-500">
            <tr>
              <th className="px-6 py-4 font-medium">Issue Type</th>
              <th className="px-6 py-4 font-medium">Query / Prompt</th>
              <th className="px-6 py-4 font-medium">Detected</th>
              <th className="px-6 py-4 font-medium">Status</th>
              <th className="px-6 py-4 font-medium text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {loading ? (
              <tr>
                <td colSpan={5} className="px-6 py-8 text-center text-slate-400">
                  Analyzing latest rollup…
                </td>
              </tr>
            ) : visible.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-6 py-8 text-center text-slate-400">
                  {filter === "open" ? "No open gaps — nothing slipped and no competitor is outranking you." : "Nothing in this status."}
                </td>
              </tr>
            ) : (
              visible.map((g) => (
                <Fragment key={g.id}>
                  <tr className="hover:bg-slate-50/50 transition-colors align-top">
                    <td className="px-6 py-4">
                      <GapTypeBadge gapType={g.gap_type} />
                    </td>
                    <td className="px-6 py-4 font-medium text-slate-900 max-w-md">{g.prompt_text || g.prompt_id || "—"}</td>
                    <td className="px-6 py-4 text-slate-600 whitespace-nowrap">
                      {g.detected_at ? formatDate(g.detected_at) : "—"}
                    </td>
                    <td className="px-6 py-4">
                      <span className={`px-2.5 py-1 rounded-full text-xs font-medium border capitalize ${gapStatusClass(g.status)}`}>
                        {g.status.replace("_", " ")}
                      </span>
                    </td>
                    <td className="px-6 py-4 text-right whitespace-nowrap">
                      <button
                        onClick={() => void toggleEvidence(g)}
                        className="inline-flex items-center text-slate-500 hover:text-slate-800 text-sm font-medium mr-2"
                      >
                        {expandedId === g.id ? (
                          <ChevronDown className="w-4 h-4 mr-1" />
                        ) : (
                          <ChevronRight className="w-4 h-4 mr-1" />
                        )}
                        Evidence
                      </button>
                      {g.status === "open" && (
                        <button
                          onClick={() => void setStatus(g, "in_progress")}
                          disabled={busy}
                          className="px-2.5 py-1 rounded-lg bg-sky-50 text-sky-700 border border-sky-200 hover:bg-sky-100 text-xs font-medium disabled:opacity-50 mr-1.5"
                        >
                          Start
                        </button>
                      )}
                      {(g.status === "open" || g.status === "in_progress") && (
                        <>
                          <button
                            onClick={() => void setStatus(g, "won")}
                            disabled={busy}
                            title="Mark won"
                            className="p-1.5 rounded bg-emerald-50 text-emerald-700 border border-emerald-200 hover:bg-emerald-100 disabled:opacity-50 mr-1"
                          >
                            <Check className="w-3.5 h-3.5" />
                          </button>
                          <button
                            onClick={() => void setStatus(g, "dismissed")}
                            disabled={busy}
                            title="Dismiss"
                            className="p-1.5 rounded bg-slate-50 text-slate-500 border border-slate-200 hover:bg-slate-100 disabled:opacity-50"
                          >
                            <X className="w-3.5 h-3.5" />
                          </button>
                        </>
                      )}
                      {(g.status === "won" || g.status === "dismissed") && (
                        <button
                          onClick={() => void setStatus(g, "open")}
                          disabled={busy}
                          title="Reopen"
                          className="p-1.5 rounded bg-slate-50 text-slate-500 border border-slate-200 hover:bg-slate-100 disabled:opacity-50"
                        >
                          <RotateCcw className="w-3.5 h-3.5" />
                        </button>
                      )}
                    </td>
                  </tr>
                  {expandedId === g.id && (
                    <tr className="bg-slate-50/70">
                      <td colSpan={5} className="px-6 py-4">
                        {loadingDetail && !details[g.id] ? (
                          <div className="text-sm text-slate-400">Loading evidence…</div>
                        ) : details[g.id] ? (
                          <EvidencePanel detail={details[g.id]} />
                        ) : (
                          <div className="text-sm text-slate-400">Evidence unavailable.</div>
                        )}
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))
            )}
          </tbody>
        </table>
      </div>

      <p className="text-xs text-slate-400">
        Evidence shows the raw collected answers the detector ran on. Statuses move open → in progress → won; dismissed gaps
        keep their history.
      </p>
    </div>
  );
}
