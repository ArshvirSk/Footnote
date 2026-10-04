"use client";

import { useState } from "react";
import { Pencil, Plus, Trash2 } from "lucide-react";
import { api, websites, type Persona } from "../lib/api";

interface PersonasPanelProps {
  clientId: string;
  personas: Persona[];
  onChanged: () => Promise<void> | void;
}

/** Buyer personas: create, edit and delete. */
export default function PersonasPanel({ clientId, personas, onChanged }: PersonasPanelProps) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editName, setEditName] = useState("");
  const [editDescription, setEditDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const inputClass =
    "w-full px-3 py-2 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-slate-900";

  async function onCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await websites.personas.create(clientId, {
        name: name.trim(),
        description: description.trim() || undefined,
      });
      setName("");
      setDescription("");
      await onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to add persona");
    } finally {
      setBusy(false);
    }
  }

  async function saveEdit(personaId: string) {
    setBusy(true);
    setError(null);
    try {
      await api.patch<Persona>(`/clients/${clientId}/personas/${personaId}`, {
        name: editName.trim(),
        description: editDescription.trim(),
      });
      setEditingId(null);
      await onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update persona");
    } finally {
      setBusy(false);
    }
  }

  async function onDelete(personaId: string) {
    setError(null);
    try {
      await websites.personas.remove(clientId, personaId);
      await onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete persona");
    }
  }

  return (
    <div className="space-y-4">
      {error && (
        <div className="text-sm text-rose-600 bg-rose-50 border border-rose-200 rounded-lg px-4 py-3">{error}</div>
      )}

      <div className="border border-slate-200 rounded-lg divide-y divide-slate-100">
        {personas.length === 0 ? (
          <div className="px-4 py-6 text-sm text-slate-400">
            No personas yet — define who the tracked prompts are written for.
          </div>
        ) : (
          personas.map((p) => (
            <div key={p.id} className="px-4 py-3">
              {editingId === p.id ? (
                <div className="space-y-2">
                  <input
                    value={editName}
                    onChange={(e) => setEditName(e.target.value)}
                    placeholder="Persona name"
                    className={inputClass}
                  />
                  <textarea
                    value={editDescription}
                    onChange={(e) => setEditDescription(e.target.value)}
                    rows={2}
                    placeholder="Description"
                    className={inputClass}
                  />
                  <div className="flex gap-2">
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => void saveEdit(p.id)}
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
                <div className="flex items-start gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="text-sm font-medium text-slate-800">{p.name}</div>
                    {p.description && <div className="text-xs text-slate-500 mt-0.5">{p.description}</div>}
                  </div>
                  <button
                    type="button"
                    onClick={() => {
                      setEditingId(p.id);
                      setEditName(p.name);
                      setEditDescription(p.description ?? "");
                    }}
                    className="text-slate-400 hover:text-slate-600"
                    aria-label={`Edit ${p.name}`}
                  >
                    <Pencil className="w-4 h-4" />
                  </button>
                  <button
                    type="button"
                    onClick={() => void onDelete(p.id)}
                    className="text-slate-300 hover:text-rose-500"
                    aria-label={`Delete ${p.name}`}
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              )}
            </div>
          ))
        )}
      </div>

      <form onSubmit={onCreate} className="grid grid-cols-1 sm:grid-cols-[1fr_2fr_auto] gap-2 items-start">
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Persona name"
          required
          className={inputClass}
        />
        <input
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="Description (role, context, pains)"
          className={inputClass}
        />
        <button
          type="submit"
          disabled={busy || !name.trim()}
          className="inline-flex items-center px-3 py-2 bg-slate-900 text-white rounded-lg text-sm font-medium disabled:opacity-60"
        >
          <Plus className="w-4 h-4 mr-1" /> Add
        </button>
      </form>
    </div>
  );
}
