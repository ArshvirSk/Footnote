"use client";

import { useState } from "react";
import { Check, Plus, Trash2 } from "lucide-react";
import { websites, type BrandProfile } from "../lib/api";

interface BrandProfileFormProps {
  clientId: string;
  profile: BrandProfile;
  onSaved: (profile: BrandProfile) => void;
}

function linesToList(value: string): string[] {
  return value
    .split("\n")
    .map((v) => v.trim())
    .filter(Boolean);
}

/** Brand profile editor: voice, positioning, products, ICP, proof points, banned claims, aliases. */
export default function BrandProfileForm({ clientId, profile, onSaved }: BrandProfileFormProps) {
  const [voice, setVoice] = useState(profile.voice ?? "");
  const [positioning, setPositioning] = useState(profile.positioning ?? "");
  const [products, setProducts] = useState(profile.products ?? []);
  const [icpSummary, setIcpSummary] = useState(profile.icp?.summary ?? "");
  const [icpSegments, setIcpSegments] = useState((profile.icp?.segments ?? []).join("\n"));
  const [proofPoints, setProofPoints] = useState(profile.proof_points ?? []);
  const [bannedClaims, setBannedClaims] = useState((profile.banned_claims ?? []).join("\n"));
  const [aliases, setAliases] = useState((profile.aliases ?? []).join(", "));
  const [themeHtml, setThemeHtml] = useState(profile.theme_html ?? "");
  const [themeCss, setThemeCss] = useState(profile.theme_css ?? "");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // The parent keys this component by profile.updated_at, so a fresh save
  // remounts the form with the saved values instead of syncing via an effect.

  async function onSave(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      const updated = await websites.brandProfile.put(clientId, {
        voice: voice.trim() || null,
        positioning: positioning.trim() || null,
        products: products.filter((p) => p.name.trim()),
        icp: { summary: icpSummary.trim(), segments: linesToList(icpSegments) },
        proof_points: proofPoints.filter((p) => p.claim.trim()),
        banned_claims: linesToList(bannedClaims),
        theme_html: themeHtml.trim() || null,
        theme_css: themeCss.trim() || null,
        aliases: aliases
          .split(",")
          .map((a) => a.trim())
          .filter(Boolean),
      });
      onSaved(updated);
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save brand profile");
    } finally {
      setSaving(false);
    }
  }

  const inputClass =
    "w-full px-3 py-2 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-slate-900";

  return (
    <form onSubmit={onSave} className="space-y-6">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div>
          <label htmlFor="brand-voice" className="block text-sm font-medium text-slate-700 mb-1">
            Voice
          </label>
          <textarea
            id="brand-voice"
            value={voice}
            onChange={(e) => setVoice(e.target.value)}
            rows={3}
            placeholder="e.g. Plain-spoken, evidence-led, no hype"
            className={inputClass}
          />
        </div>
        <div>
          <label htmlFor="brand-positioning" className="block text-sm font-medium text-slate-700 mb-1">
            Positioning
          </label>
          <textarea
            id="brand-positioning"
            value={positioning}
            onChange={(e) => setPositioning(e.target.value)}
            rows={3}
            placeholder="What the brand is and who it is for"
            className={inputClass}
          />
        </div>
      </div>

      <div>
        <label htmlFor="brand-aliases" className="block text-sm font-medium text-slate-700 mb-1">
          Brand aliases <span className="text-slate-400 font-normal">(comma-separated, used by mention detection)</span>
        </label>
        <input
          id="brand-aliases"
          value={aliases}
          onChange={(e) => setAliases(e.target.value)}
          placeholder="e.g. DBA, DBA Consultants"
          className={inputClass}
        />
      </div>

      <div>
        <div className="flex items-center justify-between mb-2">
          <span className="text-sm font-medium text-slate-700">Products</span>
          <button
            type="button"
            onClick={() => setProducts([...products, { name: "", category: "" }])}
            className="inline-flex items-center text-xs font-medium text-blue-600 hover:text-blue-800"
          >
            <Plus className="w-3.5 h-3.5 mr-1" /> Add product
          </button>
        </div>
        {products.length === 0 && <p className="text-xs text-slate-400">No products added yet.</p>}
        <div className="space-y-2">
          {products.map((p, idx) => (
            <div key={idx} className="flex gap-2">
              <input
                value={p.name}
                onChange={(e) =>
                  setProducts(products.map((x, i) => (i === idx ? { ...x, name: e.target.value } : x)))
                }
                placeholder="Product name"
                className={`${inputClass} flex-1`}
              />
              <input
                value={p.category ?? ""}
                onChange={(e) =>
                  setProducts(products.map((x, i) => (i === idx ? { ...x, category: e.target.value } : x)))
                }
                placeholder="Category"
                className={`${inputClass} flex-1`}
              />
              <button
                type="button"
                onClick={() => setProducts(products.filter((_, i) => i !== idx))}
                className="text-slate-300 hover:text-rose-500 px-1"
                aria-label="Remove product"
              >
                <Trash2 className="w-4 h-4" />
              </button>
            </div>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div>
          <label htmlFor="brand-icp" className="block text-sm font-medium text-slate-700 mb-1">
            ICP summary
          </label>
          <textarea
            id="brand-icp"
            value={icpSummary}
            onChange={(e) => setIcpSummary(e.target.value)}
            rows={3}
            placeholder="Ideal customer profile in one or two sentences"
            className={inputClass}
          />
        </div>
        <div>
          <label htmlFor="brand-segments" className="block text-sm font-medium text-slate-700 mb-1">
            ICP segments <span className="text-slate-400 font-normal">(one per line)</span>
          </label>
          <textarea
            id="brand-segments"
            value={icpSegments}
            onChange={(e) => setIcpSegments(e.target.value)}
            rows={3}
            placeholder={"Mid-market analytics teams\nRetail planning leads"}
            className={inputClass}
          />
        </div>
      </div>

      <div>
        <div className="flex items-center justify-between mb-2">
          <span className="text-sm font-medium text-slate-700">
            Proof points <span className="text-slate-400 font-normal">(claims the agents may use, with a source)</span>
          </span>
          <button
            type="button"
            onClick={() => setProofPoints([...proofPoints, { claim: "", source: "" }])}
            className="inline-flex items-center text-xs font-medium text-blue-600 hover:text-blue-800"
          >
            <Plus className="w-3.5 h-3.5 mr-1" /> Add proof point
          </button>
        </div>
        {proofPoints.length === 0 && <p className="text-xs text-slate-400">No proof points added yet.</p>}
        <div className="space-y-2">
          {proofPoints.map((p, idx) => (
            <div key={idx} className="flex gap-2">
              <input
                value={p.claim}
                onChange={(e) =>
                  setProofPoints(proofPoints.map((x, i) => (i === idx ? { ...x, claim: e.target.value } : x)))
                }
                placeholder="Claim (e.g. ISO 27001 certified)"
                className={`${inputClass} flex-1`}
              />
              <input
                value={p.source ?? ""}
                onChange={(e) =>
                  setProofPoints(proofPoints.map((x, i) => (i === idx ? { ...x, source: e.target.value } : x)))
                }
                placeholder="Source URL"
                className={`${inputClass} flex-1`}
              />
              <button
                type="button"
                onClick={() => setProofPoints(proofPoints.filter((_, i) => i !== idx))}
                className="text-slate-300 hover:text-rose-500 px-1"
                aria-label="Remove proof point"
              >
                <Trash2 className="w-4 h-4" />
              </button>
            </div>
          ))}
        </div>
      </div>

      <div>
        <label htmlFor="brand-banned" className="block text-sm font-medium text-slate-700 mb-1">
          Banned claims <span className="text-slate-400 font-normal">(one per line, enforced for all content)</span>
        </label>
        <textarea
          id="brand-banned"
          value={bannedClaims}
          onChange={(e) => setBannedClaims(e.target.value)}
          rows={3}
          placeholder={"guaranteed results\n#1 in the market"}
          className={inputClass}
        />
      </div>

      <details className="border border-slate-200 rounded-lg">
        <summary className="px-4 py-3 text-sm font-medium text-slate-700 cursor-pointer">
          Theme (HTML/CSS for feeds and previews)
        </summary>
        <div className="p-4 pt-0 space-y-4">
          <div>
            <label htmlFor="theme-html" className="block text-xs font-medium text-slate-600 mb-1">
              Theme HTML
            </label>
            <textarea
              id="theme-html"
              value={themeHtml}
              onChange={(e) => setThemeHtml(e.target.value)}
              rows={4}
              className={`${inputClass} font-mono text-xs`}
            />
          </div>
          <div>
            <label htmlFor="theme-css" className="block text-xs font-medium text-slate-600 mb-1">
              Theme CSS
            </label>
            <textarea
              id="theme-css"
              value={themeCss}
              onChange={(e) => setThemeCss(e.target.value)}
              rows={4}
              className={`${inputClass} font-mono text-xs`}
            />
          </div>
        </div>
      </details>

      {error && (
        <div className="text-sm text-rose-600 bg-rose-50 border border-rose-200 rounded-lg px-4 py-3">{error}</div>
      )}

      <div className="flex items-center gap-3">
        <button
          type="submit"
          disabled={saving}
          className="px-4 py-2 bg-slate-900 text-white rounded-lg hover:bg-slate-800 transition font-medium text-sm disabled:opacity-60"
        >
          {saving ? "Saving…" : "Save brand profile"}
        </button>
        {saved && (
          <span className="flex items-center text-sm text-emerald-600 font-medium">
            <Check className="w-4 h-4 mr-1" /> Saved
          </span>
        )}
        {profile.updated_at && !saved && (
          <span className="text-xs text-slate-400">
            Last saved {new Date(profile.updated_at).toLocaleString()}
          </span>
        )}
      </div>
    </form>
  );
}
