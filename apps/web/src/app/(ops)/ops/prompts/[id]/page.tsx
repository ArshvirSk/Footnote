"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import {
  AlertCircle,
  ArrowLeft,
  Check,
  ChevronDown,
  ChevronRight,
  Pencil,
  Play,
  RefreshCw,
  RotateCcw,
  Target,
} from "lucide-react";
import {
  collectionApi,
  getDefaultClientId,
  promptsApi,
  type AnswerCitation,
  type AnswerMention,
  type PromptAnswer,
  type PromptListItem,
} from "../../../../../lib/api";
import { formatDateTime, pct } from "../../../../../lib/ui";

const STATUS_CLASS: Record<string, string> = {
  succeeded: "bg-emerald-50 text-emerald-700 border-emerald-200",
  failed: "bg-rose-50 text-rose-700 border-rose-200",
  queued: "bg-amber-50 text-amber-700 border-amber-200",
  running: "bg-sky-50 text-sky-700 border-sky-200",
};

function runStatusClass(status: string): string {
  return STATUS_CLASS[status] ?? "bg-slate-100 text-slate-600 border-slate-200";
}

function engineDotClass(status: string | undefined): string {
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

function MentionBadges({ mentions }: { mentions: AnswerMention[] }) {
  if (mentions.length === 0) return <span className="text-xs text-slate-400">No brand/competitor mentions</span>;
  return (
    <div className="flex flex-wrap gap-1.5">
      {mentions.map((m, i) => (
        <span
          key={`${m.entity_kind}-${m.competitor_id ?? i}`}
          className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs border ${
            m.entity_kind === "brand"
              ? "bg-emerald-50 text-emerald-700 border-emerald-200"
              : "bg-rose-50 text-rose-700 border-rose-200"
          }`}
          title={m.excerpt ?? undefined}
        >
          <span className="font-medium capitalize">{m.entity_kind}</span>
          {m.recommended && <span className="text-[10px] uppercase tracking-wide">recommended</span>}
          {m.sentiment && <span className="text-[10px]">· {m.sentiment}</span>}
          {m.linked && <span className="text-[10px]">· linked</span>}
        </span>
      ))}
    </div>
  );
}

function Citations({ citations }: { citations: AnswerCitation[] }) {
  if (citations.length === 0) return <span className="text-xs text-slate-400">No citations extracted</span>;
  return (
    <ul className="space-y-1">
      {citations.map((c) => (
        <li key={`${c.url}-${c.position ?? 0}`} className="flex items-start gap-1.5 text-xs">
          {c.is_brand_owned ? (
            <Check className="w-3.5 h-3.5 text-emerald-500 mt-0.5 flex-shrink-0" />
          ) : c.competitor_id ? (
            <AlertCircle className="w-3.5 h-3.5 text-rose-500 mt-0.5 flex-shrink-0" />
          ) : (
            <span className="w-3.5 text-center text-slate-300 flex-shrink-0">·</span>
          )}
          <a
            href={c.url}
            target="_blank"
            rel="noopener noreferrer"
            className={`truncate hover:underline ${c.is_brand_owned ? "text-emerald-700" : "text-slate-600"}`}
          >
            {c.title || c.url}
          </a>
        </li>
      ))}
    </ul>
  );
}

function AnswerCard({ answer, index }: { answer: PromptAnswer; index: number }) {
  const [expanded, setExpanded] = useState(index === 0);
  const brandMentioned = answer.mentions.some((m) => m.entity_kind === "brand");

  return (
    <div className="border border-slate-200 rounded-xl bg-white shadow-sm overflow-hidden">
      <button
        onClick={() => setExpanded((v) => !v)}
        className="w-full flex items-center justify-between gap-3 px-4 py-3 text-left hover:bg-slate-50/60"
      >
        <div className="flex items-center gap-2 flex-wrap text-sm">
          {expanded ? <ChevronDown className="w-4 h-4 text-slate-400" /> : <ChevronRight className="w-4 h-4 text-slate-400" />}
          <span className="font-medium text-slate-900 capitalize">{answer.engine.replace("_", " ")}</span>
          <span className="text-slate-400 text-xs">run {answer.run_index}</span>
          <span className={`px-2 py-0.5 rounded-full text-xs font-medium border ${runStatusClass(answer.status)}`}>
            {answer.status}
          </span>
          {answer.status === "succeeded" && (
            <span
              className={`px-2 py-0.5 rounded-full text-xs border ${
                brandMentioned
                  ? "bg-emerald-50 text-emerald-700 border-emerald-200"
                  : "bg-slate-50 text-slate-500 border-slate-200"
              }`}
            >
              {brandMentioned ? "brand mentioned" : "brand absent"}
            </span>
          )}
          {answer.mock && (
            <span className="px-2 py-0.5 rounded-full text-xs bg-amber-50 text-amber-700 border border-amber-200">mock</span>
          )}
        </div>
        <div className="text-xs text-slate-400 whitespace-nowrap">
          {answer.day ?? "—"} {answer.latency_ms !== null ? `· ${answer.latency_ms} ms` : ""}
          {answer.attempts > 1 ? ` · ${answer.attempts} tries` : ""}
        </div>
      </button>

      {expanded && (
        <div className="border-t border-slate-100 px-4 py-4 space-y-4">
          {answer.error && (
            <div className="text-xs text-rose-700 bg-rose-50 border border-rose-200 rounded-lg px-3 py-2 whitespace-pre-wrap">
              {answer.error}
            </div>
          )}

          {answer.raw_text ? (
            <div>
              <div className="text-xs font-medium text-slate-500 uppercase tracking-wide mb-1.5">Raw answer</div>
              <div className="text-sm text-slate-700 whitespace-pre-wrap bg-slate-50 border border-slate-100 rounded-lg p-3 max-h-96 overflow-y-auto">
                {answer.raw_text}
              </div>
            </div>
          ) : (
            answer.status === "succeeded" && <div className="text-xs text-slate-400">No raw text stored.</div>
          )}

          <div className="grid md:grid-cols-2 gap-4">
            <div>
              <div className="text-xs font-medium text-slate-500 uppercase tracking-wide mb-1.5">
                Mentions ({answer.mentions.length})
              </div>
              <MentionBadges mentions={answer.mentions} />
            </div>
            <div>
              <div className="text-xs font-medium text-slate-500 uppercase tracking-wide mb-1.5">
                Citations ({answer.citations.length})
              </div>
              <Citations citations={answer.citations} />
            </div>
          </div>

          <div className="flex flex-wrap gap-x-6 gap-y-1 text-xs text-slate-400 border-t border-slate-100 pt-3">
            <span>model: {answer.model_label ?? "—"}</span>
            <span>judge: {answer.judge_version ?? "—"}</span>
            <span>geo: {answer.geo ?? "—"}</span>
            <span>collected: {formatDateTime(answer.collected_at)}</span>
          </div>
        </div>
      )}
    </div>
  );
}

export default function PromptDetailPage() {
  const params = useParams<{ id: string }>();
  const promptId = params.id;
  const [clientId, setClientId] = useState<string | null>(null);
  const [prompt, setPrompt] = useState<PromptListItem | null>(null);
  const [answers, setAnswers] = useState<PromptAnswer[]>([]);
  const [days, setDays] = useState(14);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [collecting, setCollecting] = useState(false);
  const [editing, setEditing] = useState(false);
  const [editText, setEditText] = useState("");

  const load = useCallback(
    async (windowDays: number, cid?: string) => {
      try {
        const client = cid ?? (await getDefaultClientId());
        if (!cid) setClientId(client);
        const [list, runs] = await Promise.all([
          promptsApi.list(client),
          collectionApi.answers(client, promptId, windowDays),
        ]);
        const found = list.find((p) => p.id === promptId);
        if (!found) throw new Error("Prompt not found");
        setPrompt(found);
        setAnswers(runs);
        setError(null);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load prompt");
      } finally {
        setLoading(false);
      }
    },
    [promptId],
  );

  useEffect(() => {
    // Initial window is 14 days; changeDays reloads explicitly for other windows.
    void (async () => load(14))();
  }, [load]);

  async function changeDays(next: number) {
    setDays(next);
    await load(next, clientId ?? undefined);
  }

  async function runNow() {
    if (!clientId || !prompt) return;
    setCollecting(true);
    setError(null);
    setNotice(null);
    try {
      const res = await collectionApi.runNow(clientId, prompt.id);
      setNotice(
        res.scheduled + res.already_scheduled === 0
          ? "Nothing to schedule — the daily cap was reached."
          : res.already_scheduled > 0 && res.scheduled === 0
            ? `Today's ${res.already_scheduled} runs already exist; nothing new scheduled.`
            : `Scheduled ${res.scheduled} run${res.scheduled === 1 ? "" : "s"} — collecting…`,
      );
      // The API drains the in-process queue in a background task after responding.
      window.setTimeout(() => void load(days, clientId ?? undefined), 1500);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Run now failed");
    } finally {
      setCollecting(false);
    }
  }

  async function saveEdit() {
    if (!clientId || !prompt || !editText.trim()) return;
    try {
      await promptsApi.update(clientId, prompt.id, { text: editText.trim() });
      setEditing(false);
      await load(days, clientId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Update failed");
    }
  }

  async function toggleActive() {
    if (!clientId || !prompt) return;
    try {
      await promptsApi.update(clientId, prompt.id, { is_active: !prompt.is_active });
      await load(days, clientId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Update failed");
    }
  }

  if (loading) return <div className="text-slate-400 text-sm">Loading prompt…</div>;
  if (error && !prompt) {
    return (
      <div className="space-y-4">
        <div className="text-sm text-rose-600 bg-rose-50 border border-rose-200 rounded-lg px-4 py-3">{error}</div>
        <Link href="/ops/prompts" className="text-sm text-blue-600 hover:underline">
          Back to prompts
        </Link>
      </div>
    );
  }
  if (!prompt) return null;

  const succeeded = answers.filter((a) => a.status === "succeeded");
  const mentioned = succeeded.filter((a) => a.mentions.some((m) => m.entity_kind === "brand"));
  const mentionRate = succeeded.length > 0 ? mentioned.length / succeeded.length : null;
  const citationCount = succeeded.reduce((sum, a) => sum + a.citations.length, 0);
  const brandCitations = succeeded.reduce((sum, a) => sum + a.citations.filter((c) => c.is_brand_owned).length, 0);
  const failed = answers.filter((a) => a.status === "failed");

  return (
    <div className="space-y-6">
      <Link href="/ops/prompts" className="inline-flex items-center text-sm text-slate-500 hover:text-slate-700">
        <ArrowLeft className="w-4 h-4 mr-1" /> All prompts
      </Link>

      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div className="max-w-3xl">
          {editing ? (
            <div className="flex gap-2">
              <input
                value={editText}
                onChange={(e) => setEditText(e.target.value)}
                className="flex-1 px-3 py-2 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-slate-900"
              />
              <button onClick={() => void saveEdit()} className="px-3 py-2 bg-slate-900 text-white rounded-lg text-sm font-medium">
                Save
              </button>
              <button
                onClick={() => setEditing(false)}
                className="px-3 py-2 border border-slate-200 rounded-lg text-sm text-slate-600 bg-white"
              >
                Cancel
              </button>
            </div>
          ) : (
            <h1 className="text-2xl font-semibold tracking-tight text-slate-900">{prompt.text}</h1>
          )}
          <div className="flex flex-wrap items-center gap-2 mt-2 text-xs text-slate-500">
            <span
              className={`px-2 py-0.5 rounded-full border font-medium ${
                prompt.is_active
                  ? "bg-emerald-50 text-emerald-700 border-emerald-200"
                  : "bg-slate-100 text-slate-600 border-slate-200"
              }`}
            >
              {prompt.is_active ? "Active" : "Retired"}
            </span>
            {prompt.funnel_stage && (
              <span className="px-2 py-0.5 rounded bg-slate-100 border border-slate-200 capitalize">
                {prompt.funnel_stage}
              </span>
            )}
            {prompt.lead_intent_score !== null && (
              <span className="inline-flex items-center">
                <Target className="w-3.5 h-3.5 text-emerald-500 mr-1" /> intent {prompt.lead_intent_score}
              </span>
            )}
            {prompt.source && <span>source: {prompt.source}</span>}
            {prompt.retired_at && <span>retired {formatDateTime(prompt.retired_at)}</span>}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => void runNow()}
            disabled={collecting || !prompt.is_active}
            className="flex items-center px-3 py-2 bg-slate-900 text-white rounded-lg hover:bg-slate-800 transition text-sm font-medium disabled:opacity-60"
          >
            <Play className="w-4 h-4 mr-1.5" />
            {collecting ? "Scheduling…" : "Run now"}
          </button>
          <button
            onClick={() => {
              setEditing((v) => !v);
              setEditText(prompt.text);
            }}
            title="Edit text"
            className="p-2 rounded-lg border border-slate-200 text-slate-600 hover:bg-slate-50"
          >
            <Pencil className="w-4 h-4" />
          </button>
          <button
            onClick={() => void toggleActive()}
            title={prompt.is_active ? "Retire (keeps history)" : "Reactivate"}
            className="p-2 rounded-lg border border-slate-200 text-slate-600 hover:bg-slate-50"
          >
            <RotateCcw className="w-4 h-4" />
          </button>
          <button
            onClick={() => void load(days, clientId ?? undefined)}
            title="Refresh"
            className="p-2 rounded-lg border border-slate-200 text-slate-600 hover:bg-slate-50"
          >
            <RefreshCw className="w-4 h-4" />
          </button>
        </div>
      </div>

      {error && (
        <div className="text-sm text-rose-600 bg-rose-50 border border-rose-200 rounded-lg px-4 py-3">{error}</div>
      )}
      {notice && <div className="text-sm text-slate-600 bg-slate-50 border border-slate-200 rounded-lg px-4 py-3">{notice}</div>}

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-4">
          <div className="text-xs text-slate-500">Runs in window</div>
          <div className="text-xl font-semibold text-slate-900 mt-1">{answers.length}</div>
        </div>
        <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-4">
          <div className="text-xs text-slate-500">Mention rate</div>
          <div className="text-xl font-semibold text-slate-900 mt-1">{pct(mentionRate)}</div>
          {succeeded.length > 0 && (
            <div className="text-xs text-slate-400 mt-0.5">
              {mentioned.length} of {succeeded.length} succeeded
            </div>
          )}
        </div>
        <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-4">
          <div className="text-xs text-slate-500">Brand citations</div>
          <div className="text-xl font-semibold text-slate-900 mt-1">
            {brandCitations}
            <span className="text-sm font-normal text-slate-400"> / {citationCount}</span>
          </div>
        </div>
        <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-4">
          <div className="text-xs text-slate-500">Failed runs</div>
          <div className={`text-xl font-semibold mt-1 ${failed.length > 0 ? "text-rose-600" : "text-slate-900"}`}>
            {failed.length}
          </div>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        {prompt.engine_status.map((s) => (
          <span
            key={s.engine}
            className="px-2.5 py-1 rounded border border-slate-200 bg-slate-50 text-xs text-slate-600 capitalize"
            title={s.last_at ? `last run ${formatDateTime(s.last_at)}` : "no runs yet"}
          >
            <span className={`inline-block w-1.5 h-1.5 rounded-full mr-1.5 ${engineDotClass(s.status)}`} />
            {s.engine.replace("_", " ")}: {s.status}
          </span>
        ))}
        <span className="flex-1" />
        {[7, 14, 30].map((d) => (
          <button
            key={d}
            onClick={() => void changeDays(d)}
            className={`px-2.5 py-1 rounded text-xs border transition ${
              days === d ? "bg-slate-900 text-white border-slate-900" : "bg-white text-slate-600 border-slate-200 hover:bg-slate-50"
            }`}
          >
            {d}d
          </button>
        ))}
      </div>

      <div className="space-y-3">
        {answers.length === 0 ? (
          <div className="bg-white border border-slate-200 rounded-xl shadow-sm px-6 py-10 text-center text-sm text-slate-400">
            No runs in the last {days} days. Use <span className="font-medium text-slate-600">Run now</span> to collect.
          </div>
        ) : (
          answers.map((a, i) => <AnswerCard key={a.id} answer={a} index={i} />)
        )}
      </div>
    </div>
  );
}
