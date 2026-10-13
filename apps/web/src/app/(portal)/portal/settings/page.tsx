"use client";

import { useEffect, useState } from "react";
import {
  Check,
  Copy,
  Globe,
  Loader2,
  RefreshCw,
  Shield,
  ShieldAlert,
  Sparkles,
  Target,
  Zap,
} from "lucide-react";
import {
  PortalSettings,
  portalApi,
  getSelectedClientId,
} from "@/lib/api";

export default function ClientSettingsPage() {
  const [settings, setSettings] = useState<PortalSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    const activeCid = getSelectedClientId() || undefined;
    portalApi.getMe(activeCid)
      .then(async (me) => {
        const data = await portalApi.getSettings(me.active_client_id || undefined);
        setSettings(data);
      })
      .catch((err) => {
        setError(err.message || "Failed to load client settings");
      })
      .finally(() => {
        setLoading(false);
      });
  }, []);

  const copyKey = () => {
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  if (loading) {
    return (
      <div className="h-96 flex flex-col items-center justify-center text-slate-400 gap-3">
        <Loader2 className="w-8 h-8 animate-spin text-slate-700" />
        <span className="text-sm font-medium">Loading brand settings...</span>
      </div>
    );
  }

  if (error || !settings) {
    return (
      <div className="bg-rose-50 border border-rose-200 text-rose-800 p-6 rounded-2xl text-sm max-w-xl mx-auto my-12">
        <div className="flex items-center gap-2 font-bold mb-1">
          <ShieldAlert className="w-5 h-5 text-rose-600" />
          <span>Settings Error</span>
        </div>
        <p>{error || "Unable to retrieve settings for this brand"}</p>
      </div>
    );
  }

  return (
    <div className="space-y-8 animate-in fade-in duration-500 max-w-4xl pb-12">
      <div>
        <h1 className="text-3xl font-bold tracking-tight text-slate-900 mb-1">
          Brand Settings &amp; Configuration
        </h1>
        <p className="text-slate-500 text-sm">
          Brand memory profiles, publishing channel connections, and edge feed tokens for {settings.name}.
        </p>
      </div>

      {/* Brand Identity & Governance Overview */}
      <div className="bg-white border border-slate-200 rounded-2xl p-6 md:p-8 shadow-2xs space-y-6">
        <div className="flex items-center justify-between border-b border-slate-100 pb-4">
          <div>
            <h2 className="text-lg font-bold text-slate-900">{settings.name}</h2>
            <p className="text-xs text-slate-500">
              Primary Domain: <span className="font-mono text-slate-700 font-medium">{settings.primary_domain}</span> &bull; Industry: {settings.industry || "General"}
            </p>
          </div>
          <span className="px-3 py-1 rounded-full text-xs font-bold uppercase tracking-wider bg-emerald-50 text-emerald-800 border border-emerald-200">
            {settings.status}
          </span>
        </div>

        {/* Brand Memory Summary */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <div className="bg-slate-50 p-4 rounded-xl border border-slate-200/80">
            <span className="text-xs text-slate-500 font-semibold uppercase">Voice Tone</span>
            <p className="text-sm font-bold text-slate-900 mt-1 capitalize">
              {settings.voice || "Authoritative & Objective"}
            </p>
          </div>
          <div className="bg-slate-50 p-4 rounded-xl border border-slate-200/80">
            <span className="text-xs text-slate-500 font-semibold uppercase">Proof Points</span>
            <p className="text-sm font-bold text-slate-900 mt-1">
              {settings.proof_points_count} Verified Claims
            </p>
          </div>
          <div className="bg-slate-50 p-4 rounded-xl border border-slate-200/80">
            <span className="text-xs text-slate-500 font-semibold uppercase">Banned Claims</span>
            <p className="text-sm font-bold text-slate-900 mt-1">
              {settings.banned_claims_count} Guardrail Rules
            </p>
          </div>
        </div>

        {settings.positioning && (
          <div>
            <label className="block text-xs font-bold uppercase tracking-wider text-slate-400 mb-1">
              Brand Positioning Statement
            </label>
            <p className="text-xs text-slate-700 bg-slate-50 p-3.5 rounded-xl border border-slate-200/70 leading-relaxed font-sans">
              {settings.positioning}
            </p>
          </div>
        )}
      </div>

      {/* Publishing Targets & Competitors */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Connected Channels */}
        <div className="bg-white border border-slate-200 rounded-2xl p-6 shadow-2xs space-y-4">
          <div className="flex items-center gap-2">
            <Zap className="w-4 h-4 text-slate-600" />
            <h3 className="text-sm font-bold text-slate-900">Publishing Targets</h3>
          </div>
          {settings.publish_targets.length === 0 ? (
            <p className="text-xs text-slate-500">No external CMS webhooks currently connected.</p>
          ) : (
            <div className="space-y-2">
              {settings.publish_targets.map((pt, idx) => (
                <div
                  key={idx}
                  className="flex items-center justify-between p-2.5 bg-slate-50 rounded-lg border border-slate-200/80 text-xs"
                >
                  <span className="font-semibold text-slate-800 uppercase">{pt.kind}</span>
                  <span className="text-[10px] font-bold uppercase px-2 py-0.5 rounded bg-emerald-100 text-emerald-800">
                    {pt.status}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Tracked Competitors */}
        <div className="bg-white border border-slate-200 rounded-2xl p-6 shadow-2xs space-y-4">
          <div className="flex items-center gap-2">
            <Target className="w-4 h-4 text-slate-600" />
            <h3 className="text-sm font-bold text-slate-900">Tracked Competitors</h3>
          </div>
          {settings.competitor_domains.length === 0 ? (
            <p className="text-xs text-slate-500">No competitor benchmarks assigned yet.</p>
          ) : (
            <div className="flex flex-wrap gap-2">
              {settings.competitor_domains.map((dom, idx) => (
                <span
                  key={idx}
                  className="inline-flex items-center px-2.5 py-1 bg-slate-100 text-slate-800 rounded-lg text-xs font-mono font-medium border border-slate-200"
                >
                  {dom}
                </span>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Realtime Edge Feeds */}
      <div className="bg-white border border-slate-200 rounded-2xl p-6 md:p-8 shadow-2xs">
        <h3 className="text-base font-bold text-slate-900 mb-2">Realtime Edge Feeds</h3>
        <p className="text-xs text-slate-600 mb-6 leading-relaxed">
          Provide this API endpoint and key to ChatGPT Plugins, custom GPTs, or internal AI agents to grant them secure, realtime access to your approved brand content.
        </p>

        <div className="space-y-4">
          <div>
            <label className="block text-xs font-semibold uppercase tracking-wider text-slate-500 mb-1.5">Endpoint URL</label>
            <div className="flex bg-slate-50 border border-slate-200 rounded-lg p-3 text-xs text-slate-700 font-mono">
              https://feeds.footnote.dev/search
            </div>
          </div>

          <div>
            <label className="block text-xs font-semibold uppercase tracking-wider text-slate-500 mb-1.5">Bearer API Key</label>
            <div className="flex items-center">
              <div className="flex-1 flex bg-slate-50 border border-slate-200 rounded-l-lg p-3 text-xs text-slate-700 font-mono overflow-hidden whitespace-nowrap overflow-ellipsis">
                fn_edge_{settings.client_id.replace(/-/g, "").slice(0, 24)}
              </div>
              <button
                onClick={copyKey}
                className="flex items-center justify-center px-4 py-3 bg-white border border-y-slate-200 border-r-slate-200 rounded-r-lg text-slate-600 hover:bg-slate-50 transition"
              >
                {copied ? <Check className="w-4 h-4 text-emerald-500" /> : <Copy className="w-4 h-4" />}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
