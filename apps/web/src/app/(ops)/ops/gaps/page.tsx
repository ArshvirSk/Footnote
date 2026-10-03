"use client";

import { useState, useEffect } from "react";
import { AlertCircle, ArrowDownRight, TrendingDown } from "lucide-react";

interface Gap {
  id: string;
  prompt_text: string;
  gap_type: "slipped" | "competitor_cited";
  competitor_domain?: string;
  detected_at: string;
  status: "open" | "addressed" | "ignored";
}

export default function GapsPage() {
  const [gaps, setGaps] = useState<Gap[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // Stub data mirroring the db gap detection query
    setTimeout(() => {
      setGaps([
        {
          id: "1",
          prompt_text: "Top project management tools for enterprise",
          gap_type: "slipped",
          detected_at: new Date().toISOString(),
          status: "open",
        },
        {
          id: "2",
          prompt_text: "Best CRM for real estate agents",
          gap_type: "competitor_cited",
          competitor_domain: "hubspot.com",
          detected_at: new Date().toISOString(),
          status: "open",
        }
      ]);
      setLoading(false);
    }, 500);
  }, []);

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-end">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight text-slate-900">Gaps & Slips</h1>
          <p className="text-slate-600 mt-1">Automatic detection of lost rankings and competitor citations.</p>
        </div>
        <div className="flex space-x-3">
          <button className="flex items-center px-4 py-2 bg-white border border-slate-200 text-slate-700 rounded-lg hover:bg-slate-50 transition font-medium text-sm shadow-sm">
            Export Report
          </button>
        </div>
      </div>

      <div className="bg-white border border-slate-200 rounded-xl shadow-sm overflow-hidden">
        <table className="w-full text-left text-sm">
          <thead className="bg-slate-50 border-b border-slate-200 text-slate-500">
            <tr>
              <th className="px-6 py-4 font-medium">Issue Type</th>
              <th className="px-6 py-4 font-medium">Query / Prompt</th>
              <th className="px-6 py-4 font-medium">Competitor</th>
              <th className="px-6 py-4 font-medium">Detected</th>
              <th className="px-6 py-4 font-medium">Status</th>
              <th className="px-6 py-4 font-medium text-right">Action</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {loading ? (
              <tr>
                <td colSpan={6} className="px-6 py-8 text-center text-slate-400">Analyzing latest rollup...</td>
              </tr>
            ) : gaps.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-6 py-8 text-center text-slate-400">All good! No gaps detected.</td>
              </tr>
            ) : (
              gaps.map((g) => (
                <tr key={g.id} className="hover:bg-slate-50/50 transition-colors">
                  <td className="px-6 py-4">
                    {g.gap_type === 'slipped' ? (
                      <span className="flex items-center text-amber-700 font-medium">
                        <TrendingDown className="w-4 h-4 mr-1.5" /> Ranking Slipped
                      </span>
                    ) : (
                      <span className="flex items-center text-rose-700 font-medium">
                        <AlertCircle className="w-4 h-4 mr-1.5" /> Competitor Cited
                      </span>
                    )}
                  </td>
                  <td className="px-6 py-4 font-medium text-slate-900">{g.prompt_text}</td>
                  <td className="px-6 py-4 text-slate-600">{g.competitor_domain || "—"}</td>
                  <td className="px-6 py-4 text-slate-600">
                    {new Date(g.detected_at).toLocaleDateString()}
                  </td>
                  <td className="px-6 py-4">
                    <span className="px-2.5 py-1 rounded-full text-xs font-medium bg-slate-100 text-slate-600 border border-slate-200 capitalize">
                      {g.status}
                    </span>
                  </td>
                  <td className="px-6 py-4 text-right">
                    <button className="text-blue-600 hover:text-blue-800 font-medium hover:underline text-sm">
                      Create Brief →
                    </button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
