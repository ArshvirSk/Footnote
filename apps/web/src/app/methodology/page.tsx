"use client";

import { useState } from "react";
import Link from "next/link";
import {
  ArrowLeft,
  ArrowRight,
  BarChart3,
  BookOpen,
  Calculator,
  CheckCircle2,
  ChevronRight,
  Cpu,
  Globe,
  Layers,
  Percent,
  Search,
  ShieldCheck,
  Sparkles,
} from "lucide-react";

export default function MethodologyPage() {
  // Interactive Calculator State
  const [calcBrandMentions, setCalcBrandMentions] = useState(45);
  const [calcCompetitorMentions, setCalcCompetitorMentions] = useState(55);
  const [calcVisiblePrompts, setCalcVisiblePrompts] = useState(38);
  const [calcTotalPrompts, setCalcTotalPrompts] = useState(50);
  const [calcBrandCitations, setCalcBrandCitations] = useState(28);
  const [calcTotalCitations, setCalcTotalCitations] = useState(80);

  // Derived Calculations
  const calculatedSov =
    calcBrandMentions + calcCompetitorMentions > 0
      ? ((calcBrandMentions / (calcBrandMentions + calcCompetitorMentions)) * 100).toFixed(1)
      : "0.0";

  const calculatedVisibility =
    calcTotalPrompts > 0
      ? ((calcVisiblePrompts / calcTotalPrompts) * 100).toFixed(1)
      : "0.0";

  const calculatedCitationShare =
    calcTotalCitations > 0
      ? ((calcBrandCitations / calcTotalCitations) * 100).toFixed(1)
      : "0.0";

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 selection:bg-indigo-500 selection:text-white font-sans antialiased">
      {/* Top Navigation */}
      <header className="border-b border-slate-800/80 bg-slate-950/70 backdrop-blur-md sticky top-0 z-40">
        <div className="max-w-7xl mx-auto px-6 h-16 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Link href="/" className="flex items-center gap-2 text-white font-extrabold tracking-tight text-lg">
              <span className="w-8 h-8 rounded-xl bg-gradient-to-tr from-indigo-500 to-emerald-400 flex items-center justify-center text-slate-950 font-black shadow-lg shadow-indigo-500/20">
                F
              </span>
              Footnote
            </Link>
            <span className="text-xs uppercase tracking-widest px-2.5 py-0.5 rounded-full bg-slate-800 text-slate-400 font-semibold border border-slate-700/60 ml-2">
              Methodology
            </span>
          </div>

          <div className="flex items-center gap-4">
            <Link
              href="/ops"
              className="text-xs text-slate-400 hover:text-white font-medium transition"
            >
              Ops Console
            </Link>
            <Link
              href="/login"
              className="text-xs bg-white hover:bg-slate-100 text-slate-950 font-semibold px-4 py-2 rounded-xl shadow transition"
            >
              Sign In
            </Link>
          </div>
        </div>
      </header>

      {/* Hero Section */}
      <section className="relative overflow-hidden pt-16 pb-20 border-b border-slate-800">
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_80%_80%_at_50%_-20%,rgba(99,102,241,0.25),rgba(255,255,255,0))]" />
        
        <div className="max-w-5xl mx-auto px-6 relative z-10 text-center space-y-6">
          <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full bg-indigo-500/10 border border-indigo-500/30 text-indigo-400 text-xs font-semibold">
            <Sparkles className="w-3.5 h-3.5" />
            <span>FR-28 Public Measurement Framework</span>
          </div>

          <h1 className="text-4xl md:text-5xl font-black tracking-tight text-white leading-tight">
            Scientific Measurement for <br />
            <span className="bg-gradient-to-r from-indigo-400 via-sky-300 to-emerald-400 bg-clip-text text-transparent">
              Generative Engine Optimization
            </span>
          </h1>

          <p className="text-base md:text-lg text-slate-400 max-w-2xl mx-auto leading-relaxed">
            Every metric, ratio, and citation tracked by Footnote is derived from deterministic statistical models. Here is the mathematical framework behind our AEO intelligence platform.
          </p>
        </div>
      </section>

      {/* Main Content */}
      <main className="max-w-5xl mx-auto px-6 py-16 space-y-20">
        {/* Section 1: Core Mathematical Definitions */}
        <section className="space-y-8">
          <div>
            <h2 className="text-2xl font-bold tracking-tight text-white flex items-center gap-2.5">
              <BookOpen className="w-6 h-6 text-indigo-400" />
              Core Metric Definitions
            </h2>
            <p className="text-sm text-slate-400 mt-1">
              Standard formulas utilized across daily batch runs, analytics rollups, and client visibility dashboards.
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {/* Metric Card 1: Visibility % */}
            <div className="bg-slate-900/60 border border-slate-800 rounded-2xl p-6 space-y-4 hover:border-slate-700 transition">
              <div className="flex items-center justify-between">
                <span className="text-xs font-bold text-indigo-400 uppercase tracking-wider">Metric Formula 01</span>
                <span className="text-xs px-2 py-0.5 rounded bg-indigo-500/20 text-indigo-300 font-mono">0.0% – 100.0%</span>
              </div>
              <h3 className="text-lg font-bold text-white">AI Engine Visibility %</h3>
              <div className="bg-slate-950 p-3.5 rounded-xl border border-slate-800/80 font-mono text-xs text-emerald-400">
                Visibility % = (Visible Prompts ÷ Total Tracked Prompts) × 100
              </div>
              <p className="text-xs text-slate-400 leading-relaxed">
                A prompt is classified as <strong>visible</strong> on a given day/engine if the target brand is affirmatively mentioned in <strong>&ge; 50%</strong> of that day&apos;s repeated sample runs (<em>k = 3</em> runs per prompt).
              </p>
            </div>

            {/* Metric Card 2: Share of Voice */}
            <div className="bg-slate-900/60 border border-slate-800 rounded-2xl p-6 space-y-4 hover:border-slate-700 transition">
              <div className="flex items-center justify-between">
                <span className="text-xs font-bold text-sky-400 uppercase tracking-wider">Metric Formula 02</span>
                <span className="text-xs px-2 py-0.5 rounded bg-sky-500/20 text-sky-300 font-mono">SOV Index</span>
              </div>
              <h3 className="text-lg font-bold text-white">Share of Voice (SOV)</h3>
              <div className="bg-slate-950 p-3.5 rounded-xl border border-slate-800/80 font-mono text-xs text-emerald-400">
                SOV % = [ Brand Mentions ÷ (Brand + Competitor Mentions) ] × 100
              </div>
              <p className="text-xs text-slate-400 leading-relaxed">
                Measures market mindshare within generative answers. When answers evaluate multiple solutions, SOV calculates the relative frequency of brand inclusion against direct competitor aliases.
              </p>
            </div>

            {/* Metric Card 3: Citation Share */}
            <div className="bg-slate-900/60 border border-slate-800 rounded-2xl p-6 space-y-4 hover:border-slate-700 transition">
              <div className="flex items-center justify-between">
                <span className="text-xs font-bold text-emerald-400 uppercase tracking-wider">Metric Formula 03</span>
                <span className="text-xs px-2 py-0.5 rounded bg-emerald-500/20 text-emerald-300 font-mono">Domain Ratio</span>
              </div>
              <h3 className="text-lg font-bold text-white">Citation Share &amp; Linked Rate</h3>
              <div className="bg-slate-950 p-3.5 rounded-xl border border-slate-800/80 font-mono text-xs text-emerald-400">
                Citation Share = Owned Domain Citations ÷ Total Answer Citations
              </div>
              <p className="text-xs text-slate-400 leading-relaxed">
                Evaluates source authority. Mentions without hyperlinks are non-attributed; <strong>Linked Rate</strong> measures the percentage of brand mentions that successfully provide a direct canonical hyperlink back to the brand.
              </p>
            </div>

            {/* Metric Card 4: Gaps & Slips */}
            <div className="bg-slate-900/60 border border-slate-800 rounded-2xl p-6 space-y-4 hover:border-slate-700 transition">
              <div className="flex items-center justify-between">
                <span className="text-xs font-bold text-amber-400 uppercase tracking-wider">Metric Formula 04</span>
                <span className="text-xs px-2 py-0.5 rounded bg-amber-500/20 text-amber-300 font-mono">Delta Signals</span>
              </div>
              <h3 className="text-lg font-bold text-white">Competitive Gaps &amp; Slips</h3>
              <div className="bg-slate-950 p-3.5 rounded-xl border border-slate-800/80 font-mono text-xs text-emerald-400">
                Gap = Competitor Mentioned ∧ Brand Unmentioned
              </div>
              <p className="text-xs text-slate-400 leading-relaxed">
                A <strong>Gap</strong> triggers when a tracked high-intent prompt cites competing solutions while omitting the brand. A <strong>Slip</strong> flags prompts that were visible in the trailing 7-day baseline but failed in the current observation.
              </p>
            </div>
          </div>
        </section>

        {/* Section 2: Interactive Metric Calculator */}
        <section className="bg-slate-900 border border-slate-800 rounded-3xl p-8 md:p-10 space-y-8 relative overflow-hidden">
          <div className="absolute top-0 right-0 w-96 h-96 bg-indigo-500/5 rounded-full blur-3xl pointer-events-none" />

          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-slate-800 pb-6">
            <div>
              <h2 className="text-2xl font-bold tracking-tight text-white flex items-center gap-2.5">
                <Calculator className="w-6 h-6 text-emerald-400" />
                Interactive Metric Simulator
              </h2>
              <p className="text-sm text-slate-400 mt-1">
                Simulate how changes in mention frequencies, prompt volume, and citations affect overall AI visibility scores.
              </p>
            </div>

            <span className="text-xs font-bold text-emerald-400 px-3 py-1 rounded-full bg-emerald-500/10 border border-emerald-500/30">
              Live Calculation
            </span>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-10">
            {/* Input Sliders */}
            <div className="space-y-6">
              <div>
                <div className="flex justify-between text-xs font-semibold mb-2">
                  <span className="text-slate-300">Brand Mentions</span>
                  <span className="text-indigo-400 font-mono">{calcBrandMentions} runs</span>
                </div>
                <input
                  type="range"
                  min="0"
                  max="150"
                  value={calcBrandMentions}
                  onChange={(e) => setCalcBrandMentions(parseInt(e.target.value, 10))}
                  className="w-full accent-indigo-500 cursor-pointer"
                />
              </div>

              <div>
                <div className="flex justify-between text-xs font-semibold mb-2">
                  <span className="text-slate-300">Competitor Mentions</span>
                  <span className="text-indigo-400 font-mono">{calcCompetitorMentions} runs</span>
                </div>
                <input
                  type="range"
                  min="0"
                  max="150"
                  value={calcCompetitorMentions}
                  onChange={(e) => setCalcCompetitorMentions(parseInt(e.target.value, 10))}
                  className="w-full accent-indigo-500 cursor-pointer"
                />
              </div>

              <div>
                <div className="flex justify-between text-xs font-semibold mb-2">
                  <span className="text-slate-300">Prompts Visible (&ge;50% inclusion)</span>
                  <span className="text-emerald-400 font-mono">{calcVisiblePrompts} of {calcTotalPrompts}</span>
                </div>
                <input
                  type="range"
                  min="0"
                  max={calcTotalPrompts}
                  value={calcVisiblePrompts}
                  onChange={(e) => setCalcVisiblePrompts(parseInt(e.target.value, 10))}
                  className="w-full accent-emerald-500 cursor-pointer"
                />
              </div>

              <div>
                <div className="flex justify-between text-xs font-semibold mb-2">
                  <span className="text-slate-300">Verified Brand Citations</span>
                  <span className="text-sky-400 font-mono">{calcBrandCitations} of {calcTotalCitations} total</span>
                </div>
                <input
                  type="range"
                  min="0"
                  max={calcTotalCitations}
                  value={calcBrandCitations}
                  onChange={(e) => setCalcBrandCitations(parseInt(e.target.value, 10))}
                  className="w-full accent-sky-500 cursor-pointer"
                />
              </div>
            </div>

            {/* Derived Results Cards */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div className="p-6 rounded-2xl bg-slate-950 border border-slate-800 space-y-1">
                <div className="text-xs uppercase font-bold text-slate-500">Calculated SOV</div>
                <div className="text-3xl font-black text-indigo-400 font-mono">{calculatedSov}%</div>
                <p className="text-[11px] text-slate-500 pt-1">
                  Brand ratio among {calcBrandMentions + calcCompetitorMentions} total mentions
                </p>
              </div>

              <div className="p-6 rounded-2xl bg-slate-950 border border-slate-800 space-y-1">
                <div className="text-xs uppercase font-bold text-slate-500">Visibility Score</div>
                <div className="text-3xl font-black text-emerald-400 font-mono">{calculatedVisibility}%</div>
                <p className="text-[11px] text-slate-500 pt-1">
                  {calcVisiblePrompts} out of {calcTotalPrompts} active tracked prompts
                </p>
              </div>

              <div className="p-6 rounded-2xl bg-slate-950 border border-slate-800 space-y-1 sm:col-span-2">
                <div className="text-xs uppercase font-bold text-slate-500">Citation Authority Share</div>
                <div className="text-3xl font-black text-sky-400 font-mono">{calculatedCitationShare}%</div>
                <p className="text-[11px] text-slate-500 pt-1">
                  {calcBrandCitations} direct domain citations out of {calcTotalCitations} category-wide references
                </p>
              </div>
            </div>
          </div>
        </section>

        {/* Section 3: Engine Sampling & Non-Determinism Transparency */}
        <section className="space-y-6">
          <div>
            <h2 className="text-2xl font-bold tracking-tight text-white flex items-center gap-2.5">
              <ShieldCheck className="w-6 h-6 text-sky-400" />
              Statistical Confidence &amp; Engine Non-Determinism
            </h2>
            <p className="text-sm text-slate-400 mt-1">
              Frontier LLMs exhibit temperature-driven variance. Footnote resolves variance via multi-run sampling.
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            <div className="p-6 rounded-2xl bg-slate-900/60 border border-slate-800 space-y-3">
              <div className="text-sm font-bold text-white flex items-center gap-2">
                <CheckCircle2 className="w-4 h-4 text-emerald-400" /> k-Sample Repeated Runs
              </div>
              <p className="text-xs text-slate-400 leading-relaxed">
                Rather than relying on single queries, Footnote executes <strong>k = 3</strong> independent repeated queries with jitter per prompt every 24 hours to observe true probabilistic inclusion.
              </p>
            </div>

            <div className="p-6 rounded-2xl bg-slate-900/60 border border-slate-800 space-y-3">
              <div className="text-sm font-bold text-white flex items-center gap-2">
                <CheckCircle2 className="w-4 h-4 text-emerald-400" /> Grounded Proof-Point Attribution
              </div>
              <p className="text-xs text-slate-400 leading-relaxed">
                AI engines rarely cite claims without authority proof points. We trace every brand mention back to either a direct domain URL or authoritative third-party source (e.g. Reddit, review platforms).
              </p>
            </div>

            <div className="p-6 rounded-2xl bg-slate-900/60 border border-slate-800 space-y-3">
              <div className="text-sm font-bold text-white flex items-center gap-2">
                <CheckCircle2 className="w-4 h-4 text-emerald-400" /> Model Drift Detection
              </div>
              <p className="text-xs text-slate-400 leading-relaxed">
                When engine providers deploy stealth updates (e.g. GPT-4o revisions, Gemini shifts), our background detector flags prompts for recalibration to prevent false decay signals.
              </p>
            </div>
          </div>
        </section>
      </main>

      {/* Footer */}
      <footer className="border-t border-slate-800/80 bg-slate-950 py-12 text-slate-500 text-xs">
        <div className="max-w-5xl mx-auto px-6 flex flex-col sm:flex-row items-center justify-between gap-4">
          <div>
            &copy; {new Date().getFullYear()} Footnote Platform. Proprietary AEO/GEO measurement framework.
          </div>
          <div className="flex items-center gap-6">
            <Link href="/" className="hover:text-slate-300 transition">Home</Link>
            <Link href="/ops" className="hover:text-slate-300 transition">Ops Console</Link>
            <Link href="/login" className="hover:text-slate-300 transition">Client Portal</Link>
          </div>
        </div>
      </footer>
    </div>
  );
}
