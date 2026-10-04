"use client";

import { useState } from "react";
import { Info } from "lucide-react";
import type { Metric } from "../lib/api";
import { pct } from "../lib/ui";

interface MetricCardProps {
  label: string;
  metric: Metric;
  /** Optional formatter override (e.g. counts instead of rates). */
  format?: (metric: Metric) => string;
  /** Extra caption shown under the value (e.g. "3 of 5 runs"). */
  sample?: string;
}

/** A KPI card that always shows the sample size and its calculation formula. */
export default function MetricCard({ label, metric, format, sample }: MetricCardProps) {
  const [showFormula, setShowFormula] = useState(false);
  const value = format ? format(metric) : pct(metric.value);
  const delta =
    metric.value !== null && metric.prior_value !== null ? metric.value - metric.prior_value : null;

  return (
    <div className="bg-white p-5 rounded-xl border border-slate-200 shadow-sm flex flex-col">
      <div className="flex items-start justify-between gap-2">
        <div className="text-sm font-medium text-slate-500">{label}</div>
        <button
          type="button"
          onClick={() => setShowFormula((v) => !v)}
          aria-label={`How ${label} is calculated`}
          aria-expanded={showFormula}
          className="text-slate-300 hover:text-slate-500 transition shrink-0"
        >
          <Info className="w-4 h-4" />
        </button>
      </div>
      <div className="text-2xl font-semibold text-slate-900 mt-2">{value}</div>
      {sample && <div className="text-xs text-slate-500 mt-1">{sample}</div>}
      {delta !== null && (
        <div
          className={`text-xs font-medium mt-2 ${delta > 0 ? "text-emerald-600" : delta < 0 ? "text-rose-600" : "text-slate-400"}`}
        >
          {delta > 0 ? "+" : ""}
          {(delta * 100).toFixed(1)} pts vs prior 7 days
        </div>
      )}
      {showFormula && (
        <div className="mt-3 pt-3 border-t border-slate-100 text-xs text-slate-500 leading-relaxed">
          {metric.formula}
          <div className="mt-1 text-slate-400">
            Sample: {metric.current} / {metric.base}
            {metric.prior_base ? ` · prior window ${metric.prior_current} / ${metric.prior_base}` : ""}
          </div>
        </div>
      )}
    </div>
  );
}
