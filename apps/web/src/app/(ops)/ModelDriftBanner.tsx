"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { AlertTriangle, ArrowRight, X } from "lucide-react";
import { adminApi, ModelDriftSummary } from "@/lib/api";

export default function ModelDriftBanner() {
  const [drift, setDrift] = useState<ModelDriftSummary | null>(null);
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    async function checkDrift() {
      try {
        const summary = await adminApi.getModelDriftSummary();
        setDrift(summary);
      } catch {
        // Non-admin or unauthenticated, ignore banner
        setDrift(null);
      }
    }
    void checkDrift();
  }, []);

  if (dismissed || !drift || (!drift.has_unbaselined_drift && !drift.latest_release)) {
    return null;
  }

  return (
    <div className="bg-amber-500/10 border-b border-amber-500/20 px-8 py-2.5 flex items-center justify-between text-xs text-amber-900 animate-in fade-in duration-300">
      <div className="flex items-center gap-2.5">
        <span className="p-1 rounded bg-amber-500 text-white font-bold flex items-center justify-center">
          <AlertTriangle className="w-3.5 h-3.5" />
        </span>
        <span className="font-semibold text-amber-950">Engine Release Alert:</span>
        <span>
          {drift.latest_release ? (
            <>
              Drift detected in <strong className="capitalize">{drift.latest_release.engine}</strong> ({drift.latest_release.model_label}).
              {" "}
            </>
          ) : (
            <>AI Engine updates detected. </>
          )}
          {drift.never_baselined_prompts > 0 && (
            <span>
              {drift.never_baselined_prompts} prompt{drift.never_baselined_prompts === 1 ? "" : "s"} require baseline calibration.
            </span>
          )}
        </span>
      </div>
      <div className="flex items-center gap-3">
        <Link
          href="/ops/admin"
          className="font-medium text-amber-950 hover:text-amber-800 underline underline-offset-2 flex items-center gap-1"
        >
          Calibrate & Re-baseline <ArrowRight className="w-3 h-3" />
        </Link>
        <button
          onClick={() => setDismissed(true)}
          className="text-amber-700 hover:text-amber-950 p-1 rounded hover:bg-amber-200/50 transition-colors"
          title="Dismiss alert"
        >
          <X className="w-3.5 h-3.5" />
        </button>
      </div>
    </div>
  );
}
