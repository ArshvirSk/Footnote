"use client";

import { useState } from "react";
import { Pencil, Plus, Trash2, X } from "lucide-react";
import { api, websites, type Competitor } from "../lib/api";

interface CompetitorsPanelProps {
  clientId: string;
  competitors: Competitor[];
  onChanged: () => Promise<void> | void;
}

interface Draft {
  name: string;
  domain: string;
  aliases: string;
}

const EMPTY: Draft = { name: "", domain: "", aliases: "" };

/** Competitors list with aliases; create, edit (PATCH) and delete. */
export default function CompetitorsPanel({ clientId, competitors, onChanged }: CompetitorsPanelProps) {
  const [draft, setDraft] = useState<Draft>(EMPTY);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editDraft, setEditDraft] = useState<Draft>(EMPTY);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const inputClass =
    "w-full px-3 py-2 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-slate-900";

  async function onCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!draft.name.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await websites.competitors.create(clientId, {
        name: draft.name.trim(),
        domain: draft.domain.trim() || undefined,
        aliases: draft.aliases
          .split(",")
          .map((a) => a.trim())
          .filter(Boolean),
      });
      setDraft(EMPTY);
      await onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to add competitor");
    } finally {
      setBusy(false);
    }
  }

  function startEdit(competitor: Competitor) {
    setEditingId(competitor.id);
    setEditDraft({
      name: competitor.name,
      domain: competitor.domain ?? "",
      aliases: competitor.aliases.join(", "),
    });
  }

  async function saveEdit(competitorId: string) {
    setBusy(true);
    setError(null);
    try {
      await api.patch<Competitor>(`/clients/${clientId}/competitors/${competitorId}`, {
        name: editDraft.name.trim(),
        domain: editDraft.domain.trim() || "",
        aliases: editDraft.aliases
          .split(",")
          .map((a) => a.trim())
          .filter(Boolean),
      });
      setEditingId(null);
      await onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update competitor");
    } finally {
      setBusy(false);
    }
  }

  async function onDelete(competitorId: string) {
    setError(null);
    try {
      await websites.competitors.remove(clientId, competitorId);
      await onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete competitor");
    }
  }

  return (
    <div className="space-y-4">
      {error && (
        <div className="text-sm text-rose-600 bg-rose-50 border border-rose-200 rounded-lg px-4 py-3">{error}</div>
      )}

      <div className="border border-slate-200 rounded-lg divide-y divide-slate-100">
        {competitors.length === 0 ? (
          <div className="px-4 py-6 text-sm text-slate-400">
            No competitors yet — add the brands that appear in AI answers for your prompts.
          </div>
        ) : (
          competitors.map((c) => (
            <div key={c.id} className="px-4 py-3">
              {editingId === c.id ? (
                <div className="space-y-2">
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                    <input
                      value={editDraft.name}
                      onChange={(e) => setEditDraft({ ...editDraft, name: e.target.value })}
                      placeholder="Name"
                      className={inputClass}
                    />
                    <input
                      value={editDraft.domain}
                      onChange={(e) => setEditDraft({ ...editDraft, domain: e.target.value })}
                      placeholder="Domain"
                      className={inputClass}
                    />
                  </div>
                  <input
                    value={editDraft.aliases}
                    onChange={(e) => setEditDraft({ ...editDraft, aliases: e.target.value })}
                    placeholder="Aliases (comma-separated)"
                    className={inputClass}
                  />
                  <div className="flex gap-2">
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => void saveEdit(c.id)}
                      className="px-3 py-1.5 bg-slate-900 text-white rounded-lg text-xs font-medium disabled:opacity-60"
                    >
                      Save
                    </button>
                    <button
                      type="button"
                      onClick={() => setEditingId(null)}
                      className="px-3 py-1.5 border border-slate-200 text-slate-600 rounded-lg text-xs font-medium"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              ) : (
                <div className="flex items-center gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="text-sm font-medium text-slate-800">{c.name}</div>
                    <div className="text-xs text-slate-400">
                      {c.domain ?? "no domain"}
                      {c.aliases.length > 0 ? ` · aliases: ${c.aliases.join(", ")}` : ""}
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => startEdit(c)}
                    className="text-slate-400 hover:text-slate-600"
                    aria-label={`Edit ${c.name}`}
                  >
                    <Pencil className="w-4 h-4" />
                  </button>
                  <button
                    type="button"
                    onClick={() => void onDelete(c.id)}
                    className="text-slate-300 hover:text-rose-500"
                    aria-label={`Delete ${c.name}`}
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              )}
            </div>
          ))
        )}
      </div>

      <form onSubmit={onCreate} className="grid grid-cols-1 sm:grid-cols-[1fr_1fr_1fr_auto] gap-2 items-start">
        <input
          value={draft.name}
          onChange={(e) => setDraft({ ...draft, name: e.target.value })}
          placeholder="Competitor name"
          required
          className={inputClass}
        />
        <input
          value={draft.domain}
          onChange={(e) => setDraft({ ...draft, domain: e.target.value })}
          placeholder="Domain"
          className={inputClass}
        />
        <input
          value={draft.aliases}
          onChange={(e) => setDraft({ ...draft, aliases: e.target.value })}
          placeholder="Aliases, comma-separated"
          className={inputClass}
        />
        <button
          type="submit"
          disabled={busy || !draft.name.trim()}
          className="inline-flex items-center px-3 py-2 bg-slate-900 text-white rounded-lg text-sm font-medium disabled:opacity-60"
        >
          {busy ? <X className="w-4 h-4" /> : <Plus className="w-4 h-4 mr-1" />}
          Add
        </button>
      </form>
    </div>
  );
}
