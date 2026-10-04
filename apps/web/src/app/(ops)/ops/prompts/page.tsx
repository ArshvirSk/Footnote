"use client";

import { Fragment, useEffect, useState } from "react";
import Link from "next/link";
import { Plus, Play, Search, Check, X, Pencil, RotateCcw, Target } from "lucide-react";
import {
  collectionApi,
  getDefaultClientId,
  promptsApi,
  researchApi,
  type CollectionHealth,
  type EngineType,
  type PromptCandidate,
  type PromptListItem,
} from "../../../../lib/api";
import { pct } from "../../../../lib/ui";

const ALL_ENGINES: EngineType[] = ["chatgpt", "gemini", "perplexity", "claude", "grok", "google_aio"];
const MAX_ACTIVE_PROMPTS = 125;

function engineDot(status: string | undefined): string {
  switch (status) {
    case "succeeded":
      return "bg-emerald-500";
    case "failed":
      return "bg-rose-500";
    case "queued":
    case "running":
      return "bg-amber-400";
    default:
      return "bg-slate-300";
  }
}

/** 14-day mention-rate sparkline (empty state when nothing was collected). */
function Sparkline({ series }: { series: { day: string; runs: number; mentioned: number }[] }) {
  if (series.length === 0) {
    return <span className="text-slate-300 text-xs">no runs</span>;
  }
  const width = 84;
  const height = 22;
  const step = series.length > 1 ? width / (series.length - 1) : width;
  const points = series.map((p, i) => {
    const rate = p.runs > 0 ? p.mentioned / p.runs : 0;
    return `${(i * step).toFixed(1)},${(height - rate * (height - 2) - 1).toFixed(1)}`;
  });
  const last = series[series.length - 1];
  const lastRate = last.runs > 0 ? last.mentioned / last.runs : 0;
  return (
    <span className="inline-flex items-center gap-1.5" title={`Last day: ${(lastRate * 100).toFixed(0)}% visible`}>
      <svg width={width} height={height} aria-hidden="true">
        <polyline points={points.join(" ")} fill="none" stroke="#10b981" strokeWidth="1.5" />
      </svg>
      <span className="text-xs text-slate-500">{(lastRate * 100).toFixed(0)}%</span>
    </span>
  );
}

