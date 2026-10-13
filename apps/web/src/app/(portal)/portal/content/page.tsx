"use client";

import { useEffect, useState } from "react";
import {
  CheckCircle2,
  Clock,
  ExternalLink,
  FileText,
  Globe,
  Loader2,
  Search,
  ShieldCheck,
} from "lucide-react";
import {
  PortalContentItem,
  portalApi,
  getSelectedClientId,
} from "@/lib/api";

export default function PortalPublishedContentPage() {
  const [clientId, setClientId] = useState<string | null>(null);
  const [items, setItems] = useState<PortalContentItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchTerm, setSearchTerm] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const activeCid = getSelectedClientId() || undefined;
    portalApi.getMe(activeCid)
      .then(async (me) => {
        const resolvedCid = me.active_client_id || undefined;
        setClientId(resolvedCid || null);
        const contentList = await portalApi.listContent(resolvedCid);
        setItems(contentList);
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : "Failed to load content inventory");
      })
      .finally(() => {
        setLoading(false);
      });
  }, []);

  const filteredItems = items.filter((item) =>
    (item.title || "").toLowerCase().includes(searchTerm.toLowerCase()) ||
    (item.slug || "").toLowerCase().includes(searchTerm.toLowerCase())
  );

  return (
    <div className="space-y-6 max-w-6xl animate-in fade-in duration-300">
      <div>
        <h1 className="text-3xl font-semibold tracking-tight text-slate-900">Shipped Content</h1>
        <p className="text-slate-500 mt-1">
          Articles and answers published to your website with embedded Schema.org JSON-LD to power AI engine visibility.
        </p>
      </div>

      {error && (
        <div className="bg-rose-50 border border-rose-200 text-rose-800 px-4 py-3 rounded-xl text-xs">
          {error}
        </div>
      )}

      {/* Filter and stats banner */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div className="relative flex-1 max-w-sm">
          <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
          <input
            type="text"
            placeholder="Search published articles…"
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="w-full pl-9 pr-4 py-2 bg-white border border-slate-200 rounded-xl text-xs focus:outline-none focus:ring-2 focus:ring-slate-900/10 focus:border-slate-900"
          />
        </div>

        <div className="flex items-center gap-3 text-xs text-slate-600">
          <span className="bg-white border border-slate-200 px-3 py-1.5 rounded-lg shadow-2xs">
            <strong>{items.length}</strong> Total Pieces
          </span>
          <span className="bg-white border border-slate-200 px-3 py-1.5 rounded-lg shadow-2xs flex items-center gap-1.5">
            <ShieldCheck className="w-3.5 h-3.5 text-emerald-600" /> Grounded Citations
          </span>
        </div>
      </div>

      {loading ? (
        <div className="h-64 flex flex-col items-center justify-center text-slate-400 gap-2">
          <Loader2 className="w-6 h-6 animate-spin text-slate-600" />
          <span className="text-xs">Loading content pieces…</span>
        </div>
      ) : filteredItems.length === 0 ? (
        <div className="bg-white border border-slate-200 rounded-2xl p-12 text-center shadow-xs">
          <Globe className="w-10 h-10 text-slate-300 mx-auto mb-3" />
          <h3 className="text-base font-semibold text-slate-800">No Content Found</h3>
          <p className="text-xs text-slate-500 max-w-md mx-auto mt-1 mb-4">
            Articles will appear here once drafts are created and approved by your team.
          </p>
        </div>
      ) : (
        <div className="grid gap-3">
          {filteredItems.map((item) => {
            const isLive = item.status === "published";

            return (
              <div
                key={item.id}
                className="bg-white border border-slate-200 rounded-2xl p-5 shadow-xs hover:border-slate-300 transition flex flex-col md:flex-row md:items-center justify-between gap-4"
              >
                <div className="space-y-1.5">
                  <div className="flex items-center gap-2 flex-wrap">
                    <h2 className="font-semibold text-base text-slate-900 leading-snug">
                      {item.title}
                    </h2>
                    <span className={`px-2.5 py-0.5 rounded-full text-[11px] font-medium border ${
                      isLive
                        ? "bg-emerald-50 text-emerald-800 border-emerald-200"
                        : item.status === "approved"
                        ? "bg-blue-50 text-blue-800 border-blue-200"
                        : "bg-slate-100 text-slate-700 border-slate-200"
                    }`}>
                      {item.status.replace("_", " ").toUpperCase()}
                    </span>
                    {isLive && (
                      <span className="inline-flex items-center gap-1 text-[11px] font-medium text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded-md border border-emerald-100">
                        <CheckCircle2 className="w-3 h-3 text-emerald-600" /> Schema Verified
                      </span>
                    )}
                  </div>

                  <div className="text-xs text-slate-500 flex items-center gap-3 flex-wrap">
                    <span>
                      {item.published_at ? (
                        <>Published: {new Date(item.published_at).toLocaleDateString()}</>
                      ) : (
                        <>Created: {new Date(item.created_at).toLocaleDateString()}</>
                      )}
                    </span>
                    {item.word_count > 0 && (
                      <span>&bull; {item.word_count} words</span>
                    )}
                    {item.type && (
                      <span>
                        &bull; Type: <span className="uppercase font-medium">{item.type}</span>
                      </span>
                    )}
                    {item.slug && (
                      <span className="font-mono text-slate-400">
                        &bull; /{item.slug}
                      </span>
                    )}
                  </div>
                </div>

                <div className="flex items-center gap-2 self-end md:self-center">
                  {item.published_url ? (
                    <a
                      href={item.published_url}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex items-center gap-1.5 px-4 py-2 bg-slate-900 hover:bg-slate-800 text-white text-xs font-medium rounded-xl shadow-xs transition"
                    >
                      <ExternalLink className="w-3.5 h-3.5" />
                      View Live Article
                    </a>
                  ) : (
                    <span className="text-xs text-slate-400 font-medium">Internal preview</span>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
