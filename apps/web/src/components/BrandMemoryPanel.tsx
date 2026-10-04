"use client";

import { useState } from "react";
import { FileText, Globe, Loader2, Trash2 } from "lucide-react";
import { websites, type MemoryChunk } from "../lib/api";

interface BrandMemoryPanelProps {
  clientId: string;
  chunks: MemoryChunk[];
  onChanged: () => Promise<void> | void;
  /** True when the server has no embedding provider key configured. */
  providerMissing?: boolean;
}

/** Ingest documents/URLs into brand memory (chunked + embedded) and list them. */
export default function BrandMemoryPanel({
  clientId,
  chunks,
  onChanged,
  providerMissing,
}: BrandMemoryPanelProps) {
  const [kind, setKind] = useState<"url" | "text">("url");
  const [url, setUrl] = useState("");
  const [text, setText] = useState("");
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function onIngest(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const result = await websites.brandMemory.ingest(clientId, {
        kind,
        url: kind === "url" ? url.trim() : undefined,
        text: kind === "text" ? text : undefined,
        title: title.trim() || undefined,
      });
      setMessage(`Ingested “${result.title}” — ${result.chunks} chunk(s), ${result.tokens} tokens.`);
      setUrl("");
      setText("");
      setTitle("");
      await onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ingestion failed");
    } finally {
      setBusy(false);
    }
  }

  async function onDelete(chunkId: string) {
    setError(null);
    try {
      await websites.brandMemory.remove(clientId, chunkId);
      await onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete chunk");
    }
  }

  const inputClass =
    "w-full px-3 py-2 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-slate-900";

  return (
    <div className="space-y-6">
      {providerMissing && (
        <div className="text-sm text-amber-800 bg-amber-50 border border-amber-200 rounded-lg px-4 py-3">
          Embeddings are not configured on the server yet (<code className="font-mono text-xs">OPENAI_API_KEY</code>),
          so ingestion is disabled. Nothing is written until a real provider is configured.
        </div>
      )}

      <form onSubmit={onIngest} className="space-y-4">
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => setKind("url")}
            className={`px-3 py-1.5 rounded-lg text-sm font-medium border transition ${
              kind === "url" ? "bg-slate-900 text-white border-slate-900" : "bg-white text-slate-600 border-slate-200"
            }`}
          >
            From URL
          </button>
          <button
            type="button"
            onClick={() => setKind("text")}
            className={`px-3 py-1.5 rounded-lg text-sm font-medium border transition ${
              kind === "text" ? "bg-slate-900 text-white border-slate-900" : "bg-white text-slate-600 border-slate-200"
            }`}
          >
            Paste document
          </button>
        </div>

        {kind === "url" ? (
          <div>
            <label htmlFor="memory-url" className="block text-sm font-medium text-slate-700 mb-1">
              Page URL
            </label>
            <input
              id="memory-url"
              type="url"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              required
              placeholder="https://www.example.com/about"
              className={inputClass}
            />
          </div>
        ) : (
          <div>
            <label htmlFor="memory-text" className="block text-sm font-medium text-slate-700 mb-1">
              Document text
            </label>
            <textarea
              id="memory-text"
              value={text}
              onChange={(e) => setText(e.target.value)}
              required
              rows={5}
              placeholder="Paste a case study, service description, or any source material…"
              className={inputClass}
            />
          </div>
        )}

        <div>
          <label htmlFor="memory-title" className="block text-sm font-medium text-slate-700 mb-1">
            Title <span className="text-slate-400 font-normal">(optional)</span>
          </label>
          <input
            id="memory-title"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="e.g. Services overview"
            className={inputClass}
          />
        </div>

        <button
          type="submit"
          disabled={busy || providerMissing}
          className="inline-flex items-center px-4 py-2 bg-slate-900 text-white rounded-lg hover:bg-slate-800 transition font-medium text-sm disabled:opacity-60"
        >
          {busy ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : null}
          {busy ? "Embedding…" : "Ingest into brand memory"}
        </button>

        {message && (
          <div className="text-sm text-emerald-700 bg-emerald-50 border border-emerald-200 rounded-lg px-4 py-3">
            {message}
          </div>
        )}
        {error && (
          <div className="text-sm text-rose-600 bg-rose-50 border border-rose-200 rounded-lg px-4 py-3">{error}</div>
        )}
      </form>

      <div className="border border-slate-200 rounded-lg divide-y divide-slate-100">
        <div className="px-4 py-3 text-sm font-medium text-slate-700">
          Indexed chunks ({chunks.length})
        </div>
        {chunks.length === 0 ? (
          <div className="px-4 py-6 text-sm text-slate-400">
            Nothing ingested yet — add a page or document so agents can ground their work in it.
          </div>
        ) : (
          chunks.map((chunk) => (
            <div key={chunk.id} className="px-4 py-3 flex items-start gap-3">
              {chunk.source === "site" ? (
                <Globe className="w-4 h-4 text-slate-300 mt-0.5 shrink-0" />
              ) : (
                <FileText className="w-4 h-4 text-slate-300 mt-0.5 shrink-0" />
              )}
              <div className="min-w-0 flex-1">
                <div className="text-sm font-medium text-slate-800 truncate">{chunk.title ?? "Untitled"}</div>
                <div className="text-xs text-slate-500 mt-0.5 line-clamp-2">{chunk.preview}</div>
                <div className="text-xs text-slate-400 mt-0.5">
                  {chunk.source} · {chunk.created_at ? new Date(chunk.created_at).toLocaleString() : ""}
                </div>
              </div>
              <button
                type="button"
                onClick={() => void onDelete(chunk.id)}
                className="text-slate-300 hover:text-rose-500 shrink-0"
                aria-label="Delete chunk"
              >
                <Trash2 className="w-4 h-4" />
              </button>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