function CollectionHealthPanel({ health, onRunAll, running }: { health: CollectionHealth | null; onRunAll: () => void; running: boolean }) {
  if (!health) return null;
  return (
    <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-5 space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="font-medium text-slate-900">Collection health (last {health.days} days)</h2>
        <div className="flex items-center gap-2">
          {health.mock_mode && (
            <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-amber-50 text-amber-700 border border-amber-200">
              Mock collection (no API keys)
            </span>
          )}
          {health.mock_runs > 0 && (
            <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-slate-100 text-slate-600 border border-slate-200">
              {health.mock_runs} mock runs
            </span>
          )}
          <button
            onClick={onRunAll}
            disabled={running}
            className="flex items-center px-3 py-1.5 bg-slate-900 text-white rounded-lg hover:bg-slate-800 transition text-sm font-medium disabled:opacity-60"
          >
            <Play className="w-3.5 h-3.5 mr-1.5" />
            {running ? "Collecting…" : "Run all now"}
          </button>
        </div>
      </div>

      {health.scheduled === 0 ? (
        <div className="text-sm text-slate-500">
          No runs scheduled yet. Start a batch with <span className="font-medium text-slate-700">Run all now</span> —
          the nightly scheduler does this automatically once a worker is running.
        </div>
      ) : (
        <>
          <div className="flex flex-wrap items-end gap-6">
            <div>
              <div className="text-3xl font-semibold text-slate-900">{pct(health.rate)}</div>
              <div className="text-xs text-slate-500 mt-0.5">
                {health.succeeded} of {health.scheduled} runs succeeded
              </div>
            </div>
            <div className="flex flex-wrap gap-2">
              {health.per_engine.map((e) => (
                <span
                  key={e.engine}
                  className="px-2.5 py-1 rounded border border-slate-200 bg-slate-50 text-xs text-slate-600"
                  title={`${e.succeeded} succeeded, ${e.failed} failed, ${e.queued} queued`}
                >
                  <span className={`inline-block w-1.5 h-1.5 rounded-full mr-1.5 ${engineDot(e.failed > 0 ? "failed" : e.queued > 0 ? "queued" : "succeeded")}`} />
                  {e.engine.replace("_", " ")} {e.succeeded}/{e.scheduled}
                </span>
              ))}
            </div>
          </div>

          {health.failures.length > 0 && (
            <div className="border-t border-slate-100 pt-3">
              <div className="text-xs font-medium text-slate-500 uppercase tracking-wide mb-2">
                Failed runs ({health.failed})
              </div>
              <table className="w-full text-left text-xs">
                <tbody className="divide-y divide-slate-100">
                  {health.failures.slice(0, 5).map((f) => (
                    <tr key={f.answer_id}>
                      <td className="py-1.5 pr-3 text-slate-500 whitespace-nowrap">{f.engine}</td>
                      <td className="py-1.5 pr-3 text-slate-700 max-w-xs truncate">{f.prompt_text || f.prompt_id}</td>
                      <td className="py-1.5 pr-3 text-rose-600 max-w-md truncate">{f.error}</td>
                      <td className="py-1.5 text-slate-400 whitespace-nowrap">{f.attempts} tries</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function ResearchPanel({
  clientId,
  candidates,
  onGenerated,
  onResolved,
}: {
  clientId: string;
  candidates: PromptCandidate[];
  onGenerated: () => void;
  onResolved: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editText, setEditText] = useState("");

  async function generate() {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const res = await researchApi.generate(clientId, 20);
      setNotice(
        res.created === 0
          ? "No new candidates — everything the agent proposes is already in the queue."
          : `Proposed ${res.created} candidate${res.created === 1 ? "" : "s"} (${res.generator}).`,
      );
      onGenerated();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Generation failed");
    } finally {
      setBusy(false);
    }
  }

  async function accept(candidate: PromptCandidate, text?: string) {
    setBusy(true);
    setError(null);
    try {
      await researchApi.accept(clientId, candidate.id, text ? { text } : {});
      setEditingId(null);
      setNotice(`Accepted: ${(text || candidate.text).slice(0, 60)}`);
      onResolved();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Accept failed");
    } finally {
      setBusy(false);
    }
  }

  async function reject(candidate: PromptCandidate) {
    setBusy(true);
    setError(null);
    try {
      await researchApi.reject(clientId, candidate.id);
      onResolved();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Reject failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-5 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="font-medium text-slate-900">Research agent</h2>
          <p className="text-xs text-slate-500 mt-0.5">
            Candidates come from your brand, competitors, personas and site content — nothing is tracked until you accept it.
          </p>
        </div>
        <button
          onClick={() => void generate()}
          disabled={busy}
          className="flex items-center px-3 py-1.5 bg-emerald-600 text-white rounded-lg hover:bg-emerald-700 transition text-sm font-medium disabled:opacity-60"
        >
          <Search className="w-3.5 h-3.5 mr-1.5" />
          {busy ? "Working…" : "Find candidates"}
        </button>
      </div>

      {error && <div className="text-sm text-rose-600 bg-rose-50 border border-rose-200 rounded-lg px-3 py-2">{error}</div>}
      {notice && <div className="text-sm text-slate-600 bg-slate-50 border border-slate-200 rounded-lg px-3 py-2">{notice}</div>}

      {candidates.length === 0 ? (
        <div className="text-sm text-slate-400">No pending candidates. Run the agent to propose some.</div>
      ) : (
        <ul className="divide-y divide-slate-100">
          {candidates.map((c) => (
            <li key={c.id} className="py-3">
              {editingId === c.id ? (
                <div className="space-y-2">
                  <textarea
                    value={editText}
                    onChange={(e) => setEditText(e.target.value)}
                    rows={2}
                    className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-slate-900"
                  />
                  <div className="flex gap-2">
                    <button
                      onClick={() => void accept(c, editText.trim() || undefined)}
                      disabled={busy}
                      className="px-3 py-1.5 bg-slate-900 text-white rounded text-xs font-medium disabled:opacity-60"
                    >
                      Save &amp; track
                    </button>
                    <button
                      onClick={() => setEditingId(null)}
                      className="px-3 py-1.5 border border-slate-200 rounded text-xs text-slate-600 hover:bg-slate-50"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              ) : (
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <div className="text-sm text-slate-800">{c.text}</div>
                    <div className="flex flex-wrap items-center gap-2 mt-1 text-xs text-slate-500">
                      <span className="capitalize px-1.5 py-0.5 rounded bg-slate-100 border border-slate-200">
                        {c.funnel_stage || "—"}
                      </span>
                      <span className="inline-flex items-center">
                        <Target className="w-3 h-3 text-emerald-500 mr-1" />
                        intent {c.lead_intent_score ?? "—"}
                      </span>
                      <span>{c.generator}</span>
                    </div>
                    {c.rationale && <div className="text-xs text-slate-400 mt-1">{c.rationale}</div>}
                  </div>
                  <div className="flex items-center gap-1.5 flex-shrink-0">
                    <button
                      onClick={() => void accept(c)}
                      disabled={busy}
                      title="Track as-is"
                      className="p-1.5 rounded bg-emerald-50 text-emerald-700 border border-emerald-200 hover:bg-emerald-100"
                    >
                      <Check className="w-4 h-4" />
                    </button>
                    <button
                      onClick={() => {
                        setEditingId(c.id);
                        setEditText(c.text);
                      }}
                      title="Edit then track"
                      className="p-1.5 rounded bg-slate-50 text-slate-600 border border-slate-200 hover:bg-slate-100"
                    >
                      <Pencil className="w-4 h-4" />
                    </button>
                    <button
                      onClick={() => void reject(c)}
                      disabled={busy}
                      title="Reject (keeps history)"
                      className="p-1.5 rounded bg-rose-50 text-rose-600 border border-rose-200 hover:bg-rose-100"
                    >
                      <X className="w-4 h-4" />
                    </button>
                  </div>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default function PromptsPage() {
  const [clientId, setClientId] = useState<string | null>(null);
  const [prompts, setPrompts] = useState<PromptListItem[]>([]);
  const [candidates, setCandidates] = useState<PromptCandidate[]>([]);
  const [health, setHealth] = useState<CollectionHealth | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [newText, setNewText] = useState("");
  const [newEngines, setNewEngines] = useState<EngineType[]>(["chatgpt", "gemini", "perplexity", "grok"]);
  const [saving, setSaving] = useState(false);
  const [collecting, setCollecting] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editText, setEditText] = useState("");

  async function load(id?: string) {
    try {
      const cid = id ?? (await getDefaultClientId());
      if (!id) setClientId(cid);
      const [list, pending, h] = await Promise.all([
        promptsApi.list(cid),
        researchApi.candidates(cid, "pending"),
        collectionApi.health(cid, 7),
      ]);
      setPrompts(list);
      setCandidates(pending);
      setHealth(h);
      setLoading(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load prompts");
      setLoading(false);
    }
  }

  useEffect(() => {
    void (async () => load())();
  }, []);

  async function onCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!newText.trim() || newEngines.length === 0 || !clientId) return;
    setSaving(true);
    try {
      await promptsApi.create(clientId, { text: newText.trim(), engines: newEngines });
      setNewText("");
      setShowForm(false);
      await load(clientId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create prompt");
    } finally {
      setSaving(false);
    }
  }

  async function runNow(promptId?: string) {
    if (!clientId) return;
    setCollecting(true);
    setError(null);
    try {
      const res = await collectionApi.runNow(clientId, promptId);
      setNotice(
        res.skipped_cap > 0
          ? `Scheduled ${res.scheduled} runs (${res.skipped_cap} skipped: daily cap).`
          : `Scheduled ${res.scheduled} run${res.scheduled === 1 ? "" : "s"} for collection now.`,
      );
      await load(clientId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Run now failed");
    } finally {
      setCollecting(false);
    }
  }

  async function toggleActive(prompt: PromptListItem) {
    if (!clientId) return;
    try {
      await promptsApi.update(clientId, prompt.id, { is_active: !prompt.is_active });
      await load(clientId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Update failed");
    }
  }

  async function saveEdit(prompt: PromptListItem) {
    if (!clientId || !editText.trim()) return;
    try {
      await promptsApi.update(clientId, prompt.id, { text: editText.trim() });
      setEditingId(null);
      await load(clientId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Update failed");
    }
  }

  function toggleEngine(engine: EngineType) {
    setNewEngines((prev) => (prev.includes(engine) ? prev.filter((e) => e !== engine) : [...prev, engine]));
  }

  const activeCount = prompts.filter((p) => p.is_active).length;

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-end">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight text-slate-900">Prompts</h1>
          <p className="text-slate-600 mt-1">
            Buyer queries tracked daily across engines.
            <span className="ml-2 text-slate-400">
              {activeCount} active of {MAX_ACTIVE_PROMPTS}
            </span>
          </p>
        </div>
        <button
          onClick={() => setShowForm((v) => !v)}
          className="flex items-center px-4 py-2 bg-slate-900 text-white rounded-lg hover:bg-slate-800 transition font-medium text-sm shadow-sm"
        >
          <Plus className="w-4 h-4 mr-2" />
          New Prompt
        </button>
      </div>

      {error && (
        <div className="text-sm text-rose-600 bg-rose-50 border border-rose-200 rounded-lg px-4 py-3">{error}</div>
      )}

      <CollectionHealthPanel health={health} onRunAll={() => void runNow()} running={collecting} />
      {notice && <div className="text-sm text-slate-600 bg-slate-50 border border-slate-200 rounded-lg px-4 py-3">{notice}</div>}

      {clientId && (
        <ResearchPanel
          clientId={clientId}
          candidates={candidates}
          onGenerated={() => void load(clientId)}
          onResolved={() => void load(clientId)}
        />
      )}

      {showForm && (
        <form onSubmit={onCreate} className="bg-white border border-slate-200 rounded-xl shadow-sm p-6 space-y-4">
          <div>
            <label htmlFor="prompt-text" className="block text-sm font-medium text-slate-700 mb-1">
              Prompt text
            </label>
            <textarea
              id="prompt-text"
              value={newText}
              onChange={(e) => setNewText(e.target.value)}
              rows={2}
              required
              placeholder="e.g. What is the best project management tool for startups?"
              className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-slate-900"
            />
          </div>
          <div>
            <span className="block text-sm font-medium text-slate-700 mb-2">Engines</span>
            <div className="flex gap-2 flex-wrap">
              {ALL_ENGINES.map((engine) => (
                <button
                  key={engine}
                  type="button"
                  onClick={() => toggleEngine(engine)}
                  className={`px-2.5 py-1 rounded text-xs capitalize border transition ${
                    newEngines.includes(engine)
                      ? "bg-slate-900 text-white border-slate-900"
                      : "bg-white text-slate-600 border-slate-200 hover:bg-slate-50"
                  }`}
                >
                  {engine.replace("_", " ")}
                </button>
              ))}
            </div>
          </div>
          <div className="flex gap-3">
            <button
              type="submit"
              disabled={saving || !newText.trim() || newEngines.length === 0}
              className="px-4 py-2 bg-slate-900 text-white rounded-lg hover:bg-slate-800 transition font-medium text-sm disabled:opacity-60"
            >
              {saving ? "Creating…" : "Create prompt"}
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
        <table className="w-full text-left text-sm">
          <thead className="bg-slate-50 border-b border-slate-200 text-slate-500">
            <tr>
              <th className="px-6 py-4 font-medium">Prompt Text</th>
              <th className="px-4 py-4 font-medium">Funnel</th>
              <th className="px-4 py-4 font-medium">Intent</th>
              <th className="px-4 py-4 font-medium">14d Visibility</th>
              <th className="px-4 py-4 font-medium">Engines</th>
              <th className="px-4 py-4 font-medium">Status</th>
              <th className="px-6 py-4 font-medium text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {loading ? (
              <tr>
                <td colSpan={7} className="px-6 py-8 text-center text-slate-400">
                  Loading prompts…
                </td>
              </tr>
            ) : prompts.length === 0 ? (
              <tr>
                <td colSpan={7} className="px-6 py-8 text-center text-slate-400">
                  No prompts yet — add one or let the research agent propose candidates above.
                </td>
              </tr>
            ) : (
              prompts.map((p) => (
                <Fragment key={p.id}>
                  <tr className="hover:bg-slate-50/50 transition-colors">
                    <td className="px-6 py-4 font-medium text-slate-900 max-w-md">
                      <Link href={`/ops/prompts/${p.id}`} className="hover:text-emerald-700 hover:underline">
                        {p.text}
                      </Link>
                      {p.source?.startsWith("research") && (
                        <span className="ml-2 px-1.5 py-0.5 rounded text-[10px] uppercase tracking-wide bg-indigo-50 text-indigo-600 border border-indigo-200">
                          research
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-4 capitalize text-slate-600">{p.funnel_stage || "—"}</td>
                    <td className="px-4 py-4">
                      <span className="inline-flex items-center text-slate-700">
                        <Target className="w-3.5 h-3.5 text-emerald-500 mr-1" />
                        {p.lead_intent_score ?? "—"}
                      </span>
                    </td>
                    <td className="px-4 py-4">
                      <Sparkline series={p.series} />
                    </td>
                    <td className="px-4 py-4">
                      <div className="flex gap-1.5 flex-wrap">
                        {p.engines.map((e) => {
                          const st = p.engine_status.find((s) => s.engine === e);
                          return (
                            <span
                              key={e}
                              className="px-2 py-0.5 bg-slate-100 text-slate-600 rounded text-xs capitalize border border-slate-200"
                              title={`${e}: ${st ? `${st.status} (${st.last_at ?? "never"})` : "no runs yet"}`}
                            >
                              <span className={`inline-block w-1.5 h-1.5 rounded-full mr-1 ${engineDot(st?.status)}`} />
                              {e.replace("_", " ")}
                            </span>
                          );
                        })}
                      </div>
                    </td>
                    <td className="px-4 py-4">
                      <span
                        className={`px-2.5 py-1 rounded-full text-xs font-medium ${
                          p.is_active
                            ? "bg-emerald-50 text-emerald-700 border border-emerald-200"
                            : "bg-slate-50 text-slate-600 border border-slate-200"
                        }`}
                      >
                        {p.is_active ? "Active" : "Retired"}
                      </span>
                    </td>
                    <td className="px-6 py-4 text-right whitespace-nowrap">
                      <button
                        onClick={() => void runNow(p.id)}
                        disabled={collecting || !p.is_active}
                        title="Collect this prompt now"
                        className="p-1.5 mr-1 rounded text-slate-400 hover:text-emerald-600 hover:bg-emerald-50 disabled:opacity-40"
                      >
                        <Play className="w-4 h-4" />
                      </button>
                      <button
                        onClick={() => {
                          setEditingId(p.id);
                          setEditText(p.text);
                        }}
                        title="Edit text"
                        className="p-1.5 mr-1 rounded text-slate-400 hover:text-slate-700 hover:bg-slate-100"
                      >
                        <Pencil className="w-4 h-4" />
                      </button>
                      <button
                        onClick={() => void toggleActive(p)}
                        title={p.is_active ? "Retire (keeps history)" : "Reactivate"}
                        className="p-1.5 rounded text-slate-400 hover:text-rose-600 hover:bg-rose-50"
                      >
                        <RotateCcw className="w-4 h-4" />
                      </button>
                    </td>
                  </tr>
                  {editingId === p.id && (
                    <tr className="bg-slate-50">
                      <td colSpan={7} className="px-6 py-3">
                        <div className="flex gap-2">
                          <input
                            value={editText}
                            onChange={(e) => setEditText(e.target.value)}
                            className="flex-1 px-3 py-1.5 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-slate-900"
                          />
                          <button
                            onClick={() => void saveEdit(p)}
                            className="px-3 py-1.5 bg-slate-900 text-white rounded-lg text-sm font-medium"
                          >
                            Save
                          </button>
                          <button
                            onClick={() => setEditingId(null)}
                            className="px-3 py-1.5 border border-slate-200 rounded-lg text-sm text-slate-600 bg-white"
                          >
                            Cancel
                          </button>
                        </div>
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
