"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { ArrowLeft, ExternalLink } from "lucide-react";
import {
  websites,
  type BrandProfile,
  type ClientSummary,
  type Competitor,
  type MemoryChunk,
  type Persona,
  type SetupResponse,
} from "../../../../../lib/api";
import BrandMemoryPanel from "../../../../../components/BrandMemoryPanel";
import BrandProfileForm from "../../../../../components/BrandProfileForm";
import CompetitorsPanel from "../../../../../components/CompetitorsPanel";
import DemoBadge from "../../../../../components/DemoBadge";
import PersonasPanel from "../../../../../components/PersonasPanel";
import SetupChecklist from "../../../../../components/SetupChecklist";
import { formatDateTime, pct, statusBadgeClass, statusLabel } from "../../../../../lib/ui";

interface PageData {
  client: ClientSummary;
  setup: SetupResponse;
  profile: BrandProfile;
  memory: MemoryChunk[];
  competitors: Competitor[];
  personas: Persona[];
}

export default function WebsiteDetailPage() {
  const params = useParams<{ id: string }>();
  const clientId = params.id;
  const [data, setData] = useState<PageData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const list = await websites.list(true);
      const client = list.find((c) => c.id === clientId);
      if (!client) throw new Error("Website not found");
      const [setup, profile, memory, competitors, personas] = await Promise.all([
        websites.setup(clientId),
        websites.brandProfile.get(clientId),
        websites.brandMemory.list(clientId),
        websites.competitors.list(clientId),
        websites.personas.list(clientId),
      ]);
      setData({ client, setup, profile, memory, competitors, personas });
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load website");
    } finally {
      setLoading(false);
    }
  }, [clientId]);

  useEffect(() => {
    // Async IIFE keeps setState out of the synchronous effect body.
    void (async () => {
      await load();
    })();
  }, [load]);

  if (loading) return <div className="text-slate-400 text-sm">Loading website…</div>;
  if (error && !data) {
    return (
      <div className="space-y-4">
        <div className="text-sm text-rose-600 bg-rose-50 border border-rose-200 rounded-lg px-4 py-3">{error}</div>
        <Link href="/ops/websites" className="text-sm text-blue-600 hover:underline">
          Back to websites
        </Link>
      </div>
    );
  }
  if (!data) return null;

  const { client, setup, profile, memory, competitors, personas } = data;

  const sectionCard = "bg-white border border-slate-200 rounded-xl shadow-sm";

  return (
    <div className="space-y-6 max-w-5xl">
      <Link href="/ops/websites" className="inline-flex items-center text-sm text-slate-500 hover:text-slate-700">
        <ArrowLeft className="w-4 h-4 mr-1" /> All websites
      </Link>

      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <div className="flex items-center gap-3 flex-wrap">
            <h1 className="text-3xl font-semibold tracking-tight text-slate-900">{client.name}</h1>
            <span className={`px-2.5 py-1 rounded-full text-xs font-medium border ${statusBadgeClass(client.derived_status)}`}>
              {statusLabel(client.derived_status)}
            </span>
            {client.is_demo && <DemoBadge />}
          </div>
          <div className="text-slate-500 mt-1 flex items-center gap-2">
            <span>{client.primary_domain}</span>
            <a
              href={`https://${client.primary_domain}`}
              target="_blank"
              rel="noopener noreferrer"
              className="text-slate-400 hover:text-slate-600"
              aria-label="Open live site"
            >
              <ExternalLink className="w-3.5 h-3.5" />
            </a>
          </div>
        </div>
        <Link
          href="/ops/site-audit"
          className="px-4 py-2 bg-white border border-slate-200 text-slate-700 rounded-lg hover:bg-slate-50 transition font-medium text-sm"
        >
          Open site audit →
        </Link>
      </div>

      {error && (
        <div className="text-sm text-rose-600 bg-rose-50 border border-rose-200 rounded-lg px-4 py-3">{error}</div>
      )}

      {/* Summary tiles */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
        <div className={sectionCard + " p-4"}>
          <div className="text-xs text-slate-500">Setup</div>
          <div className="text-xl font-semibold text-slate-900 mt-1">
            {setup.progress}/{setup.total}
          </div>
        </div>
        <div className={sectionCard + " p-4"}>
          <div className="text-xs text-slate-500">Last collection</div>
          <div className="text-sm font-medium text-slate-900 mt-1">
            {formatDateTime(client.last_collection_at)}
          </div>
        </div>
        <div className={sectionCard + " p-4"}>
          <div className="text-xs text-slate-500">Visibility 7d</div>
          <div className="text-xl font-semibold text-slate-900 mt-1">{pct(client.visibility_pct)}</div>
        </div>
        <div className={sectionCard + " p-4"}>
          <div className="text-xs text-slate-500">Open issues</div>
          <div className="text-xl font-semibold text-slate-900 mt-1">
            {client.open_issues > 0 ? <span className="text-amber-700">{client.open_issues}</span> : 0}
          </div>
        </div>
        <div className={sectionCard + " p-4"}>
          <div className="text-xs text-slate-500">Pending approvals</div>
          <div className="text-xl font-semibold text-slate-900 mt-1">{client.pending_approvals}</div>
        </div>
      </div>

      {/* Setup checklist */}
      <section id="setup">
        <SetupChecklist items={setup.items} progress={setup.progress} total={setup.total} />
      </section>

      {/* Brand profile */}
      <section id="brand" className={sectionCard + " p-6"}>
        <div className="mb-4">
          <h2 className="font-medium text-slate-900">Brand profile</h2>
          <p className="text-sm text-slate-500 mt-0.5">
            The source of truth every agent uses. Proof points need a source URL; banned claims are enforced.
          </p>
        </div>
        <BrandProfileForm
          key={profile.updated_at ?? clientId}
          clientId={clientId}
          profile={profile}
          onSaved={(updated) => {
            setData((prev) => (prev ? { ...prev, profile: updated } : prev));
            void load();
          }}
        />
      </section>

      {/* Brand memory */}
      <section id="memory" className={sectionCard + " p-6"}>
        <div className="mb-4">
          <h2 className="font-medium text-slate-900">Brand memory</h2>
          <p className="text-sm text-slate-500 mt-0.5">
            Pages and documents are chunked and embedded so agents can retrieve grounded facts.
          </p>
        </div>
        <BrandMemoryPanel
          clientId={clientId}
          chunks={memory}
          onChanged={async () => {
            const chunks = await websites.brandMemory.list(clientId);
            setData((prev) => (prev ? { ...prev, memory: chunks } : prev));
          }}
        />
      </section>

      {/* Competitors */}
      <section id="competitors" className={sectionCard + " p-6"}>
        <div className="mb-4">
          <h2 className="font-medium text-slate-900">Competitors</h2>
          <p className="text-sm text-slate-500 mt-0.5">
            Used to attribute citations and mentions, and to detect where rivals are cited instead of you.
          </p>
        </div>
        <CompetitorsPanel
          clientId={clientId}
          competitors={competitors}
          onChanged={async () => {
            const next = await websites.competitors.list(clientId);
            setData((prev) => (prev ? { ...prev, competitors: next } : prev));
          }}
        />
      </section>

      {/* Personas */}
      <section id="personas" className={sectionCard + " p-6"}>
        <div className="mb-4">
          <h2 className="font-medium text-slate-900">Personas</h2>
          <p className="text-sm text-slate-500 mt-0.5">Prompts are mapped to personas so coverage mirrors the buying journey.</p>
        </div>
        <PersonasPanel
          clientId={clientId}
          personas={personas}
          onChanged={async () => {
            const next = await websites.personas.list(clientId);
            setData((prev) => (prev ? { ...prev, personas: next } : prev));
          }}
        />
      </section>

      {/* Publishing */}
      <section id="publishing" className={sectionCard + " p-6"}>
        <div className="flex items-center justify-between">
          <h2 className="font-medium text-slate-900">Publishing</h2>
          <span className="px-2.5 py-1 rounded-full text-xs font-medium bg-slate-100 text-slate-600 border border-slate-200">
            Not configured
          </span>
        </div>
        <p className="text-sm text-slate-500 mt-2">
          WordPress and static-feeds publishing are planned, not configured yet. When connected, nothing is published
          without an approved version of the content.
        </p>
      </section>
    </div>
  );
}
